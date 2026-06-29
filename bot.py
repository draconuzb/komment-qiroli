"""Telegram bot — Komment Qiroli boshqaruvi (professional tugmali interfeys).

- Manba kanalga (bot admin) IG havola tushsa → global navbatga qo'shadi, log kanalga hisobot.
- Ruxsatli DM'da havola → navbatga.
- /start — tugmali menyu: Akkauntlar · Navbat · Kanallar · Tozalash · Yordam.
"""
import asyncio
import datetime
import logging
import os
import re

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import instagram_client
import queue_mgr

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

_IG_URL_RE = re.compile(r"https?://(www\.)?instagram\.com/\S+")
_INTERNAL_URL = f"http://127.0.0.1:{os.getenv('PORT', '8000')}"


def _authorized(update: Update) -> bool:
    if not config.ALLOWED_TELEGRAM_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in config.ALLOWED_TELEGRAM_IDS)


# ---------- Navbatga qo'shish (web-app HTTP orqali) ----------

def _enqueue_via_app(url: str, source: str) -> dict:
    r = requests.post(
        f"{_INTERNAL_URL}/api/hook/run",
        headers={"X-Webhook-Token": config.WEBHOOK_TOKEN},
        json={"url": url, "source": source},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def _clear_queue() -> int:
    try:
        r = requests.post(
            f"{_INTERNAL_URL}/api/hook/clear",
            headers={"X-Webhook-Token": config.WEBHOOK_TOKEN}, timeout=30,
        )
        r.raise_for_status()
        return r.json().get("cleared", 0)
    except Exception:
        return -1


def _accelerate_queue() -> int:
    try:
        r = requests.post(
            f"{_INTERNAL_URL}/api/hook/accelerate",
            headers={"X-Webhook-Token": config.WEBHOOK_TOKEN}, timeout=30,
        )
        r.raise_for_status()
        return r.json().get("accelerated", 0)
    except Exception:
        return -1


def _channel_allowed(post) -> bool:
    srcs = config.TELEGRAM_SOURCE_CHANNELS
    if not srcs:
        return True
    cid = str(post.chat.id)
    uname = post.chat.username or ""
    return cid in srcs or uname in srcs or ("@" + uname) in srcs


# ---------- Interfeys (menyu + matnlar) ----------

_WELCOME = (
    "👑 Komment Qiroli — boshqaruv paneli\n\n"
    "Manba kanalga Instagram havolasi tushsa, men uni global navbatga qo'shaman.\n"
    "Har akkaunt o'z uslubida, vaqtga taqsimlab (≥3 daqiqa oraliq) komment + like "
    "qoldiradi — hech qachon 2 tasi birga ketmaydi (bloklanmaslik uchun).\n"
    "Natijalarni log kanalda ko'rasiz.\n\n"
    "Quyidagi tugmalardan foydalaning 👇"
)

_HELP = (
    "ℹ️ Yordam\n\n"
    "• Manba kanalga IG reel/post havolasini tashlang — men avtomatik navbatga qo'shaman.\n"
    "• Menga shaxsiy (DM) havola yuborsangiz ham bo'ladi.\n"
    "• 📊 Akkauntlar — holat (tirik/o'lik, kunlik hisob).\n"
    "• 📋 Navbat — kutayotgan kommentlar, keyingisi qachon.\n"
    "• 📡 Kanallar — manba va log kanallar.\n"
    "• 🧹 Tozalash — navbatdagi (hali joylanmagan) kommentlarni bekor qiladi.\n\n"
    "Kommentlar oyna ichida tasodifiy, ≥3 daqiqa oraliq bilan joylanadi."
)


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Akkauntlar", callback_data="menu:status"),
         InlineKeyboardButton("📋 Navbat", callback_data="menu:queue")],
        [InlineKeyboardButton("⚡ Hoziroq jo'natish", callback_data="menu:accel"),
         InlineKeyboardButton("🧹 Navbatni tozalash", callback_data="menu:clear")],
        [InlineKeyboardButton("📡 Kanallar", callback_data="menu:sources")],
        [InlineKeyboardButton("🔄 Yangilash", callback_data="menu:home"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="menu:help")],
    ])


def _back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="menu:home")]])


def _fmt_status() -> str:
    accs = instagram_client.list_accounts()
    if not accs:
        return "📭 Hech qanday akkaunt ulanmagan.\nPanel orqali akkaunt qo'shing."
    alive = sum(1 for a in accs if (a.get("health") or {}).get("alive") is True)
    dead = sum(1 for a in accs if (a.get("health") or {}).get("alive") is False)
    lines = [f"📊 Akkauntlar: {len(accs)}   🟢 {alive}   🔴 {dead}\n"]
    for a in accs[:40]:
        h = (a.get("health") or {}).get("alive")
        ic = "🟢" if h is True else "🔴" if h is False else "⚪"
        lines.append(f"{ic} @{a['username']} · {a.get('personality', '')} · {a['daily_count']}/{a['daily_limit']}")
    if len(accs) > 40:
        lines.append(f"... va yana {len(accs) - 40} ta")
    return "\n".join(lines)


