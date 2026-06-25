"""Runtime sozlamalari — paneldan o'zgartiriladi, settings.json'ga saqlanadi.

.env qiymatlari standart (default) sifatida ishlatiladi; settings.json ularni
ustidan yozadi. Shu tarzda foydalanuvchi API kalitlarini va limitlarni serverni
qayta ishga tushirmasdan panel orqali boshqaradi.
"""
import json
import os

import config

_FILE = os.path.join(config.DATA_DIR, "settings.json")

# Maxfiy maydonlar — frontendga real qiymat qaytarilmaydi, faqat "o'rnatilgan/yo'q".
_SECRET_KEYS = {"anthropic_api_key", "groq_api_key", "mistral_api_key", "panel_password"}

_DEFAULTS = {
    "anthropic_api_key": config.ANTHROPIC_API_KEY,
    "claude_model": config.CLAUDE_MODEL,
    "groq_api_key": config.GROQ_API_KEY,
    "groq_model": config.GROQ_MODEL,
    "mistral_api_key": config.MISTRAL_API_KEY,
    "mistral_model": config.MISTRAL_MODEL,
    "min_seconds_between_comments": config.MIN_SECONDS_BETWEEN_COMMENTS,
    "random_delay_min": config.RANDOM_DELAY_MIN,
    "random_delay_max": config.RANDOM_DELAY_MAX,
    "max_comments_per_day": config.MAX_COMMENTS_PER_DAY,
    "account_gap_min": config.ACCOUNT_GAP_MIN,
    "account_gap_max": config.ACCOUNT_GAP_MAX,
    "schedule_gap_min": config.SCHEDULE_GAP_MIN,
    "schedule_window": config.SCHEDULE_WINDOW,
    "panel_password": config.PANEL_PASSWORD,
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        data = dict(_DEFAULTS)
        if os.path.exists(_FILE):
            try:
                with open(_FILE, encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass
        _cache = data
    return _cache


def get(key: str):
    return _load().get(key, _DEFAULTS.get(key))


def _coerce(key: str, value):
    default = _DEFAULTS.get(key)
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return str(value)


def update(new: dict) -> dict:
    """Sozlamalarni yangilaydi. Maxfiy maydonlar bo'sh bo'lsa — o'zgartirilmaydi."""
    global _cache
    data = _load()
    for key, value in new.items():
        if key not in _DEFAULTS:
            continue
        if key in _SECRET_KEYS and (value is None or str(value).strip() == ""):
            continue  # bo'sh maxfiy maydon — eskisini saqlab qolamiz
        try:
            data[key] = _coerce(key, value)
        except (ValueError, TypeError):
            continue
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache = data
    return data


def public_view() -> dict:
    """Frontend uchun — maxfiy kalitlar maskalanadi (faqat o'rnatilgan/yo'qligi)."""
    data = _load()
    out: dict = {}
    for key, value in data.items():
        if key in _SECRET_KEYS:
            out[key + "_set"] = bool(value)
        else:
            out[key] = value
    return out
