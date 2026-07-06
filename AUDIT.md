# Komment Qiroli — To'liq Xavfsizlik Auditi (2026-06-24)

5 ta parallel agent bilan: web/API, IG+AI klientlar, bot/modem/config, frontend, infra/secrets.
Severity bo'yicha tartiblangan, takrorlar birlashtirilgan.

---

## ⚠️ ENG MUHIM XULOSA

- **Git TOZA** — `.env`, `bekpro.pem`, sessiyalar, kalitlar GitHub'ga hech qachon chiqmagan (tarixda ham). `.gitignore` to'g'ri ishlaydi. Eng katta xavf (public repo'da leak) **yuz bermagan**.
- **LEKIN diskda tirik kalitlar ochiq** va kod darajasida bir nechta CRITICAL bor (auth fail-open, SSRF, Telegram bypass, Docker'ga SSH key, kuchsiz parol). Bular **darhol** tuzatilishi kerak.

---

## CRITICAL

### C1 — Panel auth fail-open: parol bo'sh bo'lsa BUTUN panel ochiq
`app.py:48-52`, `config.py:58`
`_check_auth()` parol bo'sh bo'lsa darrov `return` qiladi; `PANEL_PASSWORD` default `""`. Parol o'rnatilmagan deploy'da akkaunt qo'shish/o'chirish, settings yozish, `/api/run` — hammasi parolsiz.
**Fix:** Fail-closed — parol yo'q bo'lsa ishga tushmasin yoki barcha mutatsion so'rovni 403 qilsin.

### C2 — Telegram kanal handler'ida avtorizatsiya YO'Q
`bot.py:141-152` (`on_channel`)
`on_dm` da `_authorized()` bor, `on_channel` da yo'q. `TELEGRAM_CHANNEL_ID` bo'sh bo'lsa bot **admin bo'lgan har qanday kanaldagi** IG havolaga komment/like bosadi → `ALLOWED_TELEGRAM_IDS` butunlay chetlab o'tiladi.
**Fix:** `if not want: return` + kanal `chat.id` ni allowlist bilan tekshirish.

### C3 — SSRF: server ixtiyoriy URL'larni o'qiydi (AWS metadata o'g'irlash)
`instagram_client.py:525, 570-578` (`fetch_media`/`_fetch_via_page`), `app.py:343-353` (`_download_image`), `bot.py:102-104`, `modem_pool.py:268-291` (`rotate_url`)
`fetch_media` user URL'ni to'g'ridan-to'g'ri (proxysiz, AWS IP'dan) `requests.get` qiladi — host/scheme tekshiruvi yo'q, redirect ochiq. `http://169.254.169.254/latest/meta-data/iam/...` → IAM kredensiallarini o'g'irlash; ichki xizmatlarga so'rov.
**Fix:** Host allowlist (`instagram.com`), RFC1918/link-local/loopback IP'larni blok, `allow_redirects=False`. `rotate_url` ni modem gateway diapazoniga cheklash.

### C4 — SSH private key (`bekpro.pem`) Docker image'ga tushadi
`.dockerignore` (`*.pem` YO'Q) + `Dockerfile` `COPY . .`
`.dockerignore`'da `.env`, `sessions/`, `*.json` bor, lekin `*.pem`/`*.key` yo'q → `bekpro.pem` image qatlamiga baked bo'ladi. Image'ga ega har kim EC2 serverga SSH kalitni oladi → to'liq server kompromisi.
**Fix:** `.dockerignore`'ga `*.pem *.key *.ppk` qo'shing, kalitni repo papkasidan olib tashlang, **AWS key-pair rotatsiya qiling**.

### C5 — Diskda tirik kalitlar ochiq + kuchsiz panel parol
`.env`, `settings.json`, `sessions/*.json`
Tirik: `TELEGRAM_BOT_TOKEN`, `PANEL_PASSWORD=Salommen123` (kuchsiz!), `groq_api_key`, `mistral_api_key`, 3 ta IG akkaunt sessiya cookie'lari. Git'da emas, lekin serverda/backup'da; server kompromisida darrov ishlatiladi.
**Fix:** Hammasini **rotatsiya qiling** (BotFather revoke, Groq/Mistral qayta yarating, IG qayta login), panel parolni kuchli tasodifiy qiymatga.

---

## HIGH

### H1 — Webhook token timing-safe emas + `?token=` log'ga tushadi
`app.py:435` (`token != config.WEBHOOK_TOKEN`), `app.py:443,453` (query param)
Oddiy `!=` → timing oracle (auth/cookie kerak emas). `?token=` access log'da qoladi.
**Fix:** `secrets.compare_digest(...)`, faqat header, query param'ni olib tashlash.

### H2 — Prompt injection: dushman caption AI'ga uzatilib, akkauntdan avto-post bo'ladi
`prompts.py:73, 25`, `claude_client.py:58-64`, `ai_client.py:85-107`
Uchinchi tomon IG postining caption'i hech qanday izolyatsiyasiz prompt'ga qo'shiladi. `"Ignore all previous instructions..."` → model boshqariladi va natija real akkauntdan komment qilib chiqariladi. `generate_one` (post yo'li) schema'siz, erkin matn.
**Fix:** Caption'ni delimiter ichida "bu ma'lumot, ko'rsatma emas" deb berish; chiqishni validatsiya (uzunlik, URL/@mention bloki).

