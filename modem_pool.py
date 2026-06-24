"""Local mobil-modem proxy pool — IPRoyal o'rniga o'z 4G modemlaringiz.

G'oya: mini-PC'ga ulangan har bir USB 4G modem = bitta UZ mobil IP. 3proxy har
modemga bitta SOCKS5 port beradi va trafikni o'sha modemning chiquvchi IP'siga
bog'laydi (-e<ext_ip>). Akkauntlar modemlarga STICKY taqsimlanadi (har akkaunt
doim o'sha modem/IP'dan chiqadi — Instagram uchun barqarorlik muhim). Bot esa
socks5://HOST:PORT orqali ulanadi.

    bot ──socks5://127.0.0.1:10001──► 3proxy ──(-e 192.168.8.100)──► modem1 ──► UZ mobil IP

Fayllar (config.DATA_DIR ichida):
  modems.json         — modem ta'riflari
  account_modem.json  — {username: modem_id} sticky xarita

3proxy bilan bog'liq: gen_3proxy_config() konfiguratsiya matnini yaratadi.
Rotation: Huawei HiLink (HTTP API) yoki Android (ADB) qo'llab-quvvatlanadi.
"""
import json
import os
import subprocess
import xml.etree.ElementTree as ET

import requests

import config

_MODEMS_FILE = os.path.join(config.DATA_DIR, "modems.json")
_ASSIGN_FILE = os.path.join(config.DATA_DIR, "account_modem.json")

# Bot 3proxy'ga qaysi host orqali ulanadi. Docker'da konteyner host'ni ko'rishi uchun
# docker-compose'da `network_mode: host` qo'ying (eng oson) — shunda 127.0.0.1 ishlaydi.
PROXY_HOST = os.getenv("MODEM_PROXY_HOST", "127.0.0.1")
# 3proxy SOCKS portlari shu sondan boshlanadi (m1=10001, m2=10002, ...).
PORT_BASE = int(os.getenv("MODEM_PORT_BASE", "10001"))


# ---------- Fayl yordamchilari ----------

