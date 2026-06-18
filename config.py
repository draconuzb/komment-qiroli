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

# Web-panel
# Bo'sh bo'lsa — parolsiz (faqat lokal sinov uchun). Ishlatishda albatta to'ldiring.
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
