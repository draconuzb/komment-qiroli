#!/bin/sh
# Web-panel + (yoqilgan bo'lsa) Telegram botni ishga tushiradi.
# PORT — uvicorn porti (default 8000). BOT_ENABLED=0 bo'lsa bot ishga tushmaydi
# (bir token ikkita joyda polling qilsa Telegram "Conflict" beradi — shuning uchun
#  faqat BITTA muhitda bot yoqilsin).
set -e
PORT="${PORT:-8000}"

if [ "${BOT_ENABLED:-1}" != "0" ] && [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  echo "Telegram bot ishga tushirilmoqda (fonда, avto-restart bilan)..."
  # Bot o'lса, 5 soniyaдан keyin o'zi qayta yonadi (hech qachon o'lik qolmaydi).
  ( while true; do python bot.py; echo "Bot to'xtadi — 5s dan keyin qayta..."; sleep 5; done ) &
else
  echo "Telegram bot O'CHIQ (BOT_ENABLED=0 yoki token yo'q)."
fi

exec uvicorn app:app --host 0.0.0.0 --port "$PORT"