def _fmt_queue() -> str:
    q = queue_mgr.snapshot()
    if q["pending"] == 0:
        extra = f" · ❌ {q['failed']}" if q["failed"] else ""
        return f"📋 Navbat bo'sh.\n✅ Joylangan: {q['done']}{extra}"
    mins = round((q["next_in"] or 0) / 60)
    last = datetime.datetime.fromtimestamp(q["last_at"]).strftime("%m-%d %H:%M") if q["last_at"] else "?"
    extra = f" · ❌ {q['failed']}" if q["failed"] else ""
    lines = [
        f"📋 Navbat: {q['pending']} kutyapti",
        f"⏭ Keyingisi: ~{mins} daqiqadan keyin",
        f"🏁 Oxirgisi: {last}",
        f"✅ Joylangan: {q['done']}{extra}\n",
    ]
    for it in q["items"][:15]:
        m = round(it["in_sec"] / 60)
        lines.append(f"• @{it['username']} — ~{m} daq")
    if q["pending"] > 15:
        lines.append(f"... va yana {q['pending'] - 15} ta")
    return "\n".join(lines)


def _fmt_sources() -> str:
    srcs = sorted(config.TELEGRAM_SOURCE_CHANNELS)
    log = config.TELEGRAM_LOG_CHANNEL or "— (o'rnatilmagan)"
    lines = [f"📡 Manba kanallar: {len(srcs)}"]
    lines += [f"• {s}" for s in srcs] or ["• (yo'q)"]
    lines.append(f"\n📝 Log kanal: {log}")
    lines.append("\n⚠️ Botni bu kanallarga ADMIN qilishingiz shart.")
    return "\n".join(lines)


# ---------- Handlerlar ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    await update.message.reply_text(_WELCOME, reply_markup=_main_menu())


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(_fmt_status(), reply_markup=_back_menu())


async def queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(_fmt_queue(), reply_markup=_back_menu())


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not _authorized(update):
        await q.edit_message_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    data = q.data.split(":", 1)[1]
    try:
        if data == "home":
            await q.edit_message_text(_WELCOME, reply_markup=_main_menu())
        elif data == "status":
            await q.edit_message_text(_fmt_status(), reply_markup=_back_menu())
        elif data == "queue":
            await q.edit_message_text(_fmt_queue(), reply_markup=_back_menu())
        elif data == "sources":
            await q.edit_message_text(_fmt_sources(), reply_markup=_back_menu())
        elif data == "help":
            await q.edit_message_text(_HELP, reply_markup=_back_menu())
        elif data == "clear":
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ha, tozala", callback_data="menu:clear_yes"),
                InlineKeyboardButton("❌ Yo'q", callback_data="menu:home"),
            ]])
            await q.edit_message_text("🧹 Navbatdagi (hali joylanmagan) kommentlarni bekor qilamizmi?", reply_markup=kb)
        elif data == "clear_yes":
            n = await asyncio.get_event_loop().run_in_executor(None, _clear_queue)
            msg = f"🧹 {n} ta navbatdan o'chirildi." if n >= 0 else "❌ Tozalab bo'lmadi."
            await q.edit_message_text(msg, reply_markup=_back_menu())
        elif data == "accel":
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ha, jo'nat", callback_data="menu:accel_yes"),
                InlineKeyboardButton("❌ Yo'q", callback_data="menu:home"),
            ]])
            await q.edit_message_text("⚡ Kutayotgan kommentlarni HOZIROQ (2-4 daqiqa oraliq) jo'natamizmi?", reply_markup=kb)
        elif data == "accel_yes":
            n = await asyncio.get_event_loop().run_in_executor(None, _accelerate_queue)
            msg = f"⚡ {n} ta komment 2-4 daqiqa oraliq bilan jo'natiladi." if n >= 0 else "❌ Bo'lmadi."
            await q.edit_message_text(msg, reply_markup=_back_menu())
    except Exception:
        pass  # "message not modified" kabi xatolarni yutamiz


async def on_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    m = _IG_URL_RE.search(update.message.text or "")
    if not m:
        await update.message.reply_text("Instagram havolasini yuboring yoki /start bosing.")
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
        f"✅ {q} akkaunt navbatga qo'shildi. Oxirgisi ~{eta}.\nNatijani LOG kanaldan kuzating.",
        reply_markup=_back_menu(),
    )


def _extract_ig_url(post) -> str:
    """Post matni, caption VA inline tugma (button) URL/matnlaridan IG havolani topadi."""
    parts = [post.text or "", post.caption or ""]
    rm = getattr(post, "reply_markup", None)
    if rm and getattr(rm, "inline_keyboard", None):
        for row in rm.inline_keyboard:
            for btn in row:
                if getattr(btn, "url", None):
                    parts.append(btn.url)
                if getattr(btn, "text", None):
                    parts.append(btn.text)
    m = _IG_URL_RE.search("\n".join(parts))
    return m.group(0) if m else ""


async def on_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    post = update.channel_post
    if not post or not _channel_allowed(post):
        return
    url = _extract_ig_url(post)   # matn/caption/tugma — barchasidan qidiradi
    if not url:
        return
    source = post.chat.title or str(post.chat.id)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _enqueue_via_app(url, source))
    except Exception as e:
        logger.warning("enqueue xato (%s): %s", source, e)


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN yo'q — Telegram bot ishga tushmaydi.")
        return
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("queue", queue_cmd))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^menu:"))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_dm))
    logger.info("Telegram bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
