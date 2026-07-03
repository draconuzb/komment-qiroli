"""Ko'p akkauntli Instagram boshqaruvi: sessionid orqali ulash, caption olish, komment joylash.

DIQQAT: instagrapi norasmiy kutubxona va Instagram qoidalariga ziddir. Bir nechta
akkauntdan bitta postga komment yozish "muvofiqlashtirilgan" faollik sifatida
aniqlanishi va akkauntlar bloklanishi mumkin. Himoyalar (har akkaunt uchun kunlik
limit, tasodifiy kechikish, alohida sessiya) xavfni kamaytiradi, lekin yo'qotmaydi.
O'z mas'uliyatingiz ostida ishlating.
"""
import concurrent.futures as _cf
import hashlib
import html as _html
import json
import os
import random
import re as _re
import secrets
import time
from datetime import date

import requests

from instagrapi import Client

try:
    from instagrapi.exceptions import LoginRequired, ClientLoginRequired
    _LOGIN_ERRORS = (LoginRequired, ClientLoginRequired)
except Exception:  # eski/yangi versiyalar uchun zaxira
    class LoginRequired(Exception):
        pass
    _LOGIN_ERRORS = (LoginRequired,)

try:
    from instagrapi.exceptions import TwoFactorRequired
except Exception:  # versiya farqlari uchun zaxira
    class TwoFactorRequired(Exception):
        pass

try:
    from instagrapi.exceptions import ChallengeRequired
except Exception:
    class ChallengeRequired(Exception):
        pass

import threading as _threading

import config
import settings

_SESSIONS_DIR = os.path.join(config.DATA_DIR, "sessions")
_ACCOUNTS_FILE = os.path.join(config.DATA_DIR, "accounts.json")
_COUNTER_FILE = os.path.join(config.DATA_DIR, "daily_counter.json")
_PROXIES_FILE = os.path.join(config.DATA_DIR, "proxies.json")
_PERSONAS_FILE = os.path.join(config.DATA_DIR, "personalities.json")
_HEALTH_FILE = os.path.join(config.DATA_DIR, "health.json")

_clients: dict[str, Client] = {}      # username -> tirik Client (kesh)
_last_ts: dict[str, float] = {}       # username -> oxirgi komment vaqti

# Har akkaunt uchun ALOHIDA qulf — bir akkauntni bir vaqtda faqat BITTA thread ishlatadi.
# instagrapi Client thread-safe emas: komment worker + keep-alive + parallel tekshiruv
# bir akkauntni birga ishlatsa "to'qnashadi" va soxta login_required (o'lik) beradi.
_account_locks: dict[str, "_threading.Lock"] = {}
_locks_guard = _threading.Lock()


def _account_lock(username: str):
    with _locks_guard:
        lk = _account_locks.get(username)
        if lk is None:
            lk = _threading.Lock()
            _account_locks[username] = lk
        return lk


class RateLimitError(Exception):
    """Kunlik limit yoki tezlik chegarasiga yetilganda."""


class NotLoggedInError(Exception):
    """Akkaunt ulanmagan yoki sessiya eskirgan."""


# ---------- Yordamchilar ----------

def _new_client() -> Client:
    cl = Client()
    cl.delay_range = [1, 2]  # instagrapi ichki so'rovlari orasida tasodifiy kechikish
    # Har bir HTTP so'rovga timeout — o'lik sessiya/sekin proxy 504 ga olib kelmasin.
    try:
        cl.request_timeout = 12
    except Exception:
        pass
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


# ---------- Akkaunt xususiyati (personality) ----------

