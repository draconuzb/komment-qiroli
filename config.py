"""Konfiguratsiya — barcha sozlamalar .env faylidan o'qiladi."""
import os
from dotenv import load_dotenv

load_dotenv()


# Runtime ma'lumotlar papkasi (sessiyalar, sozlamalar, tarix). Docker'da volume bilan
# saqlab qolish uchun shu papkaga yoziladi. Lokalda standart — joriy papka.
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"'{name}' .env faylida o'rnatilmagan. .env.example faylidan nusxa oling."
        )
    return value


# Telegram (faqat Telegram bot uchun kerak; web-panel uchun shart emas)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_TELEGRAM_IDS = {
    int(x.strip())
    for x in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",")
    if x.strip()
}
# Avtomatlashtirish kanali (bot admin bo'lishi shart). @username yoki -100... ID.
# Bo'sh bo'lsa — bot admin bo'lgan har qanday kanaldagi havolaga ishlaydi.
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

# AI provayderlar (kamida bittasi to'ldirilgan bo'lsin)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

# Instagram
# Login/parol ixtiyoriy — paneldan 'sessionid' kiritish usuli tavsiya etiladi.
IG_USERNAME = os.getenv("IG_USERNAME", "")
IG_PASSWORD = os.getenv("IG_PASSWORD", "")
IG_SESSION_FILE = os.getenv("IG_SESSION_FILE", "ig_session.json")

# Rate-limit / xavfsizlik
MIN_SECONDS_BETWEEN_COMMENTS = int(os.getenv("MIN_SECONDS_BETWEEN_COMMENTS", "90"))
RANDOM_DELAY_MIN = float(os.getenv("RANDOM_DELAY_MIN", "4"))
RANDOM_DELAY_MAX = float(os.getenv("RANDOM_DELAY_MAX", "12"))
MAX_COMMENTS_PER_DAY = int(os.getenv("MAX_COMMENTS_PER_DAY", "30"))
# Akkauntlararo kechikish (sekund) — komment/avto-run da har akkaunt orasida tasodifiy
# minutli tanaffus (bloklanmaslik uchun: hammasi birdan emas, birma-bir yoziladi).
ACCOUNT_GAP_MIN = int(os.getenv("ACCOUNT_GAP_MIN", "120"))   # 2 daqiqa
ACCOUNT_GAP_MAX = int(os.getenv("ACCOUNT_GAP_MAX", "300"))   # 5 daqiqa
# Global navbat (queue_mgr): kommentlar vaqtga taqsimlanadi (ban himoyasi).
# gap_min — istalgan 2 komment orasidagi MINIMAL oraliq (butun tizim bo'ylab).
# window — akkauntlar shu OYNA ichiga tasodifiy joylashtiriladi.
SCHEDULE_GAP_MIN = int(os.getenv("SCHEDULE_GAP_MIN", "180"))      # 3 daqiqa
SCHEDULE_WINDOW = int(os.getenv("SCHEDULE_WINDOW", "172800"))     # 2 kun

# Web-panel
# Bo'sh bo'lsa — parolsiz (faqat lokal sinov uchun). Ishlatishda albatta to'ldiring.
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

# Proxy rejimi (avtomatik proxy qaysi manbadan):
#   "local"   — o'z 4G modem pool'ingiz (modem_pool.py / modems.json). BEPUL, UZ mobil IP.
#   "iproyal" — IPRoyal residential (pastdagi PROXY_* creds).
#   "auto"    — modemlar sozlangan bo'lsa "local", aks holda "iproyal".
PROXY_MODE = os.getenv("PROXY_MODE", "auto")

# Avtomatik proxy (IPRoyal residential) — yangi akkaunt qo'shilganda har biriga
# avtomatik alohida UZ sticky-IP biriktiriladi (proxy maydonini bo'sh qoldirsa).
PROXY_AUTO = os.getenv("PROXY_AUTO", "") == "1"
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_PORT = os.getenv("PROXY_PORT", "")
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASS = os.getenv("PROXY_PASS", "")
PROXY_COUNTRY = os.getenv("PROXY_COUNTRY", "uz")
PROXY_LIFETIME = os.getenv("PROXY_LIFETIME", "30m")

# Webhook (kiruvchi trigger) — tashqi skript/cron botni avtomatik boshqarishi uchun.
# Bo'sh bo'lsa webhook o'chiq. So'rovda X-Webhook-Token header yoki ?token= bilan keladi.
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
