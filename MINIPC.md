# Mini-PC (Ubuntu) ga ko'chirish — qo'llanma

Maqsad: Komment Qiroli'ni uy mini-PC'sida 24/7 ishlatish, **uy WiFi IP'sidan (proxysiz)** —
sessiyalar barqaror bo'lishi uchun. Boshqa Ubuntu loyihalariga **halaqit qilmaslik**.

---

## Nega mini-PC + uy IP?
Sessiyalar o'layotgan asosiy sabab — IP mos kelmasligi (login bir IP, bot boshqa IP).
Mini-PC uy WiFi'sida bo'lsa va akkauntga ham shu tarmoqdan kirilsa — **bitta real uy IP** →
Instagram "IP sakradi" demaydi → sessiyalar uzoq yashaydi. Datacenter/proxy emas.

---

## 0. Boshqa loyihalarga halaqit qilmaslik (izolyatsiya)
- **Docker ishlatamiz** → Python paketlari, port, ma'lumotlar to'liq alohida konteynerда.
  Boshqa loyihalarning venv/paketlariga tegmaydi.
- **Alohida port** (default `8090`, band bo'lsa boshqasini bering) → 8000 ni band qilgan
  loyihaga xalal bermaydi. `deploy-minipc.sh` portni avtomatik tekshiradi.
- **Konteyner nomi** `komment-qiroli` — boshqalardan ajralib turadi.
- Hammasi `~/komment-qiroli/data/` ichida — boshqa joyga yozmaydi.

---

## 1. Mini-PC'da tayyorgarlik
```bash
# Docker (yo'q bo'lsa)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Loyihani olish
git clone https://github.com/draconuzb/komment-qiroli.git
cd komment-qiroli
```

## 2. .env yaratish (PROXYSIZ)
```bash
cp .env.example .env
nano .env
```
To'ldiring:
```ini
PANEL_PASSWORD=kuchli-parol
# AI (kamida bittasi) — yoki keyin panel Sozlamalardan
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...        # vision (caption-siz video) uchun

# Telegram (shu yerda bot ishlaydi)
TELEGRAM_BOT_TOKEN=...
ALLOWED_TELEGRAM_IDS=1357885397,8210027116
TELEGRAM_CHANNEL_ID=-1004333923580
BOT_ENABLED=1

# === PROXY: O'CHIQ (uy IP ishlatiladi) ===
PROXY_AUTO=0
```

## 3. Ishga tushirish
```bash
bash deploy-minipc.sh 8090      # yoki bo'sh port
docker logs -f komment-qiroli   # tekshirish
```

## 4. AWS serverdagi botni O'CHIRISH (MUHIM!)
Bitta Telegram token ikki joyda polling qilsa "Conflict" beradi. Mini-PC live bo'lgach:
```bash
# AWS da:
ssh -i bekpro.pem ec2-user@54.160.255.7 'docker rm -f komment-qiroli'
# (yoki AWS .env ga BOT_ENABLED=0 qo'shib qayta yaratib, faqat web qoldirish mumkin)
```

## 5. Masofadan kirish (Tailscale — tavsiya)
Uy WiFi'da statik IP/port-forwarding yo'q. Tailscale eng oson:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
Keyin panel: `http://<mini-pc-tailscale-ip>:8090` — xohlagan joydan (telefon/laptopda ham Tailscale).
Webhook/cron ham shu manzildan ishlaydi.

## 6. Akkauntlarni QAYTA ulash (uy IP'dan)
Eski (AWS/proxy) sessiyalarni ko'chirmang — ular boshqa IP'ga bog'langan.
- Mini-PC paneli orqali akkauntni **qaytadan** ulang (sessionid yoki login+parol).
- Eng yaxshi: akkauntga **shu uy WiFi'dagi** telefon/brauzerdan kiring → sessionid oling →
  panelga joylang. IP bir xil → sessiya uzoq yashaydi.
- Qo'shgach **🩺 Tekshir** va **🔥 Isitish** tugmalaridan foydalaning.

---

## PROXY STRATEGIYASI (mini-PC uchun "aqlli" yondashuv)

**Asosiy: proxysiz uy IP** (`PROXY_AUTO=0`). Tekin, eng barqaror. Lekin bitta uy IP'ga
~5-15 akkaunt xavfsiz (undan ko'pi "ferma" ko'rinadi). Shuning uchun bosqichli:

| Daraja | IP manbai | Narx | Nechta akkaunt |
|---|---|---|---|
| 1 (default) | **Uy WiFi IP** (proxysiz) | tekin | ~5-15 |
| 2 (ko'paytirish) | **4G modemlar** (modem_pool) — har modem alohida UZ mobil IP | SIM trafik | har modemga ~5 |
| 3 (zaxira/overflow) | IPRoyal residential (`PROXY_AUTO=1` yoki akkauntga qo'lda) | $/GB | cheksiz |

**Qanday ishlaydi (kod allaqachon qo'llab-quvvatlaydi):**
- `PROXY_AUTO=0` → proxy biriktirilmagan akkaunt **uy IP**'dan ishlaydi.
- Akkauntga **qo'lda proxy** bersangiz (panel 🛡 yoki modem_pool taqsimoti) — o'sha akkaunt
  shu IP'dan ketadi. Ya'ni: ko'pchilik uy IP'da, ba'zilari modem/proxy'da — **aralash**.
- **Modem pool**: mini-PC'ga 4G modem ulasangiz, panel "Modemlar" bo'limidan qo'shib,
  "Akkauntlarni taqsimlash" bilan har modemga akkaunt biriktirasiz → tekin mobil UZ IP'lar.

**Tavsiya:** avval 5-10 akkauntni uy IP'da (proxysiz) sinab ko'ring. Barqaror ishlasa,
ko'paytirish kerak bo'lganda 4G modem qo'shasiz. Pulli proxy faqat oxirgi chora.
