"""Telegram bot — Komment Qiroli boshqaruvi (professional tugmali interfeys).

- Manba kanalga (bot admin) IG havola tushsa → global navbatga qo'shadi, log kanalga hisobot.
- Ruxsatli DM'da havola → navbatga.
- /start — tugmali menyu: Akkauntlar · Navbat · Kanallar · Tozalash · Yordam.
"""
import asyncio
import datetime
import io
import json
import logging
import os
import re

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
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


def _add_account_via_app(username: str, sessionid: str) -> str:
    r = requests.post(
        f"{_INTERNAL_URL}/api/hook/add-account",
        headers={"X-Webhook-Token": config.WEBHOOK_TOKEN},
        json={"username": username, "sessionid": sessionid, "use_proxy": True},
        timeout=120,
    )
    if not r.ok:
        try:
            detail = r.json().get("detail") or r.text[:200]
        except ValueError:
            detail = r.text[:200]
        raise RuntimeError(detail)
    return r.json().get("username", username)


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
    "➕ Akkaunt qo'shish (proxy bilan, o'lmaydigan):\n"
    "1) /foxyproxy user1 user2 ... — FoxyProxy import faylini olasiz (bir marta import).\n"
    "2) 🦊 → akkaunt nomini tanlab yoqing → o'sha akkaunt bilan IG'ga kiring.\n"
    "3) sessionid'ni oling → /add <username> <sessionid>\n"
    "(yoki bitta akkaunt uchun: /proxy <username>)\n\n"
    "Kommentlar oyna ichida tasodifiy, ≥3 daqiqa oraliq bilan joylanadi."
)


# ---------- Rangli tugma helperlari (Bot API 9.4: style = primary/success/danger) ----------

def _ibtn(text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=callback_data,
                                api_kwargs=({"style": style} if style else None))


def _kbtn(text: str, style: str | None = None) -> KeyboardButton:
    return KeyboardButton(text, api_kwargs=({"style": style} if style else None))


# Doimiy (pastdagi) tugmalar matni — routing uchun
B_ACCOUNTS = "📊 Akkauntlar"
B_QUEUE = "📋 Navbat"
B_ADD = "➕ Akkaunt qo'shish"
B_ACCEL = "⚡ Hoziroq jo'natish"
B_SOURCES = "📡 Kanallar"
B_HELP = "ℹ️ Yordam"
B_CANCEL = "❌ Bekor qilish"


def _kb() -> ReplyKeyboardMarkup:
    """Doimiy rangli klaviatura — slash komanda kerak emas."""
    return ReplyKeyboardMarkup(
        [[_kbtn(B_ACCOUNTS, "primary"), _kbtn(B_QUEUE, "primary")],
         [_kbtn(B_ADD, "success"), _kbtn(B_ACCEL, "success")],
         [_kbtn(B_SOURCES), _kbtn(B_HELP)]],
        resize_keyboard=True, is_persistent=True,
    )


def _kb_cancel() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[_kbtn(B_CANCEL, "danger")]],
                               resize_keyboard=True, is_persistent=True)


def _yesno(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _ibtn("✅ Ha", f"menu:{action}", "success"),
        _ibtn("❌ Yo'q", "menu:dismiss", "danger"),
    ]])


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
    context.user_data.pop("add_state", None)
    await update.message.reply_text(_WELCOME, reply_markup=_kb())


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(_fmt_status(), reply_markup=_kb())


async def queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    kb = InlineKeyboardMarkup([[_ibtn("🧹 Navbatni tozalash", "menu:clear", "danger")]])
    await update.message.reply_text(_fmt_queue(), reply_markup=kb)


async def proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/proxy <username> — brauzer (FoxyProxy) uchun proxy sozlamalari."""
    if not _authorized(update):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Foydalanish:\n/proxy <username>\nMasalan: /proxy abbosqosimov11")
        return
    parts = instagram_client.proxy_parts_for(args[0])
    if not parts:
        await update.message.reply_text("Proxy sozlanmagan yoki username noto'g'ri.")
        return
    u = args[0].lstrip("@")
    await update.message.reply_text(
        f"🔑 Brauzer proxy — @{u}\n\n"
        f"Host:     {parts['host']}\n"
        f"Port:     {parts['port']}\n"
        f"Username: {parts['username']}\n"
        f"Password: {parts['password']}\n\n"
        f"Type: HTTP. Shu proxyni brauzer (FoxyProxy)ga qo'ying, yoqing, "
        f"o'sha brauzerda @{u} bilan Instagram'ga kiring, sessionid'ni oling, keyin:\n"
        f"/add {u} <sessionid>"
    )


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add <username> <sessionid> — akkauntni AYNI proxy bilan qo'shadi."""
    if not _authorized(update):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Foydalanish:\n/add <username> <sessionid>\n(avval /proxy bilan brauzerni sozlang)")
        return
    username = args[0].lstrip("@")
    sessionid = args[1].strip()
    await update.message.reply_text(f"⏳ @{username} qo'shilyapti (proxy orqali)...")
    loop = asyncio.get_event_loop()
    try:
        name = await loop.run_in_executor(None, lambda: _add_account_via_app(username, sessionid))
    except Exception as e:
        await update.message.reply_text(f"❌ Qo'shib bo'lmadi: {str(e)[:250]}")
        return
    await update.message.reply_text(f"✅ @{name} qo'shildi — barqaror UZ proxy IP'da. Endi o'lmasligi kerak.")


