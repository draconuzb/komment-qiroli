"""Ko'p akkauntli Instagram boshqaruvi: sessionid orqali ulash, caption olish, komment joylash.

DIQQAT: instagrapi norasmiy kutubxona va Instagram qoidalariga ziddir. Bir nechta
akkauntdan bitta postga komment yozish "muvofiqlashtirilgan" faollik sifatida
aniqlanishi va akkauntlar bloklanishi mumkin. Himoyalar (har akkaunt uchun kunlik
limit, tasodifiy kechikish, alohida sessiya) xavfni kamaytiradi, lekin yo'qotmaydi.
O'z mas'uliyatingiz ostida ishlating.
"""
import json
import os
import random
import time
from datetime import date

from instagrapi import Client

try:
    from instagrapi.exceptions import LoginRequired, ClientLoginRequired
    _LOGIN_ERRORS = (LoginRequired, ClientLoginRequired)
except Exception:  # eski/yangi versiyalar uchun zaxira
    class LoginRequired(Exception):
        pass
    _LOGIN_ERRORS = (LoginRequired,)

import config
import settings

_SESSIONS_DIR = "sessions"
_ACCOUNTS_FILE = "accounts.json"
_COUNTER_FILE = "daily_counter.json"

_clients: dict[str, Client] = {}      # username -> tirik Client (kesh)
_last_ts: dict[str, float] = {}       # username -> oxirgi komment vaqti


class RateLimitError(Exception):
    """Kunlik limit yoki tezlik chegarasiga yetilganda."""


class NotLoggedInError(Exception):
    """Akkaunt ulanmagan yoki sessiya eskirgan."""


# ---------- Yordamchilar ----------

def _new_client() -> Client:
    cl = Client()
    cl.delay_range = [1, 3]  # instagrapi ichki so'rovlari orasida tasodifiy kechikish
    return cl


def _session_path(username: str) -> str:
    return os.path.join(_SESSIONS_DIR, f"{username}.json")


def _sid_path(username: str) -> str:
    return os.path.join(_SESSIONS_DIR, f"{username}.sid")


def _save_sessionid(username: str, sessionid: str) -> None:
    try:
        with open(_sid_path(username), "w", encoding="utf-8") as f:
            f.write(sessionid)
    except Exception:
        pass


def _load_sessionid(username: str) -> str:
    try:
        with open(_sid_path(username), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _load_accounts() -> list[str]:
    if os.path.exists(_ACCOUNTS_FILE):
        try:
            with open(_ACCOUNTS_FILE, encoding="utf-8") as f:
                return json.load(f).get("accounts", [])
        except Exception:
            pass
    return []


def _save_accounts(usernames: list[str]) -> None:
    with open(_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"accounts": usernames}, f, ensure_ascii=False, indent=2)


# ---------- Akkauntlarni boshqarish ----------

def add_account_by_sessionid(sessionid: str) -> str:
    """Brauzerdan olingan sessionid orqali yangi akkaunt qo'shadi. Username qaytaradi."""
    sessionid = sessionid.strip().strip('"')
    if not sessionid:
        raise ValueError("sessionid bo'sh")

    cl = _new_client()
    if not cl.login_by_sessionid(sessionid):
        raise RuntimeError("sessionid bilan kirib bo'lmadi. Cookie eskirgan yoki noto'g'ri.")

    try:
        username = cl.account_info().username
    except Exception:
        username = getattr(cl, "username", "") or ""
    if not username:
        raise RuntimeError("Akkaunt nomini aniqlab bo'lmadi.")

    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    cl.dump_settings(_session_path(username))
    _save_sessionid(username, sessionid)  # auto-reconnect uchun saqlaymiz

    accounts = _load_accounts()
    if username not in accounts:
        accounts.append(username)
        _save_accounts(accounts)

    _clients[username] = cl
    return username


def remove_account(username: str) -> None:
    _save_accounts([a for a in _load_accounts() if a != username])
    _clients.pop(username, None)
    _last_ts.pop(username, None)
    for path in (_session_path(username), _sid_path(username)):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def list_accounts() -> list[dict]:
    """Ulangan akkauntlar + bugungi komment soni."""
    limit = settings.get("max_comments_per_day")
    return [
        {"username": u, "daily_count": get_daily_count(u), "daily_limit": limit}
        for u in _load_accounts()
    ]


