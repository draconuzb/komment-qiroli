# Komment Qiroli — Instagram Guerilla Marketing Bot

Telegram bot orqali Instagram videolariga Claude yordamida 3 xil "olovli" komment
variantini yaratadi va tanlanganini avtomatik joylaydi.

## Oqim

1. Telegram'ga Instagram Reel havolasini yuborasiz.
2. Bot `instagrapi` orqali videoning matnini (caption) o'qiydi.
3. Claude (`claude-opus-4-8`) 3 xil uslubda komment qaytaradi:
   - 😄 **Yumor/Sarkazm**
   - 🧠 **Aqlli** (kutilmagan burchak)
   - 🔥 **Bahsli** (provokatsion)
4. Bot 3 variantni inline tugma qilib chiqaradi.
5. Tugmani bossangiz — bot kommentni Instagramga joylaydi.

## ⚠️ Ogohlantirish

`instagrapi` — **norasmiy** kutubxona va Instagram qoidalariga (ToS) ziddir.
Instagram avtomatlashtirishni aniqlab, akkauntni vaqtincha yoki butunlay
**bloklashi mumkin**. Kodga himoyalar qo'shilgan, lekin xavfni butunlay yo'qotmaydi:

- Sessiya faylga saqlanadi (`IG_SESSION_FILE`) — har safar login qilinmaydi.
- Kommentlar orasida tasodifiy kechikish (`RANDOM_DELAY_*`) va minimal interval
  (`MIN_SECONDS_BETWEEN_COMMENTS`).
- Kunlik limit (`MAX_COMMENTS_PER_DAY`).
- Human-in-the-loop: komment faqat siz tugmani bosganda joylanadi.

**Tavsiya:** asosiy akkaunt emas, alohida/zaxira akkauntdan foydalaning.
Hammasi o'z mas'uliyatingiz ostida.

## O'rnatish

```bash
cd D:\projects\automation_insta
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # keyin .env ni to'ldiring
```

`.env` faylida quyidagilarni to'ldiring:
- `TELEGRAM_BOT_TOKEN` — @BotFather'dan
- `ALLOWED_TELEGRAM_IDS` — sizning Telegram ID'ingiz (@userinfobot)
- `ANTHROPIC_API_KEY` — console.anthropic.com'dan
- `IG_USERNAME`, `IG_PASSWORD` — Instagram login

## Ishga tushirish

Ikki xil interfeys bor — ikkalasi bir xil yadroni (`claude_client`, `instagram_client`) ishlatadi.

### 1) Web-panel (tavsiya etiladi)

```bash
python app.py
```
Brauzerda oching: **http://127.0.0.1:8000**

`.env`da `PANEL_PASSWORD` o'rnatilgan bo'lsa, panel parol so'raydi. Panelda:
- havola/mavzu kiritasiz → 3 ta variant kartochka ko'rinishida chiqadi,
- har birini **Nusxalash** yoki **Joylash** tugmasi bilan boshqarasiz,
- yuqorida Instagram akkaunt, model va **kunlik limit** ko'rsatkichi turadi,
- pastda joylangan kommentlar **tarixi** ko'rinadi.

### 2) Telegram bot

```bash
python bot.py
```
Telegram'da botingizga `/start` yozing, keyin Reel havolasini yuboring.

## Eslatmalar

- Birinchi Instagram login'da challenge/2FA so'ralishi mumkin — terminal orqali
  hal qilinadi. Muvaffaqiyatli login'dan keyin sessiya `ig_session.json`'ga
  saqlanadi.
- Arzonroq/tezroq model uchun `.env`da `CLAUDE_MODEL=claude-sonnet-4-6` yoki
  `claude-haiku-4-5` qo'ying.
- Kunlik hisoblagich `daily_counter.json`'da saqlanadi.

## Fayllar

| Fayl | Vazifasi |
|------|----------|
| `app.py` | Web-panel (FastAPI) — REST API + frontend serveri |
| `static/` | Panel interfeysi (`index.html`, `style.css`, `app.js`) |
| `history.py` | Joylangan kommentlar tarixi |
| `bot.py` | Telegram bot, inline tugmalar, asosiy oqim |
| `claude_client.py` | Claude API — 3 ta komment JSON formatda |
| `instagram_client.py` | Instagram login, caption olish, komment joylash + rate-limit |
| `prompts.py` | System/user promptlar va JSON sxema |
| `config.py` | `.env` sozlamalari |