def _read(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _write(path: str, data) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_modems() -> list[dict]:
    return _read(_MODEMS_FILE, {"modems": []}).get("modems", [])


def _save_modems(modems: list[dict]) -> None:
    _write(_MODEMS_FILE, {"modems": modems})


def _load_assign() -> dict:
    return _read(_ASSIGN_FILE, {})


def _save_assign(data: dict) -> None:
    _write(_ASSIGN_FILE, data)


# ---------- Modemlarni boshqarish ----------

def _next_port(modems: list[dict]) -> int:
    used = {m["port"] for m in modems if m.get("port")}
    p = PORT_BASE
    while p in used:
        p += 1
    return p


def add_modem(ext_ip: str, modem_id: str = "", rotate: dict | None = None,
              label: str = "") -> dict:
    """Pool'ga modem qo'shadi.

    ext_ip  — modemning host'dagi chiquvchi IP'si (3proxy -e shu IP'ga bog'laydi).
    rotate  — {"type": "huawei", "url": "http://192.168.8.1"} yoki
              {"type": "adb", "serial": "<adb-serial>"}; bo'sh bo'lsa rotation o'chiq.
    """
    ext_ip = (ext_ip or "").strip()
    if not ext_ip:
        raise ValueError("ext_ip (modem chiquvchi IP) kerak")
    modems = _load_modems()
    if not modem_id:
        n = 1
        existing = {m["id"] for m in modems}
        while f"m{n}" in existing:
            n += 1
        modem_id = f"m{n}"
    if any(m["id"] == modem_id for m in modems):
        raise ValueError(f"'{modem_id}' allaqachon mavjud")
    modem = {
        "id": modem_id,
        "label": label or modem_id,
        "ext_ip": ext_ip,
        "port": _next_port(modems),
        "rotate": rotate or {},
    }
    modems.append(modem)
    _save_modems(modems)
    return modem


def remove_modem(modem_id: str) -> None:
    modems = [m for m in _load_modems() if m["id"] != modem_id]
    _save_modems(modems)
    # Shu modemga biriktirilgan akkauntlarni bo'shatamiz (keyin qayta taqsimlanadi).
    assign = _load_assign()
    changed = False
    for user, mid in list(assign.items()):
        if mid == modem_id:
            assign.pop(user)
            changed = True
    if changed:
        _save_assign(assign)


def get_modem(modem_id: str) -> dict | None:
    return next((m for m in _load_modems() if m["id"] == modem_id), None)


def list_modems() -> list[dict]:
    """Modemlar + har biriga biriktirilgan akkaunt soni."""
    assign = _load_assign()
    counts: dict[str, int] = {}
    for mid in assign.values():
        counts[mid] = counts.get(mid, 0) + 1
    out = []
    for m in _load_modems():
        out.append({
            "id": m["id"],
            "label": m.get("label", m["id"]),
            "ext_ip": m["ext_ip"],
            "port": m["port"],
            "proxy": f"socks5://{PROXY_HOST}:{m['port']}",
            "accounts": counts.get(m["id"], 0),
            "rotate_type": (m.get("rotate") or {}).get("type", ""),
        })
    return out


# ---------- Akkaunt ↔ modem taqsimoti (sticky, balanslangan) ----------

def _balanced_modem(modems: list[dict], assign: dict) -> dict | None:
    if not modems:
        return None
    counts = {m["id"]: 0 for m in modems}
    for mid in assign.values():
        if mid in counts:
            counts[mid] += 1
    return min(modems, key=lambda m: counts[m["id"]])


def assign(username: str, modem_id: str = "") -> str:
    """Akkauntni modemga sticky biriktiradi va socks5 URL qaytaradi.

    Allaqachon biriktirilgan bo'lsa — o'shani qaytaradi (modem_id berilmasa).
    Modem yo'q bo'lsa — bo'sh satr (chaqiruvchi IPRoyal'ga qaytishi mumkin).
    """
    modems = _load_modems()
    if not modems:
        return ""
    assign_map = _load_assign()

    if modem_id:
        if not any(m["id"] == modem_id for m in modems):
            raise ValueError(f"'{modem_id}' modem topilmadi")
        assign_map[username] = modem_id
        _save_assign(assign_map)
    elif username not in assign_map or assign_map[username] not in {m["id"] for m in modems}:
        chosen = _balanced_modem(modems, assign_map)
        assign_map[username] = chosen["id"]
        _save_assign(assign_map)

    return proxy_for(username)


def unassign(username: str) -> None:
    assign_map = _load_assign()
    if assign_map.pop(username, None) is not None:
        _save_assign(assign_map)


def proxy_for(username: str) -> str:
    """Akkauntga biriktirilgan modemning socks5 URL'i. Yo'q bo'lsa bo'sh satr."""
    mid = _load_assign().get(username)
    if not mid:
        return ""
    m = get_modem(mid)
    if not m:
        return ""
    return f"socks5://{PROXY_HOST}:{m['port']}"


def bootstrap_proxy() -> str:
    """Username hali noma'lum bo'lganda (sessionid login) — balanslangan modem proxysi."""
    modems = _load_modems()
    m = _balanced_modem(modems, _load_assign())
    return f"socks5://{PROXY_HOST}:{m['port']}" if m else ""


def has_modems() -> bool:
    return bool(_load_modems())


# ---------- 3proxy konfiguratsiyasi ----------

def gen_3proxy_config() -> str:
    """Barcha modemlar uchun 3proxy konfiguratsiya matnini yaratadi.

    Har modemga: socks -p<port> -i127.0.0.1 -e<ext_ip>
    -i127.0.0.1 — faqat lokaldan (xavfsiz). Docker konteyner host tarmog'ida
    (network_mode: host) bo'lsa shu ishlaydi.
    """
    modems = _load_modems()
    lines = [
        "# AVTOMATIK yaratilgan (modem_pool.py) — qo'lda tahrirlamang.",
        "nserver 8.8.8.8",
        "nserver 1.1.1.1",
        "nscache 65536",
        "timeouts 1 5 30 60 180 1800 15 60",
        "auth none",
        "allow *",
        "",
    ]
    listen = os.getenv("MODEM_3PROXY_LISTEN", "127.0.0.1")
    for m in modems:
        lines.append(f"# {m.get('label', m['id'])}  (IP: {m['ext_ip']})")
        lines.append(f"socks -p{m['port']} -i{listen} -e{m['ext_ip']}")
        lines.append("flush")
        lines.append("")
    return "\n".join(lines)


def write_3proxy_config(path: str = "") -> str:
    path = path or os.path.join(config.DATA_DIR, "3proxy.cfg")
    cfg = gen_3proxy_config()
    with open(path, "w", encoding="utf-8") as f:
        f.write(cfg)
    return path


# ---------- IP tekshirish va rotation ----------

def current_ip(modem_id: str, timeout: int = 15) -> str:
    """Modem proxysi orqali tashqi IP'ni qaytaradi (https://api.ipify.org)."""
    m = get_modem(modem_id)
    if not m:
        raise ValueError("modem topilmadi")
    proxy = f"socks5://{PROXY_HOST}:{m['port']}"
    proxies = {"http": proxy, "https": proxy}
    r = requests.get("https://api.ipify.org", proxies=proxies, timeout=timeout)
    r.raise_for_status()
    return r.text.strip()


def _rotate_huawei(url: str, timeout: int = 15) -> bool:
    """Huawei HiLink modem: mobil data'ni o'chirib-yoqib yangi IP oladi.

    Token-himoyali API: avval SesTokInfo'dan SessionID+token olamiz, so'ng
    dataswitch 0 → 1 yuboramiz.
    """
    url = url.rstrip("/")
    s = requests.Session()
    tok = s.get(f"{url}/api/webserver/SesTokInfo", timeout=timeout)
    root = ET.fromstring(tok.text)
    sess = root.findtext("SesInfo") or ""
    token = root.findtext("TokInfo") or ""
    s.headers.update({"Cookie": sess, "__RequestVerificationToken": token,
                      "Content-Type": "application/x-www-form-urlencoded"})

    def _switch(val: int) -> None:
        body = f"<?xml version='1.0' encoding='UTF-8'?><request><dataswitch>{val}</dataswitch></request>"
        s.post(f"{url}/api/dialup/mobile-dataswitch", data=body, timeout=timeout)

    _switch(0)
    import time
    time.sleep(3)
    _switch(1)
    return True


def _rotate_adb(serial: str, timeout: int = 20) -> bool:
    """Android (USB-tethering) modem: data'ni o'chirib-yoqib yangi mobil IP oladi."""
    base = ["adb"] + (["-s", serial] if serial else [])
    subprocess.run(base + ["shell", "svc", "data", "disable"], timeout=timeout, check=False)
    import time
    time.sleep(3)
    subprocess.run(base + ["shell", "svc", "data", "enable"], timeout=timeout, check=False)
    return True


def rotate(modem_id: str) -> bool:
    """Modem IP'sini yangilaydi (rotate turiga qarab). Sozlanmagan bo'lsa xato."""
    m = get_modem(modem_id)
    if not m:
        raise ValueError("modem topilmadi")
    rot = m.get("rotate") or {}
    rtype = rot.get("type", "")
    if rtype == "huawei":
        return _rotate_huawei(rot.get("url", ""))
    if rtype == "adb":
        return _rotate_adb(rot.get("serial", ""))
    raise RuntimeError(f"@{modem_id}: rotation sozlanmagan (type='{rtype or 'yo`q'}')")


# ---------- Avtomatik aniqlash (yordamchi) ----------

def detect_candidates() -> list[dict]:
    """`ip -j addr` orqali modemga o'xshash interfeyslarni taxminiy aniqlaydi.

    USB 4G modemlar odatda 192.168.8.x / 192.168.0.x / 192.168.1.x kabi alohida
    kichik tarmoq beradi. Bu faqat TAKLIF — ext_ip va rotate url'ni tekshiring.
    """
    try:
        out = subprocess.check_output(["ip", "-j", "addr"], timeout=10, text=True)
        ifaces = json.loads(out)
    except Exception:
        return []
    cands = []
    for it in ifaces:
        name = it.get("ifname", "")
        if name in ("lo",) or name.startswith(("docker", "veth", "br-")):
            continue
        for a in it.get("addr_info", []):
            ip = a.get("local", "")
            if a.get("family") == "inet" and ip.startswith("192.168."):
                # modem gateway odatda .1, host esa .100/.101 — taxmin
                gw = ".".join(ip.split(".")[:3]) + ".1"
                cands.append({"iface": name, "ext_ip": ip, "guess_rotate_url": f"http://{gw}"})
    return cands