# ---------- Client olish ----------

def _get_client(username: str) -> Client:
    """Sessiyani yuklaydi va keshlaydi. Proaktiv tekshirmaydi —
    haqiqiy eskirish faqat amal bajarilganda (LoginRequired) aniqlanadi."""
    if username in _clients:
        return _clients[username]
    path = _session_path(username)
    if not os.path.exists(path):
        raise NotLoggedInError(f"@{username} sessiyasi topilmadi. Qaytadan ulang.")
    cl = _new_client()
    try:
        cl.load_settings(path)
    except Exception:
        raise NotLoggedInError(f"@{username} sessiya fayli buzilgan. Qaytadan ulang.")
    _clients[username] = cl
    return cl


def _with_session(username: str, fn):
    """Amalni bajaradi. LoginRequired bo'lsa — sessionid orqali BIR marta qayta
    kirishga urinadi; baribir bo'lmasa, sessiya haqiqatan eskirgan deb belgilaydi."""
    cl = _get_client(username)
    try:
        return fn(cl)
    except _LOGIN_ERRORS:
        sid = _load_sessionid(username)
        if sid:
            try:
                cl.login_by_sessionid(sid)
                cl.dump_settings(_session_path(username))
                return fn(cl)  # qayta urinish
            except Exception:
                pass
        _clients.pop(username, None)
        raise NotLoggedInError(f"@{username} sessiyasi eskirgan. Qaytadan ulang.")


# ---------- Media (video yoki rasm) ----------

def _fetch_with(cl: Client, url: str) -> tuple[str, str]:
    pk = cl.media_pk_from_url(url)
    media = cl.media_info(pk)
    return cl.media_id(pk), (media.caption_text or "").strip()


def fetch_media(url: str) -> tuple[str, str]:
    """URL (video yoki rasm post) -> (media_id, caption_matni).

    Faol akkauntlarni navbatma-navbat sinaydi; LoginRequired bo'lsa auto-reconnect
    ishlaydi, boshqa xato bo'lsa keyingi akkauntga o'tadi."""
    accounts = _load_accounts()
    if not accounts:
        raise NotLoggedInError("Hech qanday Instagram akkaunt ulanmagan. Avval akkaunt qo'shing.")
    last_err: Exception | None = None
    for u in accounts:
        try:
            return _with_session(u, lambda cl: _fetch_with(cl, url))
        except Exception as e:
            last_err = e
    raise last_err or NotLoggedInError("Faol akkaunt yo'q.")


# ---------- Kunlik hisoblagich (har akkaunt uchun alohida) ----------

def _load_counter() -> dict:
    if os.path.exists(_COUNTER_FILE):
        try:
            with open(_COUNTER_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"date": "", "counts": {}}


def _save_counter(data: dict) -> None:
    with open(_COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def get_daily_count(username: str) -> int:
    today = date.today().isoformat()
    data = _load_counter()
    if data.get("date") != today:
        return 0
    return data.get("counts", {}).get(username, 0)


def _increment_daily(username: str) -> None:
    today = date.today().isoformat()
    data = _load_counter()
    if data.get("date") != today:
        data = {"date": today, "counts": {}}
    counts = data.setdefault("counts", {})
    counts[username] = counts.get(username, 0) + 1
    _save_counter(data)


# ---------- Komment joylash ----------

def post_comment(media_id: str, text: str, username: str) -> None:
    """Bitta akkauntdan komment joylaydi — rate-limit va tasodifiy kechikish bilan."""
    min_gap = settings.get("min_seconds_between_comments")
    daily_limit = settings.get("max_comments_per_day")
    delay_min = settings.get("random_delay_min")
    delay_max = settings.get("random_delay_max")

    # Tezlik chegarasi (shu akkaunt uchun)
    elapsed = time.time() - _last_ts.get(username, 0.0)
    if elapsed < min_gap:
        raise RateLimitError(f"@{username}: juda tez. Yana {int(min_gap - elapsed)}s kuting.")

    # Kunlik limit (shu akkaunt uchun)
    if get_daily_count(username) >= daily_limit:
        raise RateLimitError(f"@{username}: kunlik limit ({daily_limit}) tugadi.")

    time.sleep(random.uniform(delay_min, delay_max))
    _with_session(username, lambda cl: cl.media_comment(media_id, text))
    _last_ts[username] = time.time()
    _increment_daily(username)
