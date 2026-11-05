# استخدام نسخة Python مستقرة وخفيفة
FROM python:3.11-slim

# ضبط متغيرات البيئة لمنع إنشاء ملفات pyc وتحديث المخرجات فوراً
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# تثبيت الحزم والمكتبات الأساسية للمزيج والصوت/الفيديو والشهادات الأمنية
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    git \
    build-essential \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# إنشاء مجلد العمل
WORKDIR /app

# نسخ ملف متطلبات المكتبات وتثبيتها أولاً لاستغلال Caching في Docker
COPY requirements.txt .

# تثبيت وتحديث مكتبات البايثون، وخاصة yt-dlp للحصول على أحدث إصدار دائماً
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade yt-dlp

# نسخ باقي كود البوت
COPY . .

# إنشاء مجلد مؤقت لتنزيل الفيديوهات ومجلد للكوكيز لتفادي مشكلة الصلاحيات
RUN mkdir -p /app/downloads /app/cookies && chmod -R 777 /app/downloads /app/cookies

# تشغيل البوت
CMD ["python", "bot.py"]
