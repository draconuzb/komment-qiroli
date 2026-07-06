"""Global komment navbati (ban himoyasi).

- Link kelsa, har akkaunt OYNA (schedule_window, default 2 kun) ichiga TASODIFIY
  joylashtiriladi, har biri kamida `schedule_gap_min` (default 3 daq) oraliq bilan.
- BITTA ishlovchi (worker) navbatni birma-bir bajaradi → hech qachon 2 ta komment
  bir vaqtda ketmaydi, har doim >=3 daq oraliq (butun tizim bo'ylab).
- Navbat faylga (data/queue.json) saqlanadi — qayta ishga tushsa yo'qolmaydi.
- Worker FAQAT web (uvicorn) jarayonida ishlaydi. Bot/webhook/panel — hammasi shu
  bitta navbatga vazifa qo'shadi (enqueue).
"""
import datetime
import json
import os
import random
import secrets
import threading
import time

import requests

import config
import settings
import instagram_client
import ai_client
import history


def _tg_log(text: str) -> None:
    """Log kanalga xabar yuboradi (Telegram HTTP API, best-effort)."""
    token = config.TELEGRAM_BOT_TOKEN
    chat = config.TELEGRAM_LOG_CHANNEL
    if not token or not chat:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception:
        pass

_FILE = os.path.join(config.DATA_DIR, "queue.json")
_lock = threading.RLock()
_DONE_KEEP = 300  # eski done/failed yozuvlardan nechtasini saqlash

# Faqat HAQIQIY sessiya o'limi belgilari (tarmoq/timeout/"not found" — o'lim EMAS,
# aks holda tirik akkaunt soxta o'lik bo'lib qoladi).
_DEAD_HINTS = ("login_required", "logged_out", "logged out", "user_has_logged_out",
               "checkpoint", "challenge_required", "not logged", "o'lik akkaunt",
               "sessiyasi eskirgan")


# ---------- Saqlash ----------

def _load() -> dict:
    if os.path.exists(_FILE):
        try:
            with open(_FILE, encoding="utf-8") as f:
                d = json.load(f)
                d.setdefault("tasks", [])
                d.setdefault("last_post", 0)
                return d
        except Exception:
            pass
    return {"tasks": [], "last_post": 0}


def _save(d: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _FILE)


# ---------- Navbatga qo'shish (B rejimi: oynaga taqsimlash) ----------

def enqueue(url: str, media_id: str, usernames: list[str], like: bool = True,
            source: str = "") -> dict:
    """Akkauntlarni oynaga tasodifiy, >=gap_min oraliq bilan rejalashtiradi.
    source — qaysi manba kanaldan kelgani (log uchun). Qaytaradi: {queued, first_at, last_at}."""
    gap_min = int(settings.get("schedule_gap_min") or 180)
    window = int(settings.get("schedule_window") or 10800)
    # Takror himoyasi: shu media'ga ALLAQACHON komment yozgan akkauntlarni qo'shmaymiz.
    if media_id:
        usernames = [u for u in usernames if not history.already_commented(media_id, u)]
    # YOZa olmaydigan (write-dead) akkauntlarni o'tkazamiz — behuda urinish/relogin yo'q.
    usernames = [u for u in usernames if not instagram_client.is_write_dead(u)]
    if not usernames:
        _tg_log(f"📥 [{source or 'panel'}] link — yoza oladigan akkaunt yo'q (yoki hammasi yozgan).\n{url}")
        return {"queued": 0, "first_at": 0, "last_at": 0}

    batch_id = secrets.token_urlsafe(6)
    with _lock:
        d = _load()
        now = time.time()
        # Bu BATCH ni HOZIRDAN boshlab oynaga tasodifiy joylaymiz (ketma-ket stack
        # qilmaymiz — ko'p link kelsa oyna ichida ARALASHADI, 2 kunga cho'zilmaydi).
        # Bir batch ichida >=gap_min ni majburlaymiz; BATCHLAR ORASIDAGI to'qnashuvni
        # esa worker run-time da (>=gap_min global) hal qiladi — hech qachon 2 ta birga ketmaydi.
        offsets = sorted(random.uniform(0, window) for _ in usernames)
        times = []
        last = now
        for off in offsets:
            rt = max(now + off, last + gap_min)
            times.append(rt)
            last = rt

        for u, rt in zip(usernames, times):
            d["tasks"].append({
                "id": secrets.token_urlsafe(6),
                "url": url, "media_id": media_id or "", "username": u,
                "like": bool(like), "run_at": rt, "status": "pending",
                "error": "", "created_at": now,
                "source": source or "panel", "batch_id": batch_id,
            })
        _save(d)

    eta = datetime.datetime.fromtimestamp(times[-1]).strftime("%m-%d %H:%M")
    _tg_log(f"📥 [{source or 'panel'}] yangi link → {len(usernames)} akkaunt navbatga.\n"
            f"Oxirgisi ~{eta}\n{url}")
    return {"queued": len(usernames), "first_at": times[0], "last_at": times[-1]}


