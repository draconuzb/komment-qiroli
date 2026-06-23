"""Ko'p akkauntli Instagram boshqaruvi: sessionid orqali ulash, caption olish, komment joylash.

DIQQAT: instagrapi norasmiy kutubxona va Instagram qoidalariga ziddir. Bir nechta
akkauntdan bitta postga komment yozish "muvofiqlashtirilgan" faollik sifatida
aniqlanishi va akkauntlar bloklanishi mumkin. Himoyalar (har akkaunt uchun kunlik
limit, tasodifiy kechikish, alohida sessiya) xavfni kamaytiradi, lekin yo'qotmaydi.
O'z mas'uliyatingiz ostida ishlating.
"""
import hashlib
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

_SESSIONS_DIR = os.path.join(config.DATA_DIR, "sessions")
_ACCOUNTS_FILE = os.path.join(config.DATA_DIR, "accounts.json")
_COUNTER_FILE = os.path.join(config.DATA_DIR, "daily_counter.json")
_PROXIES_FILE = os.path.join(config.DATA_DIR, "proxies.json")

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


# ---------- Proxy boshqaruvi (har akkaunt uchun alohida) ----------

def _load_proxies() -> dict:
    if os.path.exists(_PROXIES_FILE):
        try:
            with open(_PROXIES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_proxies(proxies: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_PROXIES_FILE, "w", encoding="utf-8") as f:
        json.dump(proxies, f, ensure_ascii=False, indent=2)


def get_proxy(username: str) -> str:
    return _load_proxies().get(username, "")


def _sess_name(s: str) -> str:
    """IPRoyal session nomi uchun faqat harf/raqam qoldiradi."""
    return "".join(c for c in s.lower() if c.isalnum())[:24] or "acc"


def build_auto_proxy(token: str) -> str:
    """config'dagi IPRoyal creds asosida UZ sticky proxy URL yasaydi.

    Parametrlar PAROLGA qo'shiladi (IPRoyal formati):
    http://USER:PASS_country-uz_session-<token>_lifetime-30m@host:port
    PROXY_AUTO o'chiq yoki creds bo'sh bo'lsa — bo'sh satr qaytaradi.
    """
    if not (config.PROXY_AUTO and config.PROXY_HOST and config.PROXY_USER and config.PROXY_PASS):
        return ""
    pw = (
        f"{config.PROXY_PASS}_country-{config.PROXY_COUNTRY}"
        f"_session-{_sess_name(token)}_lifetime-{config.PROXY_LIFETIME}"
    )
    port = f":{config.PROXY_PORT}" if config.PROXY_PORT else ""
    return f"http://{config.PROXY_USER}:{pw}@{config.PROXY_HOST}{port}"


def proxy_display(proxy: str) -> str:
    """Login/parolsiz ko'rsatish uchun (scheme://host:port)."""
    if not proxy:
        return ""
    try:
        from urllib.parse import urlparse
        p = urlparse(proxy)
        if p.hostname:
            return f"{p.scheme}://{p.hostname}:{p.port}" if p.port else f"{p.scheme}://{p.hostname}"
    except Exception:
        pass
    return proxy


def set_proxy(username: str, proxy: str) -> None:
    """Akkaunt uchun proxy o'rnatadi yoki bo'sh bo'lsa o'chiradi. Keshni tozalaydi."""
    proxy = (proxy or "").strip()
    proxies = _load_proxies()
    if proxy:
        proxies[username] = proxy
    else:
        proxies.pop(username, None)
    _save_proxies(proxies)
    _clients.pop(username, None)  # keyingi safar yangi proxy bilan yuklanadi


def _apply_proxy(cl: Client, username: str) -> None:
    proxy = get_proxy(username)
    if proxy:
        try:
            cl.set_proxy(proxy)
        except Exception:
            pass


def test_proxy(username: str) -> str:
    """Proxy orqali akkauntni tekshiradi (account_info chaqiradi)."""
    _clients.pop(username, None)  # joriy proxy bilan yangidan
    cl = _get_client(username)
    info = cl.account_info()
    return info.username


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

def add_account_by_sessionid(sessionid: str, proxy: str = "") -> str:
    """Brauzerdan olingan sessionid orqali yangi akkaunt qo'shadi. Username qaytaradi.

    proxy berilsa, login ham shu proxy orqali amalga oshiriladi (IP mosligi uchun muhim).
    """
    sessionid = sessionid.strip().strip('"')
    if not sessionid:
        raise ValueError("sessionid bo'sh")

    proxy = (proxy or "").strip()
    auto = not proxy
    if auto:
        # Proxy berilmagan — avtomatik UZ IP (login uchun sessionid'dan barqaror token).
        proxy = build_auto_proxy(hashlib.md5(sessionid.encode()).hexdigest()[:12])

    cl = _new_client()
    if proxy:
        try:
            cl.set_proxy(proxy)
        except Exception as e:
            raise RuntimeError(f"Proxy noto'g'ri: {e}")
    if not cl.login_by_sessionid(sessionid):
        raise RuntimeError("sessionid bilan kirib bo'lmadi. Cookie eskirgan yoki noto'g'ri.")

    try:
        username = cl.account_info().username
    except Exception:
        username = getattr(cl, "username", "") or ""
    if not username:
        raise RuntimeError("Akkaunt nomini aniqlab bo'lmadi.")

    # Avto rejimda — username bo'yicha barqaror UZ sticky-IP (har safar ~o'sha IP).
    if auto:
        stable = build_auto_proxy(username)
        if stable:
            proxy = stable
            try:
                cl.set_proxy(proxy)
            except Exception:
                pass

    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    cl.dump_settings(_session_path(username))
    _save_sessionid(username, sessionid)  # auto-reconnect uchun saqlaymiz
    if proxy:
        proxies = _load_proxies()
        proxies[username] = proxy
        _save_proxies(proxies)

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
    proxies = _load_proxies()
    if proxies.pop(username, None) is not None:
        _save_proxies(proxies)
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
        {
            "username": u,
            "daily_count": get_daily_count(u),
            "daily_limit": limit,
            "proxy": proxy_display(get_proxy(u)),
        }
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
    _apply_proxy(cl, username)
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

def _fetch_with(cl: Client, url: str) -> tuple[str, str, str]:
    pk = cl.media_pk_from_url(url)
    media = cl.media_info(pk)
    thumb = str(getattr(media, "thumbnail_url", "") or "")
    return cl.media_id(pk), (media.caption_text or "").strip(), thumb


def fetch_media(url: str) -> tuple[str, str, str]:
    """URL (video yoki rasm post) -> (media_id, caption_matni, muqova_rasm_url).

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


# ---------- Like ----------

def like_media(media_id: str, username: str) -> None:
    """Bitta akkauntdan postga like bosadi (yengil amal, kichik kechikish bilan)."""
    time.sleep(random.uniform(2, 6))
    _with_session(username, lambda cl: cl.media_like(media_id))


# ---------- Ko'rish (view / seen) ----------

def view_media(media_id: str, username: str) -> None:
    """Media'ni 'ko'rildi' deb belgilaydi.

    Story uchun ishonchli (real view qo'shiladi); reel/video uchun best-effort
    (ommaviy view soni oshishiga kafolat yo'q).
    """
    time.sleep(random.uniform(2, 6))
    _with_session(username, lambda cl: cl.media_seen([media_id]))


# ---------- Repost (yuklab olib qayta joylash) ----------

def _fetch_repost_with(cl: Client, url: str) -> dict:
    pk = cl.media_pk_from_url(url)
    info = cl.media_info(pk)
    folder = os.path.join(config.DATA_DIR, "tmp")
    os.makedirs(folder, exist_ok=True)

    mt = info.media_type
    pt = getattr(info, "product_type", "") or ""
    if mt == 1:
        path = cl.photo_download(pk, folder)
        kind = "photo"
    elif mt == 2 and pt == "clips":
        path = cl.clip_download(pk, folder)
        kind = "clip"
    elif mt == 2:
        path = cl.video_download(pk, folder)
        kind = "video"
    else:
        raise RuntimeError("Bu post turi (albom/karusel) hozircha repost qilinmaydi.")

    return {
        "path": str(path),
        "kind": kind,
        "caption": (info.caption_text or "").strip(),
        "original_user": getattr(info.user, "username", ""),
    }


def fetch_repost_source(url: str) -> dict:
    """Postni bir marta yuklab oladi (barcha akkauntlar uchun qayta ishlatiladi).

    Faol akkauntlarni navbatma-navbat sinaydi (fetch_media kabi): LoginRequired
    bo'lsa auto-reconnect ishlaydi, boshqa xato bo'lsa keyingi akkauntga o'tadi.

    Qaytaradi: {path, kind, caption, original_user}
    """
    accounts = _load_accounts()
    if not accounts:
        raise NotLoggedInError("Hech qanday Instagram akkaunt ulanmagan. Avval akkaunt qo'shing.")
    last_err: Exception | None = None
    for u in accounts:
        try:
            return _with_session(u, lambda cl: _fetch_repost_with(cl, url))
        except Exception as e:
            last_err = e
    raise last_err or NotLoggedInError("Faol akkaunt yo'q.")


def repost_to_account(src: dict, username: str, caption: str) -> None:
    """Yuklab olingan media'ni bitta akkauntga joylaydi — rate-limit bilan (og'ir amal)."""
    min_gap = settings.get("min_seconds_between_comments")
    daily_limit = settings.get("max_comments_per_day")
    delay_min = settings.get("random_delay_min")
    delay_max = settings.get("random_delay_max")

    elapsed = time.time() - _last_ts.get(username, 0.0)
    if elapsed < min_gap:
        raise RateLimitError(f"@{username}: juda tez. Yana {int(min_gap - elapsed)}s kuting.")
    if get_daily_count(username) >= daily_limit:
        raise RateLimitError(f"@{username}: kunlik limit ({daily_limit}) tugadi.")

    path = src["path"]
    kind = src["kind"]

    def _upload(cl):
        if kind == "photo":
            return cl.photo_upload(path, caption)
        if kind == "clip":
            return cl.clip_upload(path, caption)
        return cl.video_upload(path, caption)

    time.sleep(random.uniform(delay_min, delay_max))
    _with_session(username, _upload)
    _last_ts[username] = time.time()
    _increment_daily(username)


def story_to_account(src: dict, username: str) -> None:
    """Yuklab olingan media'ni bitta akkauntning Story'siga joylaydi (24 soatlik)."""
    min_gap = settings.get("min_seconds_between_comments")
    daily_limit = settings.get("max_comments_per_day")
    delay_min = settings.get("random_delay_min")
    delay_max = settings.get("random_delay_max")

    elapsed = time.time() - _last_ts.get(username, 0.0)
    if elapsed < min_gap:
        raise RateLimitError(f"@{username}: juda tez. Yana {int(min_gap - elapsed)}s kuting.")
    if get_daily_count(username) >= daily_limit:
        raise RateLimitError(f"@{username}: kunlik limit ({daily_limit}) tugadi.")

    path = src["path"]
    is_photo = src["kind"] == "photo"

    def _upload(cl):
        if is_photo:
            return cl.photo_upload_to_story(path)
        return cl.video_upload_to_story(path)  # clip/video — story video sifatida

    time.sleep(random.uniform(delay_min, delay_max))
    _with_session(username, _upload)
    _last_ts[username] = time.time()
    _increment_daily(username)


def cleanup_repost_source(src: dict) -> None:
    try:
        if src and os.path.exists(src.get("path", "")):
            os.remove(src["path"])
    except Exception:
        pass
