# O'z 4G modem pool — IPRoyal o'rniga (BEPUL UZ mobil IP)

Maqsad: IPRoyal'ga pul to'lash o'rniga mini-PC'ga ulangan **o'z 4G modemlaringizdan**
foydalanish. Har modem = bitta UZ mobil IP. Akkauntlar modemlarga sticky taqsimlanadi.

```
bot ──socks5://127.0.0.1:10001──► 3proxy ──(-e 192.168.8.100)──► modem1 ──► UZ mobil IP #1
    ──socks5://127.0.0.1:10002──► 3proxy ──(-e 192.168.9.100)──► modem2 ──► UZ mobil IP #2
```

Tavsiya: **5 akkaunt / 1 modem**. 30 akkaunt ≈ **6 modem**. (Mobil IP minglab odam bilan
ulashilgani uchun 5 ta akkaunt bitta IP'da xavfsiz.)

---

## 1. Apparat
- Mini-PC (Ubuntu/Debian) — bor.
- Quvvatli **USB hub** (modemlar tok talab qiladi).
- 6-8 × USB 4G modem. Tavsiya: **Huawei E3372** (HiLink) — rotation HTTP API bilan oson.
- Har modemga UZ SIM + arzon data tarif (komment/like ~1 MB — kam yetadi).
- Muqobil: eski **Android telefon** → USB-tethering (rotation ADB orqali).

---

## 2. 3proxy o'rnatish (mini-PC)
```bash
sudo apt update && sudo apt install -y 3proxy
# yoki manbadan: https://github.com/3proxy/3proxy
```

---

## 3. ⚠️ Modem subnet konflikti (MUHIM)
Huawei HiLink modemlarning HAMMASI standart `192.168.8.1` beradi → bir nechta ulansa
**to'qnashadi**. Har modemga ALOHIDA subnet bering:

- 1-modem: `192.168.8.x` (standart)
- 2-modem: `192.168.9.x`
- 3-modem: `192.168.10.x` ...

O'zgartirish: modem veb-paneliga kiring (`http://192.168.8.1`) → **Settings → DHCP →
LAN IP** ni `192.168.9.1` ga o'zgartiring. Har modemni **bittalab** ulab sozlang.

Har modem ulangach, host'da o'zining IP'sini ko'ring:
```bash
ip -4 addr | grep 192.168
```
Bu IP (mas. `192.168.9.100`) — modemning **ext_ip**'si (3proxy `-e` shunga bog'laydi).

---

## 4. Modemlarni pool'ga qo'shish
Panel orqali (Modemlar bo'limi → "Avto-aniqlash" → "Qo'shish") yoki CLI bilan:
```bash
python modem_cli.py detect
python modem_cli.py add 192.168.8.100  --label Beeline-1 --rotate huawei --url http://192.168.8.1
python modem_cli.py add 192.168.9.100  --label Ucell-1   --rotate huawei --url http://192.168.9.1
python modem_cli.py list
```

---

## 5. 3proxy config yaratish va ishga tushirish
```bash
python modem_cli.py config          # data/3proxy.cfg yaratadi
3proxy /home/<user>/komment-qiroli/data/3proxy.cfg
```
Avtomatik ishga tushirish uchun **systemd** xizmati (`/etc/systemd/system/3proxy.service`):
```ini
[Unit]
Description=3proxy modem pool
After=network.target
[Service]
ExecStart=/usr/bin/3proxy /home/<user>/komment-qiroli/data/3proxy.cfg
Restart=always
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now 3proxy
```

> Modem qo'shgan/o'chirgan sayin `python modem_cli.py config` ni qayta ishlating va
> `sudo systemctl restart 3proxy` qiling.

---

## 6. Botni local rejimga o'tkazish (.env)
```bash
PROXY_MODE=local          # avto-proxy modemlardan olinadi (IPRoyal emas)
MODEM_PROXY_HOST=127.0.0.1
MODEM_PORT_BASE=10001
```
> `PROXY_MODE=auto` ham bo'ladi — modemlar sozlangan bo'lsa o'zi "local"ga o'tadi.

---

## 7. Docker tarmog'i (bot konteynerda bo'lsa)
Konteyner host'dagi 3proxy (`127.0.0.1`) ni ko'rishi uchun `docker-compose.yml`da
botga **host tarmog'ini** bering:
```yaml
services:
  app:
    network_mode: host        # eng oson — 127.0.0.1 ishlaydi
```
Yoki host tarmog'isiz: `MODEM_PROXY_HOST=172.17.0.1` (docker bridge gateway) qiling va
`modem_pool.gen_3proxy_config()` ichida listen'ni `0.0.0.0` qiling
(`MODEM_3PROXY_LISTEN=0.0.0.0`) — lekin u holda firewall bilan portlarni yoping.

---

## 8. Akkauntlarni modemlarga taqsimlash
```bash
python modem_cli.py assign-all
```
yoki panelda "🔗 Akkauntlarni taqsimlash". Yangi akkaunt qo'shganda avtomatik
balanslangan modemga biriktiriladi (sticky).

---

## 9. IP rotation (xohlasangiz)
- Qo'lda: panelda modem yonidagi **↻**, yoki `python modem_cli.py rotate m1`.
- Avtomatik (mas. har 30 daqiqada): cron yoki bot ichidagi rejaga ulash mumkin.
- Eslatma: rotation IP'ni yangilaydi, lekin akkaunt o'sha modemda qoladi — UZ mobil
  IP barqaror toifada bo'lgani uchun bu xavfsiz.

---

## 10. Tekshirish
```bash
python modem_cli.py ip m1     # m1 orqali tashqi IP — UZ bo'lishi kerak
```
Panelda: akkaunt yonida 🛡 proxy ko'rinadi, "Tekshirish" bossangiz akkaunt nomi qaytadi.

---

## Tejamkorlik
- IPRoyal: ~$5.5-7.3/GB (repost/story tez tugatadi).
- DIY: bir martalik ~$150-200 apparat + ~$15-25/oy SIM. 1-2 oyda o'zini qoplaydi.
- Yetarli GB bo'lgani uchun **Repost/Story qayta yoqsa bo'ladi** (`app.py`:
  `REPOST_STORY_ENABLED = True`).