def snapshot() -> dict:
    """Panel uchun navbat holati."""
    with _lock:
        d = _load()
    now = time.time()
    pend = [t for t in d["tasks"] if t["status"] == "pending"]
    pend.sort(key=lambda t: t["run_at"])
    done = sum(1 for t in d["tasks"] if t["status"] == "done")
    failed = sum(1 for t in d["tasks"] if t["status"] == "failed")
    nxt = pend[0]["run_at"] if pend else 0
    return {
        "pending": len(pend), "done": done, "failed": failed,
        "next_in": max(0, int(nxt - now)) if nxt else 0,
        "last_at": int(pend[-1]["run_at"]) if pend else 0,
        "items": [
            {"username": t["username"], "in_sec": max(0, int(t["run_at"] - now)),
             "url": t["url"]}
            for t in pend[:50]
        ],
    }


def clear_pending() -> int:
    """Kutayotgan vazifalarni bekor qiladi (joylanganlarga tegmaydi)."""
    with _lock:
        d = _load()
        before = len(d["tasks"])
        d["tasks"] = [t for t in d["tasks"] if t["status"] != "pending"]
        _save(d)
        return before - len(d["tasks"])


def accelerate(gap_min: float = 120, gap_max: float = 240) -> int:
    """Kutayotgan vazifalarni HOZIRDAN boshlab, 2-4 daqiqa (gap_min..gap_max) oraliq
    bilan qayta rejalashtiradi — '2 kun' oynani kutmasdan tezroq jo'natish uchun.
    Tartib saqlanadi, hech qachon 2 tasi birga ketmaydi."""
    with _lock:
        d = _load()
        pend = [t for t in d["tasks"] if t["status"] == "pending"]
        pend.sort(key=lambda t: t["run_at"])
        last = time.time()
        for t in pend:
            last += random.uniform(gap_min, gap_max)
            t["run_at"] = last
        _save(d)
    if pend:
        _tg_log(f"⚡ Tezlashtirildi: {len(pend)} ta komment 2-4 daqiqa oraliq bilan jo'natiladi.")
    return len(pend)


# ---------- Bajarish ----------

def _do_post(task: dict) -> tuple[bool, str]:
    u = task["username"]
    try:
        if instagram_client.is_write_dead(u):
            return False, "yoza olmaydigan akkaunt (o'tkazildi)"
        media_id = task.get("media_id") or ""
        # Caption/rasmni post vaqtida olamiz (yangi, og:meta — xavfsiz).
        mid, caption, thumb = instagram_client.fetch_media(task["url"])
        media_id = media_id or mid
        if history.already_commented(media_id, u):
            return False, "allaqachon komment yozilgan"

        persona = instagram_client.get_personality(u)
        provs = ai_client.available_providers()
        # Afzal provayder (settings) — biri ishlamasa generate_one avto zaxiraga o'tadi.
        prov = settings.get("ai_provider") or (provs[0]["id"] if provs else "groq")
        if caption:
            text = ai_client.generate_one(caption, persona, prov)
        elif thumb:
            import requests
            img = requests.get(thumb, timeout=15).content
            text = ai_client.generate_one_from_image(img, persona)
        else:
            return False, "post matni ham, rasm ham yo'q"

        instagram_client.post_comment(media_id, text, u)
        instagram_client.set_write_status(u, True)  # ✍️ YOZDI — ishlaydi
        history.add(media_id, persona, text, task["url"], u)
        if task.get("like") and not history.already_liked(media_id, u):
            try:
                instagram_client.like_media(media_id, u)
                history.add(media_id, "like", "❤️ like", task["url"], u)
            except Exception:
                pass
        return True, ""
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        # Yozishда auth-xato (login_required...) → akkaunt YOZa olmaydi: write-dead.
        # (Timeout/tarmoq/rate-limit — write-dead EMAS, qayta uriniladi.)
        if any(h in msg.lower() for h in _DEAD_HINTS):
            try:
                was_ok = instagram_client.get_write_status(u).get("ok")
                instagram_client.set_write_status(u, False)   # ✍️❌ yoza olmaydi
                if was_ok is not False:  # ilgari ishlayotgan edi — endi tushdi: xabar
                    _tg_log(f"⚠️ @{u} yoza olmayapti (login_required) — mini-PC'da qayta qo'shing.")
            except Exception:
                pass
        return False, msg


