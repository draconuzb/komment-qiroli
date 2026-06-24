"""Joylangan kommentlar tarixini oddiy JSON faylda saqlaydi."""
import json
import os
from datetime import datetime

import config

_HISTORY_FILE = os.path.join(config.DATA_DIR, "history.json")
_MAX_ITEMS = 200


def _load() -> list[dict]:
    if os.path.exists(_HISTORY_FILE):
        try:
            with open(_HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def add(media_id: str, style: str, text: str, url: str = "", username: str = "") -> None:
    items = _load()
    items.insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "media_id": media_id,
        "style": style,
        "text": text,
        "url": url,
        "username": username,
    })
    del items[_MAX_ITEMS:]
    with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def recent(limit: int = 30) -> list[dict]:
    return _load()[:limit]


def already_commented(media_id: str, username: str) -> bool:
    """Shu akkaunt shu media'ga avval komment yozganmi (like/view emas)."""
    for it in _load():
        if it.get("media_id") == media_id and it.get("username") == username \
                and it.get("style") not in ("like", "view"):
            return True
    return False


def already_liked(media_id: str, username: str) -> bool:
    for it in _load():
        if it.get("media_id") == media_id and it.get("username") == username \
                and it.get("style") == "like":
            return True
    return False
