"""Telegram bot: video URL -> Claude 3 variant -> tugma bilan tanlash -> Instagram'ga joylash."""
import asyncio
import logging
import re

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
import claude_client
import instagram_client
from instagram_client import RateLimitError

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

_IG_URL_RE = re.compile(r"https?://(www\.)?instagram\.com/\S+")

_STYLE_LABELS = {
    "yumor": "😄 Yumor",
    "aqlli": "🧠 Aqlli",
    "bahsli": "🔥 Bahsli",
}


def _authorized(update: Update) -> bool:
    if not config.ALLOWED_TELEGRAM_IDS:
        return True  # ro'yxat bo'sh bo'lsa — hammaga ochiq (tavsiya etilmaydi)
    user = update.effective_user
    return bool(user and user.id in config.ALLOWED_TELEGRAM_IDS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    await update.message.reply_text(
        "Salom! Men 'Komment qiroli' botiman.\n\n"
        "1. Menga Instagram video (Reel) havolasini yuboring.\n"
        "2. Men videoni o'qib, 3 xil olovli komment tayyorlayman.\n"
        "3. Yoqqanini tugma orqali tanlang — men uni Instagramga joylayman.\n\n"
        "Yoki havola o'rniga shunchaki video mavzusini matn qilib yuborsangiz ham bo'ladi "
        "(lekin u holda komment qo'lda joylanadi)."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return

    text = (update.message.text or "").strip()
    url_match = _IG_URL_RE.search(text)

    media_id = None
    description = text

    if url_match:
        url = url_match.group(0)
        await update.message.reply_text("Videoni o'qiyapman... ⏳")
        try:
            media_id, caption = await asyncio.to_thread(
                instagram_client.fetch_caption, url
            )
        except Exception as e:
            logger.exception("Instagram caption olishda xato")
            await update.message.reply_text(f"Videoni o'qib bo'lmadi: {e}")
            return

        if not caption:
            await update.message.reply_text(
                "Bu videoda matn (caption) yo'q ekan. Iltimos, video nima haqida ekanini "
                "qisqacha matn qilib yuboring (men keyin shu media'ga joylayman)."
            )
            context.user_data["pending_media_id"] = media_id
            return
        description = caption
    elif context.user_data.get("pending_media_id"):
        # Oldin caption'siz video yuborilgan edi — bu xabar uning tavsifi
        media_id = context.user_data.pop("pending_media_id")
        description = text

    await update.message.reply_text("Kommentlar tayyorlanmoqda... 🤖")
    try:
        comments = await asyncio.to_thread(
            claude_client.generate_comments, description
        )
    except Exception as e:
        logger.exception("Claude generatsiyasida xato")
        await update.message.reply_text(f"Komment yaratib bo'lmadi: {e}")
        return

    context.user_data["comments"] = comments
    context.user_data["media_id"] = media_id

    preview = "\n\n".join(
        f"{_STYLE_LABELS[k]}:\n{comments[k]}" for k in ("yumor", "aqlli", "bahsli")
    )

    if media_id:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(_STYLE_LABELS[k], callback_data=f"post:{k}")]
             for k in ("yumor", "aqlli", "bahsli")]
        )
        await update.message.reply_text(
            preview + "\n\nQaysi birini joylaymiz?", reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            preview
            + "\n\n(Havola yuborilmagani uchun avtomatik joylab bo'lmaydi — yuqoridagi "
            "matnni nusxalab, qo'lda joylang yoki Reel havolasini yuboring.)"
        )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not _authorized(update):
        await query.edit_message_text("Kechirasiz, sizda ruxsat yo'q.")
        return

    _, style = query.data.split(":", 1)
    comments = context.user_data.get("comments")
    media_id = context.user_data.get("media_id")

    if not comments or not media_id:
        await query.edit_message_text(
            "Sessiya eskirgan. Iltimos, video havolasini qaytadan yuboring."
        )
        return

    text = comments[style]
    await query.edit_message_text(f"Joylanmoqda ({_STYLE_LABELS[style]})... ⏳")

    try:
        await asyncio.to_thread(instagram_client.post_comment, media_id, text)
    except RateLimitError as e:
        await query.edit_message_text(f"⚠️ {e}")
        return
    except Exception as e:
        logger.exception("Komment joylashda xato")
        await query.edit_message_text(f"Joylab bo'lmadi: {e}")
        return

    await query.edit_message_text(f"✅ Joylandi:\n\n{text}")


def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^post:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot ishga tushdi.")
    app.run_polling()


if __name__ == "__main__":
    main()