### H3 — `_apply_proxy` jim yiqiladi → so'rov AWS IP'dan ketadi (IP leak)
`instagram_client.py:212-218` va ~15 ta `except: pass` (79, 101, 160, 217, 241, 504...)
Proxy qo'llashda xato bo'lsa jimgina proxysiz davom etadi — butun proxy-izolyatsiya dizayni buziladi. JSON yuklash xatosi proxy/persona/counter holatini jim o'chiradi.
**Fix:** `_apply_proxy` xato bo'lsa **raise** qilsin; barcha swallow'larni `logging` bilan almashtirish.

### H4 — Panel HTTPSsiz, 8000-port internetga ochiq (nginx aylanadi)
`wecreate.conf` (`listen 80`), `docker-compose.yml` (`8000:8000`)
Parol/cookie ochiq HTTP'da uzatiladi (MITM). `54.160.255.7:8000` to'g'ridan-to'g'ri ishlaydi — nginx himoyalarini aylanib o'tadi.
**Fix:** Let's Encrypt HTTPS, `ports: "127.0.0.1:8000:8000"`, Security Group'dan 8000 inbound'ni yopish.

### H5 — DOM XSS: username/proxy/modem-label `innerHTML` orqali
`static/app.js:144-153` (renderAccounts), `383-389` (renderModems)
`a.username`, `a.proxy`, `m.label` escape'siz `innerHTML`'ga qo'yiladi. Dushman username/label (`<img src=x onerror=...>`) → admin panelda script bajariladi (sessionid'lar, AI kalitlari, barcha `/api/*` xavf ostida).
**Fix:** `textContent`/`createElement` ishlatish (kod allaqachon comment/history uchun to'g'ri qiladi).

