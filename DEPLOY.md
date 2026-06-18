# AWS serverga joylash (Docker)

Bu qo'llanma AWS EC2 (Ubuntu) misolida. Boshqa VPS'larda ham xuddi shunday.

## 1. EC2 Security Group (port ochish)
AWS konsolida instance'ning Security Group'iga **Inbound rule** qo'shing:
- **Port 8000**, manba sifatida — iloji bo'lsa **faqat o'z IP'ingiz** (Type: Custom TCP, Source: My IP).
- Agar domen + HTTPS ishlatsangiz, 80 va 443 ham oching (pastga qarang).

## 2. Serverga ulanish va Docker o'rnatish
```bash
ssh -i kalit.pem ubuntu@<EC2_PUBLIC_IP>

# Docker o'rnatish (Ubuntu)
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
newgrp docker   # yoki qaytadan SSH qiling
```
> Amazon Linux bo'lsa: `sudo dnf install -y docker git && sudo systemctl enable --now docker && sudo usermod -aG docker ec2-user`

## 3. Loyihani klonlash
```bash
git clone https://github.com/<foydalanuvchi>/komment-qiroli.git
cd komment-qiroli
```

## 4. .env yaratish (maxfiy — repo'da yo'q)
```bash
cp .env.example .env
nano .env
```
To'ldiring (eng muhimi):
- `PANEL_PASSWORD=` — **kuchli parol** (panel internetda ochiq bo'ladi!)
- `ANTHROPIC_API_KEY` / `GROQ_API_KEY` / `MISTRAL_API_KEY` — kamida bittasi
  (yoki keyin panel ichidagi Sozlamalardan kiritasiz)

Instagram akkauntlarni panel orqali (sessionid) ulaysiz — .env'ga kerak emas.

## 5. Ishga tushirish
```bash
docker compose up -d --build
```
Tekshirish: `docker compose logs -f` · To'xtatish: `docker compose down`

Panel: **http://<EC2_PUBLIC_IP>:8000**

Yangilash (kod o'zgarsa):
```bash
git pull && docker compose up -d --build
```

Ma'lumotlar (sessiyalar, sozlamalar, tarix) `./data` papkasida saqlanadi va
qayta ishga tushirishda yo'qolmaydi. **`data/`ni zaxiralab turing.**

---

## 6. (Tavsiya) Domen + HTTPS (Nginx + Let's Encrypt)
Panel internetda ochiq bo'lgani uchun HTTPS kuchli tavsiya etiladi.

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```
`/etc/nginx/sites-available/komment` ga:
```nginx
server {
    server_name sizning-domeningiz.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/komment /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d sizning-domeningiz.com   # avtomatik HTTPS
```
So'ng Security Group'da 8000'ni yopib, faqat 80/443 ni qoldiring.

---

## Eslatma
- `PANEL_PASSWORD`siz panelni internetga chiqarmang.
- instagrapi norasmiy — serverdan ko'p akkaunt bilan ishlash ban xavfini oshiradi;
  Sozlamalardagi limit/kechikishlarni ehtiyotkor sozlang.