_FOXY_COLORS = ["#E74C3C", "#3498DB", "#2ECC71", "#9B59B6", "#E67E22",
                "#1ABC9C", "#F39C12", "#E84393", "#16A085", "#2980B9"]


def _foxyproxy_file(usernames: list[str]) -> tuple[bytes, int]:
    """FoxyProxy import faylini (settings JSON) yasaydi — har akkaunt nomi+rangi bilan."""
    data = []
    for i, u in enumerate(usernames):
        p = instagram_client.proxy_parts_for(u)
        if not p:
            continue
        data.append({
            "active": True, "title": u, "type": "http",
            "hostname": p["host"], "port": str(p["port"]),
            "username": p["username"], "password": p["password"],
            "cc": "", "city": "", "color": _FOXY_COLORS[i % len(_FOXY_COLORS)],
            "pac": "", "pacString": "", "proxyDNS": True,
            "include": [], "exclude": [], "tabProxy": [],
        })
    obj = {
        "mode": "disable", "sync": False, "autoBackup": False, "passthrough": "",
        "theme": "", "container": {},
        "commands": {"setProxy": "", "setTabProxy": "", "includeHost": "", "excludeHost": ""},
        "data": data,
    }
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"), len(data)


async def foxyproxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/foxyproxy [user1 user2 ...] — FoxyProxy import faylini yasab beradi."""
    if not _authorized(update):
        return
    if context.args:
        usernames = [a.lstrip("@") for a in context.args]
    else:
        usernames = [a["username"] for a in instagram_client.list_accounts()]
    if not usernames:
        await update.message.reply_text(
            "Foydalanish:\n/foxyproxy user1 user2 ...\n"
            "(yoki avval akkaunt qo'shsangiz — hammasi uchun yasayman)")
        return
    content, n = _foxyproxy_file(usernames)
    if not n:
        await update.message.reply_text("Proxy sozlanmagan.")
        return
    buf = io.BytesIO(content)
    await update.message.reply_document(
        document=InputFile(buf, filename="foxyproxy-komment-qiroli.json"),
        caption=(f"📥 {n} akkaunt proxysi tayyor.\n\n"
                 "FoxyProxy → Options → Import Settings → shu faylni tanlang.\n"
                 "Keyin 🦊 → kerakli akkaunt nomini tanlab yoqing."),
    )


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline tugma (tasdiqlash dialoglari) uchun."""
    q = update.callback_query
    await q.answer()
    if not _authorized(update):
        await q.edit_message_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    data = q.data.split(":", 1)[1]
    try:
        if data == "dismiss":
            await q.edit_message_text("Bekor qilindi.")
        elif data == "clear":
            await q.edit_message_text("🧹 Navbatdagi (hali joylanmagan) kommentlarni bekor qilamizmi?",
                                      reply_markup=_yesno("clear_yes"))
        elif data == "clear_yes":
            n = await asyncio.get_event_loop().run_in_executor(None, _clear_queue)
            await q.edit_message_text(f"🧹 {n} ta navbatdan o'chirildi." if n >= 0 else "❌ Tozalab bo'lmadi.")
        elif data == "accel_yes":
            n = await asyncio.get_event_loop().run_in_executor(None, _accelerate_queue)
            await q.edit_message_text(f"⚡ {n} ta komment 2-4 daqiqa oraliq bilan jo'natiladi." if n >= 0 else "❌ Bo'lmadi.")
    except Exception:
        pass  # "message not modified" kabi xatolarni yutamiz


# ---------- Tugmali akkaunt qo'shish oqimi ----------
_ADD_USER = "await_username"
_ADD_SID = "await_sessionid"


async def _add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["add_state"] = _ADD_USER
    await update.message.reply_text(
        "➕ Akkaunt qo'shish\n\nAvval akkaunt username'ini yuboring (masalan: abbosqosimov11):",
        reply_markup=_kb_cancel(),
    )