### H6 — Plaintext sessionid va proxy kredensiallari diskda
`instagram_client.py:84-87` (proxies.json), `237-242` (`.sid`)
IG `sessionid` (= to'liq login) va IPRoyal parol ochiq saqlanadi. Diskni o'qiy olgan har kim barcha akkauntlarni egallaydi.
**Fix:** Parolni env'dan use-time'da qayta qurish; fayllarni shifrlash yoki 0600 + web-served papkadan tashqarida.

### H7 — `ALLOWED_TELEGRAM_IDS`: bo'sh = fail-open, xato qiymat = crash
`config.py:25-29`, `bot.py:39-40`
Bo'sh allowlist → `_authorized` `True` (hamma ruxsatli). `.env`da xato qiymat → import vaqtida `ValueError`, butun tizim ko'tarilmaydi.
**Fix:** Har element `try/except` parse; bo'sh allowlist'da fail-closed.

### H8 — CSRF himoyasi yo'q
`app.py:66` (cookie `samesite=lax`) + barcha POST/DELETE
Anti-CSRF token yoki Origin/Referer tekshiruvi yo'q. Login admin dushman sahifaga kirsa `/api/run`/delete trigger bo'lishi mumkin.
**Fix:** Double-submit CSRF token yoki strict Origin tekshiruvi; iloji bo'lsa `samesite=strict`.

### H9 — Atomik bo'lmagan yozish: `settings.json`/`history.json` buziladi, sirlar yo'qoladi
`settings.py:76-78`, `history.py:22-34`
To'g'ridan-to'g'ri target faylga yoziladi (modem_pool'dagi `tmp+os.replace` pattern ishlatilmagan). Crash'da yarim fayl → `except: pass` defaults'ga qaytadi → panel parol/kalitlar jim yo'qoladi (H1 bilan birga panel parolsiz ochiladi).
**Fix:** Atomik yozish (`tmp + os.replace`) + `threading.Lock`.

---

## MEDIUM

- **M1 — Rate-limit/daily-counter race (TOCTOU)** `instagram_client.py:631-665`: check va increment atomik emas, ThreadPool ostida limit oshib ketadi → ban. **Fix:** per-username lock, slotni oldindan rezerv.
- **M2 — Fon-job resurs tugatish + info leak** `app.py:525-554`: har so'rovda cheksiz thread; `/api/job/{id}` to'liq akkaunt ro'yxatini qaytaradi. **Fix:** concurrency cap, job javobidan akkaunt ro'yxatini olib tashlash.
- **M3 — `/api/status` auth'siz akkaunt inventarini sizdiradi** `app.py:80-91`: username/proxy host/personality/limit. **Fix:** auth orqasiga yoki `accounts`'ni olib tashlash.
- **M4 — Error matni proxy kredensiallarini sizdiradi** `app.py:144,209...`, `instagram_client.py:292`: `detail=str(e)` proxy URL'ini (user:pass) ko'rsatishi mumkin. **Fix:** generic xabar, to'liq log faqat serverda.
- **M5 — `pollJob` cheksiz loop, timeout/abort yo'q** `static/app.js:547-556`: job tugamasa UI muzlaydi, tugma abadiy disabled. **Fix:** max-attempt/timeout + AbortController.
- **M6 — Concurrent `pollJob` race** `static/app.js:568-606`: `state.accounts` overwrite, eski job yangini bosadi. **Fix:** in-flight guard yoki job-id tagging.
- **M7 — `/api/login` rate-limit/lockout yo'q + timing** `app.py:59-67`: online brute-force. **Fix:** rate-limit + `compare_digest`.
- **M8 — In-memory sessiya, TTL/cap yo'q** `app.py:43,65`: token server-side hech qachon eskirmaydi. **Fix:** expiry timestamp + prune.
- **M9 — Sonli sozlamalarga diapazon yo'q** `settings.py:63-79`: `min_seconds_between_comments=0` → ban. **Fix:** min/max clamp.
- **M10 — ADB/Huawei rotatsiya tekshirilmaydi** `modem_pool.py:294-301`: `check=False`, IP o'zgarmasa ham `True`. **Fix:** returncode tekshirish, IP o'zgarishini tasdiqlash.
- **M11 — AI fallback asimmetrik/lossy** `ai_client.py:69-124`: faqat "kalit yo'q"da fallback, runtime xatoda emas; `generate_comments`'da fallback yo'q; Groq/Mistral `json.loads` guard'siz. **Fix:** har provider'ni try/except bilan keyingisiga o'tkazish.
- **M12 — `ThreadPoolExecutor` timeout'da thread tashlab ketadi** `instagram_client.py:560-567`: 4 worker, sekin proxy hammasini band qiladi → cascading hang. **Fix:** worker sonini oshirish, instagrapi socket timeout pasaytirish.

---

## LOW

- **L1** — Konteyner root sifatida ishlaydi (`Dockerfile`, `USER` yo'q). **Fix:** non-root user.
- **L2** — Base image digest emas, faqat tag (`python:3.11-slim`). **Fix:** `@sha256:` pin.
- **L3** — `requirements.txt` `>=` bilan, pin yo'q; pillow/moviepy yechimi mo'rt. **Fix:** lock fayl.
- **L4** — `start.sh` bot fonda (`&`) — yiqilsa sezilmaydi. **Fix:** supervisor/alohida process.
- **L5** — Nginx'da xavfsizlik header'lari + rate-limit yo'q. **Fix:** HSTS/XFO/CSP + `limit_req`.
- **L6** — `.env.example`'da placeholder parol; `set_proxy` validatsiyasiz; MD5(sessionid) routing tag; proxy creds tooltip'da ochiq; settings input'lar yopilganda tozalanmaydi (secret DOM'da qoladi).

---

## Ustuvor harakat reja

1. **C4+C5:** `.dockerignore`'ga `*.pem`, SSH key + barcha tirik kalitlarni (Telegram/Groq/Mistral/IG/panel parol) **rotatsiya qiling**.
2. **C1+C2:** Auth fail-closed (`app.py`), Telegram kanal authz (`bot.py`).
3. **C3:** SSRF allowlist (`fetch_media`, `rotate_url`).
4. **H4:** HTTPS + 8000-portni internetdan yopish.
5. **H1/H3/H5:** webhook `compare_digest`, proxy fail-loud, DOM XSS → `textContent`.
6. **H9:** atomik yozish (settings/history).

**Ijobiy (regression bo'lmasin):** git toza · sirlar frontendga `_set:bool` ko'rinishida maskalanadi · settings whitelist (arbitrary key yozib bo'lmaydi) · login akkaunt proxysi orqali · command injection YO'Q (subprocess list-arg) · modem fayllari atomik · Claude `output_config.format` + refusal handling to'g'ri.
