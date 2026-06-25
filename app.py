"""Web-panel (FastAPI): Komment Qiroli — ko'p akkaunt + ko'p AI provayder.

Ishga tushirish:
    python app.py
yoki:
    uvicorn app:app --host 127.0.0.1 --port 8000
"""
import re
import secrets
import threading
import time
from pathlib import Path

import requests
from fastapi import Cookie, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import settings
import ai_client
import instagram_client
import history
import queue_mgr
from instagram_client import RateLimitError, NotLoggedInError

app = FastAPI(title="Komment Qiroli")


@app.on_event("startup")
def _start_queue_worker():
    # Global komment navbati ishlovchisi — FAQAT shu (web) jarayonida ishlaydi.
    queue_mgr.start_worker()

# Repost/Story vaqtincha o'chirilgan (proxy GB tejash uchun). Video yuklash ~20-30 MB,
# komment/like esa ~1 MB. Yetarli proxy GB ulangach True qiling.
REPOST_STORY_ENABLED = False
_REPOST_STORY_OFF_MSG = (
    "Repost va Story vaqtincha o'chirilgan (proxy interneti/GB tejash uchun). "
    "Ular video yuklab oladi va har biri ~20-30 MB GB sarflaydi. Hozircha "
    "komment va like ishlating (ular juda kam trafik). Yetarli proxy GB "
    "ulangach qayta yoqiladi."
)

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

_IG_URL_RE = re.compile(r"https?://(www\.)?instagram\.com/\S+")
_SESSIONS: set[str] = set()


# ---------- Auth ----------

def _check_auth(session: str | None) -> None:
    if not settings.get("panel_password"):
        return
    if not session or session not in _SESSIONS:
        raise HTTPException(status_code=401, detail="Avtorizatsiya talab qilinadi")


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody, response: Response):
    panel_pw = settings.get("panel_password")
    if panel_pw and body.password != panel_pw:
        raise HTTPException(status_code=401, detail="Parol noto'g'ri")
    token = secrets.token_urlsafe(32)
    _SESSIONS.add(token)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, session: str | None = Cookie(default=None)):
    if session:
        _SESSIONS.discard(session)
    response.delete_cookie("session")
    return {"ok": True}


# ---------- Status ----------

@app.get("/api/status")
def status(session: str | None = Cookie(default=None)):
    providers = ai_client.available_providers()
    panel_pw = settings.get("panel_password")
    return {
        "auth_required": bool(panel_pw),
        "authed": (not panel_pw) or (session in _SESSIONS),
        "providers": providers,
        "default_provider": providers[0]["id"] if providers else None,
        "accounts": instagram_client.list_accounts(),
        "daily_limit": settings.get("max_comments_per_day"),
    }


# ---------- Sozlamalar ----------

@app.get("/api/settings")
def get_settings(session: str | None = Cookie(default=None)):
    _check_auth(session)
    return settings.public_view()


@app.post("/api/settings")
def save_settings(body: dict, session: str | None = Cookie(default=None)):
    _check_auth(session)
    settings.update(body)
    return {"ok": True, "settings": settings.public_view(), "providers": ai_client.available_providers()}