def _load_personas() -> dict:
    if os.path.exists(_PERSONAS_FILE):
        try:
            with open(_PERSONAS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_personas(data: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_PERSONAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_personality(username: str) -> str:
    from prompts import DEFAULT_PERSONALITY, PERSONALITIES
    p = _load_personas().get(username, DEFAULT_PERSONALITY)
    return p if p in PERSONALITIES else DEFAULT_PERSONALITY


def set_personality(username: str, personality: str) -> None:
    from prompts import PERSONALITIES, DEFAULT_PERSONALITY
    if personality not in PERSONALITIES:
        personality = DEFAULT_PERSONALITY
    data = _load_personas()
    data[username] = personality
    _save_personas(data)


# ---------- Akkaunt sog'ligi (tirik/o'lik) ----------

def _load_health() -> dict:
    if os.path.exists(_HEALTH_FILE):
        try:
            with open(_HEALTH_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _set_health(username: str, alive: bool) -> None:
    data = _load_health()
    data[username] = {"alive": alive, "checked_at": int(time.time())}
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def get_health(username: str) -> dict:
    return _load_health().get(username, {"alive": None, "checked_at": 0})


def is_dead(username: str) -> bool:
    """Oxirgi tekshiruvda o'lik deb belgilanganmi (avto-runda o'tkazib yuborish uchun)."""
    return _load_health().get(username, {}).get("alive") is False


def mark_dead(username: str) -> None:
    """Akkauntni o'lik deb belgilaydi (amal login xatosi bilan tushganda)."""
    _set_health(username, False)


_AUTH_DEAD_HINTS = (
    "login_required", "logged out", "logged_out", "user_has_logged_out",
    "checkpoint", "challenge_required", "not logged", "bad_password", "csrf",
)


def check_account(username: str, relogin: bool = True) -> bool:
    """Sessiya tirikligini tekshiradi (TEZ, soxta 'o'lik'ka qarshi):
    - faqat HAQIQIY auth-xato (login_required/checkpoint...) da 'o'lik';
    - tarmoq/timeout xatosida 'o'lik' DEMAYDI (oldingi holat qoladi);
    - relogin=True bo'lsa, auth-xato bo'lganda sessionid bilan 1 marta qayta ulanadi.
    Bulk tekshiruv (bot tugmasi) relogin=False bilan chaqiradi — tez bo'lsin."""
    last_auth = False
    for attempt in range(2):
        try:
            do_relogin = relogin and attempt == 1
            _run_timeout(
                lambda: _with_session(username, lambda cl: cl.account_info(), relogin=do_relogin), 15)
            _set_health(username, True)
            return True
        except Exception as e:
            msg = (str(e) or e.__class__.__name__).lower()
            last_auth = any(h in msg for h in _AUTH_DEAD_HINTS)
            if not last_auth:
                break        # tarmoq/timeout — tez chiqamiz, o'lik demaymiz
            if not relogin:
                break        # bulk-check — 1 urinish yetarli (tez)
    if last_auth:
        _set_health(username, False)
        return False
    return _load_health().get(username, {}).get("alive") is True


def warmup(username: str) -> str:
    """Yengil 'inson kabi' faollik (feed/reels ko'rish) — sessiya uzoqroq yashashiga yordam.
    Best-effort: xatolar yutiladi. Akkaunt proxysi orqali o'tadi."""
    def _do(cl):
        steps = []
        for fn, name in (
            (lambda: cl.get_timeline_feed(), "feed"),
            (lambda: cl.get_reels_tray_feed() if hasattr(cl, "get_reels_tray_feed") else None, "reels"),
        ):
            try:
                fn()
                steps.append(name)
            except Exception:
                pass
            time.sleep(random.uniform(2, 5))
        return steps
    steps = _run_timeout(lambda: _with_session(username, _do, relogin=False), 35)
    _set_health(username, True)  # ishladi => tirik
    return ", ".join(steps) if steps else "—"


def _sess_name(s: str) -> str:
    """IPRoyal session nomi uchun faqat harf/raqam qoldiradi."""
    return "".join(c for c in s.lower() if c.isalnum())[:24] or "acc"


def build_auto_proxy(token: str) -> str:
    """config'dagi IPRoyal creds asosida UZ sticky proxy URL yasaydi.

    Parametrlar PAROLGA qo'shiladi (IPRoyal formati):
    http://USER:PASS_country-uz_session-<token>_lifetime-30m@host:port
    PROXY_AUTO o'chiq yoki creds bo'sh bo'lsa — bo'sh satr qaytaradi.
    """
    # Creds bo'lsa quradi (PROXY_AUTO shart emas — chunki har akkaunt uchun checkbox bilan
    # alohida tanlanadi; PROXY_AUTO faqat "berilmasa default" sifatida chaqiruvchida ishlatiladi).
    if not (config.PROXY_HOST and config.PROXY_USER and config.PROXY_PASS):
        return ""
    pw = (
        f"{config.PROXY_PASS}_country-{config.PROXY_COUNTRY}"
        f"_session-{_sess_name(token)}_lifetime-{config.PROXY_LIFETIME}"
    )
    port = f":{config.PROXY_PORT}" if config.PROXY_PORT else ""
    return f"http://{config.PROXY_USER}:{pw}@{config.PROXY_HOST}{port}"


def proxy_parts_for(username: str) -> dict:
    """Brauzer (FoxyProxy) sozlash uchun akkaunt IPRoyal proxysining qismlari.
    Bot ham AYNI shu sessiyani ishlatadi → brauzer va bot IP'si bir xil bo'ladi."""
    username = (username or "").strip().lstrip("@")
    if not username or not (config.PROXY_HOST and config.PROXY_USER and config.PROXY_PASS):
        return {}
    sess = _sess_name(username)
    pw = (f"{config.PROXY_PASS}_country-{config.PROXY_COUNTRY}"
          f"_session-{sess}_lifetime-{config.PROXY_LIFETIME}")
    port = str(config.PROXY_PORT or "")
    return {
        "host": config.PROXY_HOST, "port": port,
        "username": config.PROXY_USER, "password": pw, "session": sess,
        "url": f"http://{config.PROXY_USER}:{pw}@{config.PROXY_HOST}:{port}",
    }


def _use_local_pool() -> bool:
    """Avto-proxy local modem pool'dan olinishi kerakmi (config.PROXY_MODE bo'yicha)."""
    mode = getattr(config, "PROXY_MODE", "auto")
    if mode == "local":
        return True
    if mode == "iproyal":
        return False
    # "auto": modemlar sozlangan bo'lsa local.
    try:
        import modem_pool
        return modem_pool.has_modems()
    except Exception:
        return False


def auto_proxy_for(username: str) -> str:
    """Akkaunt uchun avtomatik proxy: local modem pool yoki IPRoyal (rejimga qarab)."""
    if _use_local_pool():
        try:
            import modem_pool
            return modem_pool.assign(username)  # sticky biriktiradi
        except Exception:
            return ""
    return build_auto_proxy(username)


def _bootstrap_proxy() -> str:
    """Username noma'lum bo'lganda (sessionid login) login uchun vaqtinchalik UZ proxy."""
    if _use_local_pool():
        try:
            import modem_pool
            return modem_pool.bootstrap_proxy()
        except Exception:
            return ""
    return ""  # IPRoyal'da chaqiruvchi build_auto_proxy(hash) ishlatadi


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

def add_account_by_sessionid(sessionid: str, proxy: str = "", use_proxy=None,
                             username_hint: str = "") -> str:
    """Brauzerdan olingan sessionid orqali yangi akkaunt qo'shadi. Username qaytaradi.

    use_proxy: True — auto proxy (modem/IPRoyal); False — proxysiz (mini-PC IP);
    None — config.PROXY_AUTO bo'yicha. proxy (matn) berilsa — o'sha ishlatiladi.
    username_hint: berilsa — proxy BOSHIDANoq shu akkaunt sessiyasi bilan (brauzerда
    ishlatilgan IP bilan bir xil) — cookie mosligi buzilmaydi (bootstrap IP ishlatilmaydi).
    """
    sessionid = sessionid.strip().strip('"')
    if not sessionid:
        raise ValueError("sessionid bo'sh")

    username_hint = (username_hint or "").strip().lstrip("@")
    proxy = (proxy or "").strip()
    manual = bool(proxy)
    want_auto = use_proxy if use_proxy is not None else bool(config.PROXY_AUTO)
    auto = (not manual) and want_auto
    if auto:
        if username_hint:
            # Username ma'lum — brauzerда ishlatilgan bilan AYNI proxy (bir xil IP).
            proxy = auto_proxy_for(username_hint)
        else:
            # Username noma'lum — vaqtinchalik UZ IP (keyin username bo'yicha almashtiriladi).
            proxy = _bootstrap_proxy() or build_auto_proxy(
                hashlib.md5(sessionid.encode()).hexdigest()[:12]
            )

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

    # MUHIM: proxyni ALMASHTIRMAYMIZ. Cookie allaqachon telefon IP'sida tug'ilgan;
    # agar bu yerda yana boshqa proxy IP'ga o'tsak, sessiya 2-3 IP'ni bosib o'tadi va
    # Instagram uni "shubhali" deb O'LDIRADI (double-hop). Shuning uchun validatsiya
    # qilingan AYNI proxy (yuqorida tanlangani) akkauntning doimiy IP'si bo'lib qoladi.

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
    _set_health(username, True)  # login_by_sessionid muvaffaqiyatli — darrov TIRIK belgilaymiz
    return username


# ---------- Plan B: login + parol bilan kirish (2FA bilan) ----------
#
# MUHIM: login HAM, undan keyingi hamma amal HAM faqat o'sha akkauntning UZ
# proxysi orqali o'tadi — hech qachon serverning (AWS) IP'sidan emas. Shu sabab
# proxy login boshlanishidan oldin o'rnatiladi va sessiyaga saqlanadi.
#
# 2FA kodi kiritilguncha o'sha tirik Client xotirada saqlanadi (token bilan).
_pending_logins: dict[str, dict] = {}  # token -> {cl, username, password, proxy}


def _finalize_login(cl: Client, username_hint: str, proxy: str) -> str:
    """Muvaffaqiyatli logindan keyin sessiyani saqlaydi va akkauntni ro'yxatga qo'shadi."""
    try:
        username = cl.account_info().username
    except Exception:
        username = getattr(cl, "username", "") or username_hint
    if not username:
        raise RuntimeError("Akkaunt nomini aniqlab bo'lmadi.")

    # sessionid'ni ham saqlaymiz — keyinchalik auto-reconnect (_with_session) uchun.
    try:
        sid = cl.sessionid
    except Exception:
        sid = ""

    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    cl.dump_settings(_session_path(username))
    if sid:
        _save_sessionid(username, sid)
    if proxy:
        proxies = _load_proxies()
        proxies[username] = proxy
        _save_proxies(proxies)

    accounts = _load_accounts()
    if username not in accounts:
        accounts.append(username)
        _save_accounts(accounts)

    _clients[username] = cl
    _set_health(username, True)  # muvaffaqiyatli login — darrov TIRIK
    return username


def start_login(username: str, password: str, proxy: str = "", use_proxy=None) -> dict:
    """Login+parol bilan kirishni boshlaydi.

    use_proxy: True — auto proxy; False — proxysiz (mini-PC IP); None — PROXY_AUTO bo'yicha.
    Qaytaradi:
      {"status": "ok", "username": ...}   — muvaffaqiyatli kirdi (2FA o'chiq)
      {"status": "2fa", "token": ...}     — 2FA kodi kerak (finish_login_2fa chaqiring)
    """
    username = (username or "").strip().lstrip("@")
    password = password or ""
    if not username or not password:
        raise ValueError("Username va parol kerak")

    proxy = (proxy or "").strip()
    want_auto = use_proxy if use_proxy is not None else bool(config.PROXY_AUTO)
    if not proxy and want_auto:
        # Avto proxy: local modem pool yoki IPRoyal (rejimga qarab).
        proxy = auto_proxy_for(username)

    cl = _new_client()
    if proxy:
        try:
            cl.set_proxy(proxy)
        except Exception as e:
            raise RuntimeError(f"Proxy noto'g'ri: {e}")

    try:
        cl.login(username, password)
    except TwoFactorRequired:
        token = secrets.token_urlsafe(16)
        _pending_logins[token] = {
            "cl": cl, "username": username, "password": password, "proxy": proxy,
        }
        return {"status": "2fa", "token": token}
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        if isinstance(e, ChallengeRequired) or "challenge" in msg.lower():
            # Instagram email/SMS tekshiruvini majburladi (yangi IP). Kod oqimini
            # ishlatmaymiz (ovora) — foydalanuvchini sessionid+proxy usuliga yo'naltiramiz.
            raise RuntimeError(
                "Instagram tasdiqlash (email/SMS) so'radi. Login+parol o'rniga "
                "sessionid (cookie) + proxy bilan qo'shing — login bo'lmaydi, kod so'ralmaydi."
            )
        raise RuntimeError(f"Kirib bo'lmadi: {e}")

    name = _finalize_login(cl, username, proxy)
    return {"status": "ok", "username": name}


def finish_login_2fa(token: str, code: str) -> str:
    """2FA (6 xonali) kodi bilan loginni yakunlaydi. Username qaytaradi."""
    pend = _pending_logins.get(token)
    if not pend:
        raise RuntimeError("Login sessiyasi topilmadi yoki eskirgan. Qaytadan urinib ko'ring.")
    code = (code or "").strip().replace(" ", "")
    if not code:
        raise ValueError("2FA kodi kerak")

    cl = pend["cl"]
    try:
        cl.login(pend["username"], pend["password"], verification_code=code)
    except Exception as e:
        raise RuntimeError(f"2FA kodi qabul qilinmadi: {e}")

    name = _finalize_login(cl, pend["username"], pend["proxy"])
    _pending_logins.pop(token, None)
    return name


def remove_account(username: str) -> None:
    _save_accounts([a for a in _load_accounts() if a != username])
    _clients.pop(username, None)
    _last_ts.pop(username, None)
    proxies = _load_proxies()
    if proxies.pop(username, None) is not None:
        _save_proxies(proxies)
    try:  # local modem pool'dan ham bo'shatamiz
        import modem_pool
        modem_pool.unassign(username)
    except Exception:
        pass
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
            "personality": get_personality(u),
            "health": get_health(u),
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


def _with_session(username: str, fn, relogin: bool = True):
    """Amalni bajaradi. LoginRequired bo'lsa — sessionid orqali BIR marta qayta
    kirishga urinadi; baribir bo'lmasa, sessiya haqiqatan eskirgan deb belgilaydi.

    relogin=False — qayta-login urinmaydi (TEZ). O'qish (public media) uchun ishlatiladi:
    login bo'roni 504 ga olib kelmasin."""
    with _account_lock(username):  # to'qnashuvni oldini oladi (bir akkaunt = bir thread)
        cl = _get_client(username)
        try:
            return fn(cl)
        except _LOGIN_ERRORS:
            if relogin:
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

_FB_UA = ("Mozilla/5.0 (compatible; facebookexternalhit/1.1; "
          "+http://www.facebook.com/externalhit_uatext.php)")


def _meta(prop: str, h: str) -> str:
    m = _re.search(rf'<meta property="og:{prop}" content="([^"]*)"', h)
    return _html.unescape(m.group(1)) if m else ""


def _fetch_via_page(url: str) -> tuple[str, str, str]:
    """Reel/post sahifasining OMMAVIY og: meta teglaridan o'qiydi — login/gql kerak emas,
    juda tez (~1-2s) va proxy GB ishlatmaydi (to'g'ridan-to'g'ri). Qaytaradi:
    (media_id, caption, thumb_url). media_id topilmasa bo'sh bo'lishi mumkin."""
    r = requests.get(url, headers={"User-Agent": _FB_UA}, timeout=15)
    r.raise_for_status()
    h = r.text
    thumb = _meta("image", h)
    title = _meta("title", h)        # 'USER on Instagram: "caption..."'
    desc = _meta("description", h)   # 'N likes, M comments - user on date: "caption..."'

    caption = ""
    for s in (title, desc):
        m = _re.search(r'on Instagram[:\-]\s*["“‘](.+)', s, _re.S)
        if m:
            caption = _re.sub(r'["”’\s.]+$', "", m.group(1).strip())
            break
    if not caption and ":" in desc:
        caption = desc.split(":", 1)[1].strip().strip('"“” ')

    mid = ""
    mm = _re.search(r'"media_id":"(\d+_\d+)"', h) or _re.search(r'"media_id":"(\d+)"', h)
    if mm:
        mid = mm.group(1)
    return mid, caption.strip(), thumb


def _fetch_with(cl: Client, url: str) -> tuple[str, str, str]:
    pk = cl.media_pk_from_url(url)  # shortcode'dan lokal hisoblanadi (tarmoqsiz)
    # Avval ommaviy GraphQL — login shart emas, tez (1 ta so'rov). Faqat u bo'lmasa
    # v1 (login kerak) ga o'tamiz — o'lik sessiyalarda v1 sekin va baribir yiqiladi.
    try:
        media = cl.media_info_gql(pk)
    except Exception:
        media = cl.media_info(pk)
    thumb = str(getattr(media, "thumbnail_url", "") or "")
    return cl.media_id(pk), (media.caption_text or "").strip(), thumb


_EXEC = _cf.ThreadPoolExecutor(max_workers=4)


def _run_timeout(fn, timeout: float):
    """fn ni alohida thread'da bajaradi va `timeout` sek ichida natija qaytmasa
    TimeoutError beradi (instagrapi ichki qayta urinishlari osib qo'ymasin)."""
    fut = _EXEC.submit(fn)
    return fut.result(timeout=timeout)  # vaqt o'tsa thread tashlab ketiladi


def fetch_media(url: str) -> tuple[str, str, str]:
    """URL (video yoki rasm post) -> (media_id, caption_matni, muqova_rasm_url).

    Public post o'qish uchun login shart emas (ommaviy GraphQL). TEZ bo'lishi uchun:
    qayta-login yo'q, faqat birinchi bir necha akkaunt, har biriga QATTIQ timeout va
    umumiy vaqt byudjeti — sekin/o'lik sessiyalar 504 ga olib kelmasin."""
    # 1) ENG TEZ: ommaviy sahifa og: meta (login/gql/proxy kerak emas, ~1-2s).
    try:
        mid, caption, thumb = _run_timeout(lambda: _fetch_via_page(url), 18)
        if caption or thumb:
            return mid, caption, thumb
    except Exception:
        pass  # zaxira yo'liga o'tamiz

    # 2) ZAXIRA: instagrapi gql (public) akkaunt proxysi orqali — sekinroq.
    accounts = _load_accounts()
    if not accounts:
        raise NotLoggedInError("Postni o'qib bo'lmadi (sahifa meta yo'q, akkaunt ham yo'q).")
    last_err: Exception | None = None
    deadline = time.time() + 70  # umumiy vaqt byudjeti (sek)
    # gql (public) instagrapi ichki qayta urinishlari bilan ~20s olishi mumkin, shuning
    # uchun per-akkaunt timeout undan yuqori. Odatda 1-akkaunt'dayoq muvaffaqiyat.
    for u in accounts[:3]:
        if time.time() > deadline:
            break
        try:
            return _run_timeout(
                lambda: _with_session(u, lambda cl: _fetch_with(cl, url), relogin=False), 28
            )
        except _cf.TimeoutError:
            last_err = NotLoggedInError(f"@{u}: postni o'qish juda sekin (timeout).")
        except Exception as e:
            last_err = e
    raise last_err or NotLoggedInError("Postni o'qib bo'lmadi (faol akkaunt yo'q).")


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
    try:
        _run_timeout(lambda: _with_session(username, lambda cl: cl.media_comment(media_id, text)), 22)
    except _cf.TimeoutError:
        raise NotLoggedInError(f"@{username}: javob bermadi (sessiya o'lik yoki sekin). Qaytadan ulang.")
    _last_ts[username] = time.time()
    _increment_daily(username)


# ---------- Like ----------

def like_media(media_id: str, username: str) -> None:
    """Bitta akkauntdan postga like bosadi (yengil amal, kichik kechikish bilan)."""
    time.sleep(random.uniform(2, 6))
    try:
        _run_timeout(lambda: _with_session(username, lambda cl: cl.media_like(media_id)), 18)
    except _cf.TimeoutError:
        raise NotLoggedInError(f"@{username}: javob bermadi (sessiya o'lik yoki sekin). Qaytadan ulang.")


# ---------- Ko'rish (view / seen) ----------

def view_media(media_id: str, username: str) -> None:
    """Media'ni 'ko'rildi' deb belgilaydi.

    Story uchun ishonchli (real view qo'shiladi); reel/video uchun best-effort
    (ommaviy view soni oshishiga kafolat yo'q).
    """
    time.sleep(random.uniform(2, 6))
    try:
        _run_timeout(lambda: _with_session(username, lambda cl: cl.media_seen([media_id])), 18)
    except _cf.TimeoutError:
        raise NotLoggedInError(f"@{username}: javob bermadi (sessiya o'lik yoki sekin).")


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