def notify_dead(username: str) -> None:
    """Akkaunt HAQIQATAN o'lganda log kanalga ogohlantirish."""
    _tg_log(f"🔴 @{username} sessiyasi o'ldi — ilova orqali QAYTA qo'shing.")


def _keepalive_worker() -> None:
    """Keep-alive — DEFAULT O'CHIQ (interval<=0). Har relogin (login_by_sessionid)
    Instagram uchun 'login hodisasi'; ko'p relogin → flag → COOKIE O'LADI. Shuning uchun
    avtomatik tekshirish/relogin qilmaymiz — cookie'ni tinch qoldiramiz.
    Yoqilса (interval>0): relogin'SIZ yengil tekshiruv."""
    time.sleep(150)
    while True:
        try:
            interval = int(settings.get("keepalive_interval") or 0)
            if interval <= 0:
                time.sleep(3600)      # o'chiq — hech narsa qilmaymiz
                continue
            for u in [a["username"] for a in instagram_client.list_accounts()]:
                try:
                    instagram_client.check_account(u, relogin=False)  # relogin YO'Q (cookie tinch)
                except Exception:
                    pass
                time.sleep(random.uniform(90, 180))
            time.sleep(interval)
        except Exception:
            time.sleep(600)


def _worker() -> None:
    while True:
        try:
            gap_min = int(settings.get("schedule_gap_min") or 180)
            task = None
            with _lock:
                d = _load()
                now = time.time()
                pend = [t for t in d["tasks"] if t["status"] == "pending"]
                pend.sort(key=lambda t: t["run_at"])
                # vaqti kelgan VA oxirgi postdan >=gap_min o'tgan bo'lsa
                if pend and pend[0]["run_at"] <= now and (now - d.get("last_post", 0)) >= gap_min:
                    task = pend[0]
            if task:
                ok, err = _do_post(task)  # lock tashqarisida (sekin)
                src = task.get("source", "panel")
                batch_summary = None
                with _lock:
                    d = _load()
                    for t in d["tasks"]:
                        if t["id"] == task["id"]:
                            # Qayta urinsa bo'ladimi? (tirik akkaunt, vaqtinchalik xato)
                            retryable = (not ok) and not any(x in (err or "").lower() for x in (
                                "allaqachon", "o'lik akkaunt", "matni ham, rasm", "kunlik limit"))
                            tries = t.get("tries", 0)
                            if retryable and tries < 2:
                                t["status"] = "pending"          # qayta navbatga
                                t["tries"] = tries + 1
                                t["run_at"] = time.time() + random.uniform(600, 1200)  # 10-20 daq keyin
                                t["error"] = f"(qayta {tries + 1}/2) {err}"
                            else:
                                t["status"] = "done" if ok else "failed"
                                t["error"] = err
                            break
                    d["last_post"] = time.time()
                    # Batch tugadimi? (shu link bo'yicha boshqa pending qolmaganmi)
                    bid = task.get("batch_id")
                    if bid:
                        bt = [t for t in d["tasks"] if t.get("batch_id") == bid]
                        if not any(t["status"] == "pending" for t in bt):
                            ok_n = sum(1 for t in bt if t["status"] == "done")
                            fail_n = sum(1 for t in bt if t["status"] == "failed")
                            batch_summary = (src, task["url"], ok_n, fail_n)
                    # eski yakunlanganlarni cheklash
                    finished = [t for t in d["tasks"] if t["status"] != "pending"]
                    if len(finished) > _DONE_KEEP:
                        keep_ids = {t["id"] for t in finished[-_DONE_KEEP:]}
                        d["tasks"] = [t for t in d["tasks"]
                                      if t["status"] == "pending" or t["id"] in keep_ids]
                    _save(d)
                # Log (lock tashqarisida)
                if ok:
                    _tg_log(f"✅ @{task['username']} komment+like · [{src}]\n{task['url']}")
                else:
                    _tg_log(f"❌ @{task['username']}: {err[:80]} · [{src}]")
                if batch_summary:
                    s, u_, on, fn = batch_summary
                    _tg_log(f"📊 [{s}] link tugadi: ✅ {on} komment · ❌ {fn} xato\n{u_}")
            time.sleep(20)
        except Exception:
            time.sleep(30)


_started = False


def start_worker() -> None:
    """Web (uvicorn) jarayonida BIR marta ishga tushiriladi."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_keepalive_worker, daemon=True).start()  # avto keep-alive