class TestBody(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""


@app.post("/api/settings/test")
def test_settings(body: TestBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    try:
        msg = ai_client.test_provider(body.provider, body.api_key, body.model)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "message": msg}


# ---------- Akkauntlar ----------

@app.get("/api/accounts")
def get_accounts(session: str | None = Cookie(default=None)):
    _check_auth(session)
    return {"accounts": instagram_client.list_accounts()}


class AddAccountBody(BaseModel):
    sessionid: str
    proxy: str = ""


@app.post("/api/accounts")
def add_account(body: AddAccountBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    try:
        username = instagram_client.add_account_by_sessionid(body.sessionid, body.proxy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "username": username, "accounts": instagram_client.list_accounts()}


class LoginAccountBody(BaseModel):
    username: str
    password: str
    proxy: str = ""


@app.post("/api/accounts/login")
def account_login(body: LoginAccountBody, session: str | None = Cookie(default=None)):
    """Plan B: login+parol bilan akkaunt qo'shish. Login akkaunt proxysi orqali o'tadi.

    Javob: {ok, status: "ok"|"2fa", username?|token?, accounts}
    2FA yoqiq bo'lsa status="2fa" + token qaytadi — /api/accounts/login/2fa ga yuboring.
    """
    _check_auth(session)
    try:
        res = instagram_client.start_login(body.username, body.password, body.proxy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **res, "accounts": instagram_client.list_accounts()}


class Login2FABody(BaseModel):
    token: str
    code: str


@app.post("/api/accounts/login/2fa")
def account_login_2fa(body: Login2FABody, session: str | None = Cookie(default=None)):
    """2FA kodi bilan loginni yakunlaydi."""
    _check_auth(session)
    try:
        username = instagram_client.finish_login_2fa(body.token, body.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "username": username, "accounts": instagram_client.list_accounts()}


@app.delete("/api/accounts/{username}")
def delete_account(username: str, session: str | None = Cookie(default=None)):
    _check_auth(session)
    instagram_client.remove_account(username)
    return {"ok": True, "accounts": instagram_client.list_accounts()}


class ProxyBody(BaseModel):
    proxy: str = ""


@app.post("/api/accounts/{username}/proxy")
def set_account_proxy(username: str, body: ProxyBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    instagram_client.set_proxy(username, body.proxy)
    return {"ok": True, "accounts": instagram_client.list_accounts()}


@app.post("/api/accounts/{username}/proxy/test")
def test_account_proxy(username: str, session: str | None = Cookie(default=None)):
    _check_auth(session)
    try:
        name = instagram_client.test_proxy(username)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "username": name}


# ---------- Akkaunt xususiyati (personality) ----------

@app.get("/api/personalities")
def personalities():
    from prompts import PERSONALITIES, DEFAULT_PERSONALITY
    return {"personalities": PERSONALITIES, "default": DEFAULT_PERSONALITY}


class PersonaBody(BaseModel):
    personality: str


@app.post("/api/accounts/{username}/personality")
def set_personality(username: str, body: PersonaBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    instagram_client.set_personality(username, body.personality)
    return {"ok": True, "accounts": instagram_client.list_accounts()}


# ---------- Sog'lik tekshiruvi + warm-up (fon job) ----------

class AccountsBody(BaseModel):
    usernames: list[str] = []   # bo'sh => barcha


@app.post("/api/accounts/check")
def accounts_check(body: AccountsBody, session: str | None = Cookie(default=None)):
    """Tanlangan (yoki barcha) akkaunt sessiyasi tirikligini tekshiradi — fon job."""
    _check_auth(session)
    accounts = body.usernames or [a["username"] for a in instagram_client.list_accounts()]
    if not accounts:
        raise HTTPException(status_code=400, detail="Akkaunt yo'q")

    def worker(u):
        if not instagram_client.check_account(u):
            raise RuntimeError("o'lik (sessiya)")

    jid = _start_job("Tekshiruv", accounts, worker)
    return {"job_id": jid, "total": len(accounts)}


@app.post("/api/accounts/warmup")
def accounts_warmup(body: AccountsBody, session: str | None = Cookie(default=None)):
    """Akkauntlarni 'isitadi' (yengil feed/reels ko'rish) — sessiya uzoq yashashiga yordam. Fon job."""
    _check_auth(session)
    accounts = body.usernames or [a["username"] for a in instagram_client.list_accounts()]
    if not accounts:
        raise HTTPException(status_code=400, detail="Akkaunt yo'q")

    def worker(u):
        instagram_client.warmup(u)

    jid = _start_job("Isitish", accounts, worker)
    return {"job_id": jid, "total": len(accounts)}


# ---------- Modem pool (o'z 4G modemlaringiz) ----------

import modem_pool


@app.get("/api/modems")
def get_modems(session: str | None = Cookie(default=None)):
    _check_auth(session)
    return {"modems": modem_pool.list_modems(), "proxy_host": modem_pool.PROXY_HOST}


class AddModemBody(BaseModel):
    ext_ip: str
    label: str = ""
    rotate_type: str = ""   # "huawei" | "adb" | ""
    rotate_url: str = ""    # huawei uchun (http://192.168.8.1)
    rotate_serial: str = ""  # adb uchun


@app.post("/api/modems")
def add_modem(body: AddModemBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    rotate = {}
    if body.rotate_type == "huawei" and body.rotate_url:
        rotate = {"type": "huawei", "url": body.rotate_url}
    elif body.rotate_type == "adb":
        rotate = {"type": "adb", "serial": body.rotate_serial}
    try:
        m = modem_pool.add_modem(body.ext_ip, rotate=rotate, label=body.label)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "modem": m, "modems": modem_pool.list_modems()}


@app.delete("/api/modems/{modem_id}")
def delete_modem(modem_id: str, session: str | None = Cookie(default=None)):
    _check_auth(session)
    modem_pool.remove_modem(modem_id)
    return {"ok": True, "modems": modem_pool.list_modems()}


@app.post("/api/modems/{modem_id}/rotate")
def rotate_modem(modem_id: str, session: str | None = Cookie(default=None)):
    _check_auth(session)
    try:
        modem_pool.rotate(modem_id)
        ip = modem_pool.current_ip(modem_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "ip": ip}


@app.post("/api/modems/{modem_id}/ip")
def modem_ip(modem_id: str, session: str | None = Cookie(default=None)):
    _check_auth(session)
    try:
        ip = modem_pool.current_ip(modem_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "ip": ip}


@app.post("/api/modems/detect")
def detect_modems(session: str | None = Cookie(default=None)):
    _check_auth(session)
    return {"candidates": modem_pool.detect_candidates()}


@app.post("/api/modems/config")
def modems_config(session: str | None = Cookie(default=None)):
    _check_auth(session)
    cfg = modem_pool.gen_3proxy_config()
    path = modem_pool.write_3proxy_config()
    return {"ok": True, "config": cfg, "path": path}


@app.post("/api/modems/assign-all")
def assign_all(session: str | None = Cookie(default=None)):
    """Barcha akkauntlarni modemlarga balanslab biriktiradi (mavjudlarni saqlaydi)."""
    _check_auth(session)
    if not modem_pool.has_modems():
        raise HTTPException(status_code=400, detail="Avval kamida bitta modem qo'shing")
    for a in instagram_client.list_accounts():
        u = a["username"]
        modem_pool.assign(u)
        instagram_client.set_proxy(u, modem_pool.proxy_for(u))
    return {"ok": True, "accounts": instagram_client.list_accounts(), "modems": modem_pool.list_modems()}


# ---------- Generatsiya ----------

class GenerateBody(BaseModel):
    text: str
    provider: str = "claude"


# Bir reel takror generate qilinsa, qayta Instagram'ga bormaslik uchun kesh (proxy GB tejash).
# url -> (media_id, caption, thumb_url, vaqt). TTL ichida qayta so'rov yubormaydi.
_MEDIA_CACHE: dict[str, tuple] = {}
_MEDIA_CACHE_TTL = 600  # 10 daqiqa


def _fetch_media_cached(url: str):
    hit = _MEDIA_CACHE.get(url)
    if hit and (time.time() - hit[3]) < _MEDIA_CACHE_TTL:
        return hit[0], hit[1], hit[2]
    media_id, caption, thumb = instagram_client.fetch_media(url)
    _MEDIA_CACHE[url] = (media_id, caption, thumb, time.time())
    return media_id, caption, thumb


def _download_image(url: str, max_bytes: int = 3_000_000) -> bytes:
    """Muqova rasmni TO'G'RIDAN-TO'G'RI (proxy'siz) yuklab oladi — CDN ochiq, 0 proxy GB.

    Hajmi cheklangan (himoyalar uchun)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    r = requests.get(url, headers=headers, timeout=20, stream=True)
    r.raise_for_status()
    data = r.content[:max_bytes]
    if not data:
        raise RuntimeError("Rasm bo'sh yuklandi")
    return data


def _enqueue_link(url: str, usernames: list[str] | None, like: bool = True, source: str = "") -> dict:
    """Havola uchun har akkauntni global navbatga (vaqtga taqsimlangan) qo'shadi.
    Komment post vaqtida (worker'da) yaratiladi — bu yerда faqat media_id olinadi."""
    accounts = usernames or [a["username"] for a in instagram_client.list_accounts()]
    if not accounts:
        raise HTTPException(status_code=400, detail="Hech qanday akkaunt ulanmagan")
    try:
        media_id, _caption, _thumb = _fetch_media_cached(url)
    except NotLoggedInError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Postni o'qib bo'lmadi: {e}")
    res = queue_mgr.enqueue(url, media_id, accounts, like=like, source=source)
    return res


@app.post("/api/generate")
def generate(body: GenerateBody, session: str | None = Cookie(default=None)):
    _check_auth(session)

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Matn yoki havola kiriting")

    media_id = None
    url = ""
    description = text

    url_match = _IG_URL_RE.search(text)
    if url_match:
        url = url_match.group(0)
        try:
            media_id, caption, thumb_url = _fetch_media_cached(url)
        except NotLoggedInError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Postni o'qib bo'lmadi: {e}")

        # Caption yo'q bo'lsa — muqova RASMI asosida (Claude vision) generatsiya.
        if not caption:
            if not thumb_url:
                raise HTTPException(
                    status_code=422,
                    detail="Bu postda matn ham, rasm ham topilmadi. Mavzuni alohida matn qilib kiriting.",
                )
            try:
                img = _download_image(thumb_url)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Muqova rasmini yuklab bo'lmadi: {e}")
            try:
                comments = ai_client.generate_comments_from_image(img)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Rasm asosida komment yaratib bo'lmadi: {e}")
            return {
                "has_media": True,
                "media_id": media_id,
                "url": url,
                "description": "(caption yo'q — muqova rasmi tahlil qilindi)",
                "source": "vision",
                "provider": "claude",
                "comments": comments,
            }

        description = caption

    try:
        comments = ai_client.generate_comments(description, body.provider)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Komment yaratib bo'lmadi: {e}")

    return {
        "has_media": media_id is not None,
        "media_id": media_id,
        "url": url,
        "description": description,
        "source": "text",
        "provider": body.provider,
        "comments": comments,
    }


# ---------- Webhook (kiruvchi trigger — tashqi skript/cron uchun) ----------

class HookBody(BaseModel):
    url: str
    action: str = "comment"      # "comment" | "like" | "both"
    accounts: list[str] = []      # bo'sh => barcha ulangan akkauntlar
    provider: str = ""            # bo'sh => birinchi mavjud AI
    style: str = "aqlli"          # yumor | aqlli | bahsli (AI komment uslubi)
    text: str = ""                # berilsa AI ishlatilmaydi, shu matn joylanadi
    source: str = ""              # qaysi manba kanaldan (log uchun)


def _check_webhook(token: str | None) -> None:
    if not config.WEBHOOK_TOKEN:
        raise HTTPException(status_code=503, detail="Webhook o'chiq (WEBHOOK_TOKEN .env'da yo'q)")
    if not token or token != config.WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Webhook token noto'g'ri")


@app.post("/api/hook/run")
def hook_run(
    body: HookBody,
    x_webhook_token: str | None = Header(default=None),
    token: str | None = None,
):
    """Kiruvchi webhook: havola + amal => bot avtomatik AI komment yaratib joylaydi.

    Auth: `X-Webhook-Token` header yoki `?token=` query (panel cookie kerak emas).
    Misol:
      curl -X POST 'http://HOST:8000/api/hook/run' \
        -H 'X-Webhook-Token: SIZNING_TOKEN' -H 'Content-Type: application/json' \
        -d '{"url":"https://instagram.com/reel/XXX/","action":"comment","style":"aqlli"}'
    """
    _check_webhook(x_webhook_token or token)
    if not body.url:
        raise HTTPException(status_code=400, detail="url kerak")
    try:
        res = _enqueue_link(body.url, body.accounts, like=True, source=(body.source or "webhook"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, **res}


# ---------- Joylash (tanlangan akkauntlardan) ----------

class PostBody(BaseModel):
    media_id: str
    style: str
    text: str
    url: str = ""
    usernames: list[str]


# Fon (background) job tizimi — like/comment ketma-ket + kechikishlar bilan bajariladi
# (ban himoyasi). Sinxron qilsak ko'p akkaunt + kechikish = 504. Shu sabab fonда ishlaydi,
# panel esa /api/job/{id} dan holatni so'rab turadi.
_JOBS: dict[str, dict] = {}
_JOBS_MAX = 50


import random as _random

# Login/sessiya bilan bog'liq xato belgilari — bunday akkaunt "o'lik" deb belgilanadi.
_DEAD_HINTS = ("login", "sessiya", "o'lik", "logged_out", "logged out", "challenge",
               "not found", "checkpoint", "401", "403", "unauthorized")


def _start_job(label: str, usernames: list[str], worker, gap_range: tuple | None = None) -> str:
    """Fon job. gap_range=(min,max) sekund berilsa — akkauntlar ORASIDA tasodifiy
    tanaffus qiladi (kommentlar birma-bir, minutlab oralab yoziladi → bloklanmaslik)."""
    jid = secrets.token_urlsafe(8)
    job = {"label": label, "total": len(usernames), "done": 0, "results": [], "finished": False, "next_in": 0}
    _JOBS[jid] = job
    if len(_JOBS) > _JOBS_MAX:
        for old in list(_JOBS)[:-_JOBS_MAX]:
            _JOBS.pop(old, None)

    def run():
        for idx, u in enumerate(usernames):
            try:
                worker(u)
                job["results"].append({"username": u, "ok": True})
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                job["results"].append({"username": u, "ok": False, "error": msg})
                # Login/sessiya xatosi bo'lsa — akkauntni o'lik deb belgilab, davom etamiz.
                if any(h in msg.lower() for h in _DEAD_HINTS):
                    try:
                        instagram_client.mark_dead(u)
                    except Exception:
                        pass
            job["done"] += 1
            # Akkauntlar orasida tanaffus (oxirgisidan keyin emas).
            if gap_range and idx < len(usernames) - 1:
                wait = _random.uniform(gap_range[0], gap_range[1])
                job["next_in"] = int(wait)
                end = time.time() + wait
                while time.time() < end and not job.get("stop"):
                    time.sleep(1)
                job["next_in"] = 0
        job["finished"] = True

    threading.Thread(target=run, daemon=True).start()
    return jid


@app.get("/api/job/{jid}")
def get_job(jid: str, session: str | None = Cookie(default=None)):
    _check_auth(session)
    job = _JOBS.get(jid)
    if not job:
        raise HTTPException(status_code=404, detail="Job topilmadi (eskirgan bo'lishi mumkin)")
    return {**job, "accounts": instagram_client.list_accounts()}


@app.post("/api/post")
def post(body: PostBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    if not body.media_id:
        raise HTTPException(status_code=400, detail="media_id yo'q — avtomatik joylab bo'lmaydi")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    def worker(u):
        instagram_client.post_comment(body.media_id, body.text, u)
        history.add(body.media_id, body.style, body.text, body.url, u)

    gap = (settings.get("account_gap_min"), settings.get("account_gap_max"))
    jid = _start_job("Komment", body.usernames, worker, gap_range=gap)
    return {"job_id": jid, "total": len(body.usernames)}


# ---------- AVTO: har akkaunt o'z xususiyatiga mos komment + like ----------

class RunBody(BaseModel):
    url: str
    usernames: list[str] = []   # bo'sh => barcha akkauntlar
    provider: str = ""
    like: bool = True


@app.post("/api/run")
def run(body: RunBody, session: str | None = Cookie(default=None)):
    """Link uchun: har akkaunt GLOBAL NAVBATga qo'shiladi — komment+like vaqtga
    taqsimlangan holda (oyna ichida, >=3 daq oraliq, bitta-bitta) joylanadi."""
    _check_auth(session)
    if not body.url:
        raise HTTPException(status_code=400, detail="Havola (url) kerak")
    res = _enqueue_link(body.url, body.usernames, like=body.like, source="panel")
    return {"ok": True, **res}


@app.get("/api/queue")
def get_queue(session: str | None = Cookie(default=None)):
    _check_auth(session)
    return queue_mgr.snapshot()


@app.post("/api/queue/clear")
def clear_queue(session: str | None = Cookie(default=None)):
    _check_auth(session)
    n = queue_mgr.clear_pending()
    return {"ok": True, "cleared": n, "queue": queue_mgr.snapshot()}


@app.post("/api/hook/clear")
def hook_clear(x_webhook_token: str | None = Header(default=None), token: str | None = None):
    """Token bilan navbatni tozalash (bot uchun)."""
    _check_webhook(x_webhook_token or token)
    n = queue_mgr.clear_pending()
    return {"ok": True, "cleared": n}


# ---------- Like ----------

class ActionBody(BaseModel):
    media_id: str
    url: str = ""
    usernames: list[str]


@app.post("/api/like")
def like(body: ActionBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    if not body.media_id:
        raise HTTPException(status_code=400, detail="media_id yo'q")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    def worker(u):
        instagram_client.like_media(body.media_id, u)
        history.add(body.media_id, "like", "❤️ like", body.url, u)

    jid = _start_job("Like", body.usernames, worker)
    return {"job_id": jid, "total": len(body.usernames)}


# ---------- Ko'rish (view) ----------

@app.post("/api/view")
def view(body: ActionBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    if not body.media_id:
        raise HTTPException(status_code=400, detail="media_id yo'q")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    def worker(u):
        instagram_client.view_media(body.media_id, u)
        history.add(body.media_id, "view", "👁 view", body.url, u)

    jid = _start_job("Ko'rish", body.usernames, worker)
    return {"job_id": jid, "total": len(body.usernames)}


# ---------- Repost ----------

class RepostBody(BaseModel):
    url: str
    usernames: list[str]
    caption: str = ""


@app.post("/api/repost")
def repost(body: RepostBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    if not REPOST_STORY_ENABLED:
        raise HTTPException(status_code=403, detail=_REPOST_STORY_OFF_MSG)
    if not body.url:
        raise HTTPException(status_code=400, detail="Repost uchun post havolasi kerak")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    try:
        src = instagram_client.fetch_repost_source(body.url)
    except NotLoggedInError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Postni yuklab bo'lmadi: {e}")

    caption = body.caption.strip()
    if not caption:
        credit = f"\n\n· @{src['original_user']}" if src.get("original_user") else ""
        caption = (src.get("caption", "") + credit).strip()

    results = []
    for username in body.usernames:
        try:
            instagram_client.repost_to_account(src, username, caption)
            history.add(body.url, "repost", "🔁 repost", body.url, username)
            results.append({"username": username, "ok": True})
        except (RateLimitError, NotLoggedInError) as e:
            results.append({"username": username, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"username": username, "ok": False, "error": str(e)})

    instagram_client.cleanup_repost_source(src)
    return {"results": results, "accounts": instagram_client.list_accounts()}


# ---------- Story repost ----------

@app.post("/api/story")
def story(body: RepostBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    if not REPOST_STORY_ENABLED:
        raise HTTPException(status_code=403, detail=_REPOST_STORY_OFF_MSG)
    if not body.url:
        raise HTTPException(status_code=400, detail="Story uchun post havolasi kerak")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    try:
        src = instagram_client.fetch_repost_source(body.url)
    except NotLoggedInError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Postni yuklab bo'lmadi: {e}")

    results = []
    for username in body.usernames:
        try:
            instagram_client.story_to_account(src, username)
            history.add(body.url, "story", "📖 story", body.url, username)
            results.append({"username": username, "ok": True})
        except (RateLimitError, NotLoggedInError) as e:
            results.append({"username": username, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"username": username, "ok": False, "error": str(e)})

    instagram_client.cleanup_repost_source(src)
    return {"results": results, "accounts": instagram_client.list_accounts()}


@app.get("/api/history")
def get_history(session: str | None = Cookie(default=None)):
    _check_auth(session)
    return {"items": history.recent(30)}


# ---------- Frontend ----------

@app.get("/")
def index():
    # index.html keshlanmasin — ?v= versiyali static fayllar har doim yangilansin.
    return FileResponse(_STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
