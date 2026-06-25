"""Global komment navbati (ban himoyasi).

- Link kelsa, har akkaunt OYNA (schedule_window, default 2 kun) ichiga TASODIFIY
  joylashtiriladi, har biri kamida `schedule_gap_min` (default 3 daq) oraliq bilan.
- BITTA ishlovchi (worker) navbatni birma-bir bajaradi → hech qachon 2 ta komment
  bir vaqtda ketmaydi, har doim >=3 daq oraliq (butun tizim bo'ylab).
- Navbat faylga (data/queue.json) saqlanadi — qayta ishga tushsa yo'qolmaydi.
- Worker FAQAT web (uvicorn) jarayonida ishlaydi. Bot/webhook/panel — hammasi shu
  bitta navbatga vazifa qo'shadi (enqueue).
"""
import json
import os
import random
import secrets
import threading
import time

import config
import settings
import instagram_client
import ai_client
import history

_FILE = os.path.join(config.DATA_DIR, "queue.json")
_lock = threading.RLock()
_DONE_KEEP = 300  # eski done/failed yozuvlardan nechtasini saqlash

_DEAD_HINTS = ("login", "sessiya", "o'lik", "logged_out", "logged out", "challenge",
               "not found", "checkpoint", "401", "403", "unauthorized")


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

def enqueue(url: str, media_id: str, usernames: list[str], like: bool = True) -> dict:
    """Akkauntlarni oynaga tasodifiy, >=gap_min oraliq bilan rejalashtiradi.
    Qaytaradi: {queued, first_at, last_at}."""
    gap_min = int(settings.get("schedule_gap_min") or 180)
    window = int(settings.get("schedule_window") or 172800)
    if not usernames:
        return {"queued": 0, "first_at": 0, "last_at": 0}

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
            })
        _save(d)
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


# ---------- Bajarish ----------

def _do_post(task: dict) -> tuple[bool, str]:
    u = task["username"]
    try:
        if instagram_client.is_dead(u):
            return False, "o'lik akkaunt (o'tkazib yuborildi)"
        media_id = task.get("media_id") or ""
        # Caption/rasmni post vaqtida olamiz (yangi, og:meta — xavfsiz).
        mid, caption, thumb = instagram_client.fetch_media(task["url"])
        media_id = media_id or mid
        if history.already_commented(media_id, u):
            return False, "allaqachon komment yozilgan"

        persona = instagram_client.get_personality(u)
        provs = ai_client.available_providers()
        prov = provs[0]["id"] if provs else "claude"
        if caption:
            text = ai_client.generate_one(caption, persona, prov)
        elif thumb:
            import requests
            img = requests.get(thumb, timeout=15).content
            text = ai_client.generate_one_from_image(img, persona)
        else:
            return False, "post matni ham, rasm ham yo'q"

        instagram_client.post_comment(media_id, text, u)
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
        if any(h in msg.lower() for h in _DEAD_HINTS):
            try:
                instagram_client.mark_dead(u)
            except Exception:
                pass
        return False, msg


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
                with _lock:
                    d = _load()
                    for t in d["tasks"]:
                        if t["id"] == task["id"]:
                            t["status"] = "done" if ok else "failed"
                            t["error"] = err
                            break
                    d["last_post"] = time.time()
                    # eski yakunlanganlarni cheklash
                    finished = [t for t in d["tasks"] if t["status"] != "pending"]
                    if len(finished) > _DONE_KEEP:
                        keep_ids = {t["id"] for t in finished[-_DONE_KEEP:]}
                        d["tasks"] = [t for t in d["tasks"]
                                      if t["status"] == "pending" or t["id"] in keep_ids]
                    _save(d)
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
