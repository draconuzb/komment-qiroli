#!/usr/bin/env bash
# Komment Qiroli'ni mini-PC (Ubuntu) ga Docker bilan, BOSHQA loyihalarga halaqit bermay joylash.
# Izolyatsiya: alohida konteyner + alohida port + alohida data/ volume.
#
# Ishlatish:   bash deploy-minipc.sh [PORT]
# Misol:       bash deploy-minipc.sh 8090
set -euo pipefail

PORT="${1:-8090}"            # boshqa loyihalar 8000 ni band qilgan bo'lishi mumkin — 8090 default
NAME="komment-qiroli"
cd "$(dirname "$0")"

# --- Tekshiruvlar ---
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker yo'q. O'rnatish:  curl -fsSL https://get.docker.com | sh  &&  sudo usermod -aG docker \$USER"
  exit 1
fi
if [ ! -f .env ]; then
  echo "❌ .env yo'q. Avval:  cp .env.example .env  va to'ldiring (PROXY_AUTO=0)."
  exit 1
fi

# Eski konteynerni avval o'chiramiz (o'z portimizni ozod qilsin — re-deploy uchun).
echo "♻️  Eski konteyner (bo'lsa) o'chirilmoqda..."
docker rm -f "$NAME" 2>/dev/null || true

# Endi port BOSHQA narsa (boshqa loyiha) tomonidan band emasligini tekshiramiz.
if command -v ss >/dev/null 2>&1 && ss -ltn "( sport = :$PORT )" | grep -q ":$PORT"; then
  echo "❌ $PORT porti boshqa narsa tomonidan band. Boshqa port bering:  bash deploy-minipc.sh 8091"
  exit 1
fi

echo "🔨 Image qurilmoqda ($NAME)..."
# --network=host: build ichida internet (apt/pip) host DNS orqali ishlasin
# (Docker daemon DNS muammosini chetlab o'tadi, daemon'ni qayta ishga tushirmaydi).
docker build --network=host -t "$NAME" .

echo "🚀 Ishga tushirilmoqda — port $PORT, proxysiz (uy IP), bot yoqiq..."
docker run -d --name "$NAME" --restart unless-stopped \
  -p "${PORT}:8000" \
  --env-file .env \
  -e DATA_DIR=/app/data \
  -e PORT=8000 \
  -e BOT_ENABLED=1 \
  -v "$PWD/data:/app/data" \
  "$NAME"

sleep 3
echo
echo "✅ Tayyor."
echo "   Panel:        http://<mini-pc-ip>:$PORT   (Tailscale orqali masofadan)"
echo "   Holat:        docker ps --filter name=$NAME"
echo "   Loglar:       docker logs -f $NAME"
echo
echo "⚠️  Telegram bot endi shu yerda ishlaydi — AWS serverdagi botni O'CHIRING"
echo "    (aks holda ikkita polling Telegram 'Conflict' beradi):"
echo "      ssh ... 'docker rm -f komment-qiroli'   # yoki AWS .env da BOT_ENABLED=0 qilib qayta yarating"
