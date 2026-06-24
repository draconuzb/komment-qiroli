FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data

# ffmpeg — video/reel repost uchun (instagrapi + moviepy)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# moviepy'ni alohida o'rnatamiz: instagrapi pillow>=12.2 talab qiladi, moviepy 2.x
# esa pillow<12 ga pin qo'yadi (qattiq konflikt). Amalda moviepy 2.x pillow 12 bilan
# ishlaydi, shu sabab moviepy'ni --no-deps bilan, qolgan bog'liqliklarini qo'lda o'rnatamiz.
RUN pip install --no-cache-dir --no-deps "moviepy>=2.1.2,<3" \
    && pip install --no-cache-dir "imageio>=2.5,<3" "imageio_ffmpeg>=0.2.0" \
       "proglog<=1.0.0" "decorator>=4.0.2,<6.0" "numpy>=1.25.0"

COPY . .

EXPOSE 8000

# Web-panel + (token bo'lsa) Telegram bot birga ishga tushadi.
CMD ["sh", "start.sh"]
