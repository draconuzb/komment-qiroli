"""Web-panel (FastAPI): Komment Qiroli — ko'p akkaunt + ko'p AI provayder.

Ishga tushirish:
    python app.py
yoki:
    uvicorn app:app --host 127.0.0.1 --port 8000
"""
import re
import secrets
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import settings
import ai_client
import instagram_client
import history
from instagram_client import RateLimitError, NotLoggedInError

app = FastAPI(title="Komment Qiroli")

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


# ---------- Generatsiya ----------

class GenerateBody(BaseModel):
    text: str
    provider: str = "claude"


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
            media_id, caption = instagram_client.fetch_media(url)
        except NotLoggedInError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Postni o'qib bo'lmadi: {e}")
        if not caption:
            raise HTTPException(
                status_code=422,
                detail="Bu postda matn (caption) yo'q. Mavzuni alohida matn qilib kiriting.",
            )
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
        "provider": body.provider,
        "comments": comments,
    }


# ---------- Joylash (tanlangan akkauntlardan) ----------

class PostBody(BaseModel):
    media_id: str
    style: str
    text: str
    url: str = ""
    usernames: list[str]


@app.post("/api/post")
def post(body: PostBody, session: str | None = Cookie(default=None)):
    _check_auth(session)

    if not body.media_id:
        raise HTTPException(status_code=400, detail="media_id yo'q — avtomatik joylab bo'lmaydi")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    results = []
    for username in body.usernames:
        try:
            instagram_client.post_comment(body.media_id, body.text, username)
            history.add(body.media_id, body.style, body.text, body.url, username)
            results.append({"username": username, "ok": True})
        except (RateLimitError, NotLoggedInError) as e:
            results.append({"username": username, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"username": username, "ok": False, "error": str(e)})

    return {"results": results, "accounts": instagram_client.list_accounts()}


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

    results = []
    for username in body.usernames:
        try:
            instagram_client.like_media(body.media_id, username)
            history.add(body.media_id, "like", "❤️ like", body.url, username)
            results.append({"username": username, "ok": True})
        except (RateLimitError, NotLoggedInError) as e:
            results.append({"username": username, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"username": username, "ok": False, "error": str(e)})
    return {"results": results, "accounts": instagram_client.list_accounts()}


# ---------- Ko'rish (view) ----------

@app.post("/api/view")
def view(body: ActionBody, session: str | None = Cookie(default=None)):
    _check_auth(session)
    if not body.media_id:
        raise HTTPException(status_code=400, detail="media_id yo'q")
    if not body.usernames:
        raise HTTPException(status_code=400, detail="Kamida bitta akkaunt tanlang")

    results = []
    for username in body.usernames:
        try:
            instagram_client.view_media(body.media_id, username)
            history.add(body.media_id, "view", "👁 view", body.url, username)
            results.append({"username": username, "ok": True})
        except (RateLimitError, NotLoggedInError) as e:
            results.append({"username": username, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"username": username, "ok": False, "error": str(e)})
    return {"results": results, "accounts": instagram_client.list_accounts()}


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
    return FileResponse(_STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
