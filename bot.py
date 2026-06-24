"""Telegram avtomatlashtirish:

- Kanalga (bot admin bo'lgan) yoki ruxsatli DM'ga Instagram havolasi tashlansa,
  bot HAR AKKAUNT uchun o'sha akkaunt XUSUSIYATIga + post matniga mos ALOHIDA
  komment yaratadi, joylaydi va (iloji bo'lsa) like bosadi.
- Holat (qaysi akkaunt joyladi / xato) o'sha kanalga/chatga yozib turiladi.

Bot admin bo'lishi shart (kanal postlarini o'qishi uchun). TELEGRAM_CHANNEL_ID
berilsa — faqat o'sha kanal; bo'sh bo'lsa — bot admin bo'lgan har qanday kanal.
"""
import asyncio
import logging
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


async def _run_auto(bot, chat_id: int, url: str, reply_to: int | None = None) -> None:
    """Bitta havola uchun barcha akkauntlardan avto komment + like; holat tahrirlanib boriladi."""
    loop = asyncio.get_event_loop()
    status = await bot.send_message(
        chat_id=chat_id, text="⏳ Avto-komment boshlandi...", reply_to_message_id=reply_to
    )
    sid = status.message_id

    async def upd(text: str):
        try:
            await bot.edit_message_text(text=text[:4000], chat_id=chat_id, message_id=sid)
        except Exception:
            pass

    try:
        media_id, caption, thumb = await loop.run_in_executor(None, instagram_client.fetch_media, url)
    except Exception as e:
        await upd(f"❌ Postni o'qib bo'lmadi: {str(e)[:150]}")
        return
    if not media_id:
        await upd("❌ media_id topilmadi — bu postga avtomatik joylab bo'lmaydi.")
        return

    accounts = [a["username"] for a in instagram_client.list_accounts()]
    if not accounts:
        await upd("❌ Hech qanday akkaunt ulanmagan.")
        return

    prov = _provider()
    img = None
    ok = fail = 0
    lines: list[str] = []

    for u in accounts:
        try:
            persona = instagram_client.get_personality(u)
            if caption:
                text = await loop.run_in_executor(None, ai_client.generate_one, caption, persona, prov)
            elif thumb:
                if img is None:
                    img = await loop.run_in_executor(
                        None, lambda: requests.get(thumb, timeout=15).content
                    )
                text = await loop.run_in_executor(None, ai_client.generate_one_from_image, img, persona)
            else:
                raise RuntimeError("post matni ham, rasm ham yo'q")

            await loop.run_in_executor(None, instagram_client.post_comment, media_id, text, u)
            history.add(media_id, persona, text, url, u)

            liked = ""
            try:
                await loop.run_in_executor(None, instagram_client.like_media, media_id, u)
                history.add(media_id, "like", "❤️ like", url, u)
                liked = " +❤️"
            except Exception:
                pass

            ok += 1
            lines.append(f"✅ @{u} ({persona}){liked}")
        except Exception as e:
            fail += 1
            lines.append(f"❌ @{u}: {str(e)[:45]}")

        await upd(f"⏳ {ok + fail}/{len(accounts)} ...\n" + "\n".join(lines[-12:]))

    await upd(f"✅ Tugadi: {ok} komment, {fail} xato\n\n" + "\n".join(lines[-25:]))


async def on_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    m = _IG_URL_RE.search(update.message.text or "")
    if not m:
        await update.message.reply_text("Instagram havolasini yuboring.")
        return
    await _run_auto(context.bot, update.effective_chat.id, m.group(0), reply_to=update.message.message_id)


async def on_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    post = update.channel_post
    if not post or not post.text:
        return
    want = (config.TELEGRAM_CHANNEL_ID or "").lstrip("@")
    if want:
        if str(post.chat.id) != want and (post.chat.username or "") != want:
            return
    m = _IG_URL_RE.search(post.text)
    if not m:
        return
    await _run_auto(context.bot, post.chat.id, m.group(0), reply_to=post.message_id)


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