async def _add_username(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    username = text.lstrip("@").strip()
    if not username or " " in username:
        await update.message.reply_text("Username noto'g'ri. Qaytadan yuboring:", reply_markup=_kb_cancel())
        return
    context.user_data["add_user"] = username
    context.user_data["add_state"] = _ADD_SID
    parts = instagram_client.proxy_parts_for(username)
    if parts:
        await update.message.reply_text(
            f"🔑 @{username} uchun brauzer (FoxyProxy) proxysi:\n\n"
            f"Host:     {parts['host']}\n"
            f"Port:     {parts['port']}\n"
            f"Username: {parts['username']}\n"
            f"Password: {parts['password']}\n\n"
            f"1) Shu proxyni FoxyProxy'ga qo'ying va YOQING.\n"
            f"2) whatismyipaddress.com — IP UZ ekanini tekshiring.\n"
            f"3) O'sha brauzerда @{username} bilan Instagram'ga kiring.\n"
            f"4) F12 → Application → Cookies → sessionid'ni nusxalab, shu yerga yuboring:",
            reply_markup=_kb_cancel(),
        )
    else:
        await update.message.reply_text("sessionid'ni yuboring:", reply_markup=_kb_cancel())


async def _add_sessionid(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    username = context.user_data.get("add_user", "")
    context.user_data.pop("add_state", None)
    context.user_data.pop("add_user", None)
    await update.message.reply_text(f"⏳ @{username} qo'shilyapti (proxy orqali)...", reply_markup=_kb())
    loop = asyncio.get_event_loop()
    try:
        name = await loop.run_in_executor(None, lambda: _add_account_via_app(username, text.strip()))
    except Exception as e:
        await update.message.reply_text(f"❌ Qo'shib bo'lmadi: {str(e)[:250]}", reply_markup=_kb())
        return
    await update.message.reply_text(f"✅ @{name} qo'shildi — barqaror UZ proxy IP'da. Endi o'lmasligi kerak.",
                                    reply_markup=_kb())


async def _do_enqueue_dm(update: Update, url: str) -> None:
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, lambda: _enqueue_via_app(url, "DM"))
    except Exception as e:
        await update.message.reply_text(f"❌ Navbatga qo'shib bo'lmadi: {str(e)[:150]}", reply_markup=_kb())
        return
    q = res.get("queued", 0)
    last_at = res.get("last_at", 0)
    eta = datetime.datetime.fromtimestamp(last_at).strftime("%m-%d %H:%M") if last_at else "?"
    await update.message.reply_text(
        f"✅ {q} akkaunt navbatga qo'shildi. Oxirgisi ~{eta}.\nNatijani LOG kanaldan kuzating.",
        reply_markup=_kb())


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Barcha DM matnlari — tugmalar, akkaunt qo'shish oqimi, IG havola."""
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, sizda ruxsat yo'q.")
        return
    text = (update.message.text or "").strip()

    if text == B_CANCEL:
        context.user_data.pop("add_state", None)
        context.user_data.pop("add_user", None)
        await update.message.reply_text("Bekor qilindi.", reply_markup=_kb())
        return

    state = context.user_data.get("add_state")
    if state == _ADD_USER:
        await _add_username(update, context, text)
        return
    if state == _ADD_SID:
        await _add_sessionid(update, context, text)
        return

    if text == B_ACCOUNTS:
        await update.message.reply_text(_fmt_status(), reply_markup=_kb())
    elif text == B_QUEUE:
        kb = InlineKeyboardMarkup([[_ibtn("🧹 Navbatni tozalash", "menu:clear", "danger")]])
        await update.message.reply_text(_fmt_queue(), reply_markup=kb)
    elif text == B_SOURCES:
        await update.message.reply_text(_fmt_sources(), reply_markup=_kb())
    elif text == B_HELP:
        await update.message.reply_text(_HELP, reply_markup=_kb())
    elif text == B_ADD:
        await _add_start(update, context)
    elif text == B_ACCEL:
        await update.message.reply_text(
            "⚡ Kutayotgan kommentlarni HOZIROQ (2-4 daqiqa oraliq) jo'natamizmi?",
            reply_markup=_yesno("accel_yes"))
    else:
        m = _IG_URL_RE.search(text)
        if m:
            await _do_enqueue_dm(update, m.group(0))
        else:
            await update.message.reply_text("Tugmalardan foydalaning yoki IG havola yuboring 👇",
                                            reply_markup=_kb())


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
    app.add_handler(CommandHandler("proxy", proxy_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("foxyproxy", foxyproxy_cmd))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^menu:"))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_private_text))
    logger.info("Telegram bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
