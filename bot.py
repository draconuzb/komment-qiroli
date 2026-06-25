"""Telegram avtomatlashtirish:

- Kanalga (bot admin bo'lgan) yoki ruxsatli DM'ga Instagram havolasi tashlansa,
  bot HAR AKKAUNT uchun o'sha akkaunt XUSUSIYATIga + post matniga mos ALOHIDA
  komment yaratadi, joylaydi va (iloji bo'lsa) like bosadi.
- Holat (qaysi akkaunt joyladi / xato) o'sha kanalga/chatga yozib turiladi.

Bot admin bo'lishi shart (kanal postlarini o'qishi uchun). TELEGRAM_CHANNEL_ID
berilsa — faqat o'sha kanal; bo'sh bo'lsa — bot admin bo'lgan har qanday kanal.
"""
import asyncio
import datetime
import logging
import os
import re

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import ai_client
import instagram_client
import history

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

_IG_URL_RE = re.compile(r"https?://(www\.)?instagram\.com/\S+")
# Web-app (uvicorn) shu konteyner ichida — navbatga qo'shishni HTTP orqali qilamiz
# (navbat faylini faqat bitta jarayon yozsin).
_INTERNAL_URL = f"http://127.0.0.1:{os.getenv('PORT', '8000')}"


def _authorized(update: Update) -> bool:
    if not config.ALLOWED_TELEGRAM_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in config.ALLOWED_TELEGRAM_IDS)


def _provider() -> str:
    provs = ai_client.available_providers()
    return provs[0]["id"] if provs else "claude"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "Salom! Men 'Komment Qiroli' avtomatlashtirish botiman.\n\n"
        "Instagram havolasini menga (yoki men admin bo'lgan kanalga) tashlang — "
        "men har akkauntga uning xususiyatiga mos ALOHIDA komment yozaman va like bosaman, "
        "holatni shu yerga yozib boraman."
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    accs = instagram_client.list_accounts()
    if not accs:
        await update.message.reply_text("Hech qanday akkaunt ulanmagan.")
        return
    alive = sum(1 for a in accs if (a.get("health") or {}).get("alive") is True)
    dead = sum(1 for a in accs if (a.get("health") or {}).get("alive") is False)
    lines = [f"📊 Akkauntlar: {len(accs)} · 🟢 {alive} tirik · 🔴 {dead} o'lik\n"]
    for a in accs:
        h = (a.get("health") or {}).get("alive")
        ic = "🟢" if h is True else "🔴" if h is False else "⚪"
        lines.append(f"{ic} @{a['username']} · {a.get('personality', '')} · {a['daily_count']}/{a['daily_limit']}")
    await update.message.reply_text("\n".join(lines[:60]))


def _enqueue_via_app(url: str, source: str) -> dict:
    """Havolani web-app orqali GLOBAL NAVBATga qo'shadi (manba bilan). Sinxron (executor'da)."""
    r = requests.post(
        f"{_INTERNAL_URL}/api/hook/run",
        headers={"X-Webhook-Token": config.WEBHOOK_TOKEN},
        json={"url": url, "source": source},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def _channel_allowed(post) -> bool:
    srcs = config.TELEGRAM_SOURCE_CHANNELS
    if not srcs:
        return True  # ro'yxat bo'sh — har qanday admin kanal
    cid = str(post.chat.id)
    uname = post.chat.username or ""
    return cid in srcs or uname in srcs or ("@" + uname) in srcs


async def on_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    m = _IG_URL_RE.search(update.message.text or "")
    if not m:
        await update.message.reply_text("Instagram havolasini yuboring.")
        return
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, lambda: _enqueue_via_app(m.group(0), "DM"))
    except Exception as e:
        await update.message.reply_text(f"❌ Navbatga qo'shib bo'lmadi: {str(e)[:150]}")
        return
    q = res.get("queued", 0)
    last_at = res.get("last_at", 0)
    eta = datetime.datetime.fromtimestamp(last_at).strftime("%m-%d %H:%M") if last_at else "?"
    await update.message.reply_text(
        f"✅ {q} akkaunt navbatga qo'shildi. Oxirgisi ~{eta}.\n"
        f"Natijani LOG kanaldan kuzating."
    )


async def on_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    post = update.channel_post
    if not post:
        return
    text = post.text or post.caption or ""   # turli format: matn yoki caption
    if not text or not _channel_allowed(post):
        return
    m = _IG_URL_RE.search(text)
    if not m:
        return
    source = post.chat.title or str(post.chat.id)
    loop = asyncio.get_event_loop()
    try:
        # Manba kanalni iflos qilmaymiz — hisobot LOG kanalga (queue_mgr orqali) ketadi.
        await loop.run_in_executor(None, lambda: _enqueue_via_app(m.group(0), source))
    except Exception as e:
        logger.warning("enqueue xato (%s): %s", source, e)


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN yo'q — Telegram bot ishga tushmaydi.")
        return
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.TEXT, on_channel))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_dm))
    logger.info("Telegram bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
