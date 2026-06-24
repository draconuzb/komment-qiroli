#!/bin/sh
# Telegram botni (agar token bo'lsa) fonда, web-panelni asosiy jarayon sifatida ishga tushiradi.
set -e

if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  echo "Telegram bot ishga tushirilmoqda (fonда)..."
  python bot.py &
fi

exec uvicorn app:app --host 0.0.0.0 --port 8000
