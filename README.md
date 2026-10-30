
# 🚀 Multi-Platform Telegram Media Downloader Bot

A powerful Telegram bot for downloading videos and images from multiple social media platforms.

بوت تيليجرام لتحميل الفيديوهات والصور من مختلف منصات التواصل الاجتماعي.

---

## 🌐 Supported Platforms | المنصات المدعومة

- ▶️ YouTube
- 📸 Instagram
- 🎵 TikTok
- 📘 Facebook
- 🐦 X (Twitter)
- 🎧 SoundCloud
- 🔴 Reddit
- 📌 Pinterest
- 🧵 Threads

*Platform support depends on content availability and platform restrictions.*

---

## ✨ Features | المميزات

- Download videos in the best available quality.
- Download Instagram and TikTok images.
- Support multi-image posts and carousels.
- Preserve original image quality where possible.
- Preserve original post descriptions when available.
- Merge YouTube video and audio using FFmpeg.
- Support multiple simultaneous download requests.
- Automatic temporary file cleanup.
- Error handling and activity logging.
- Railway deployment support.

---

## 🛠️ Technologies | التقنيات المستخدمة

- Python 3.12
- python-telegram-bot 22.8
- yt-dlp
- FFmpeg
- Deno
- Python Dotenv
- Railway

---

## 📁 Project Structure | ملفات المشروع

```text
telegram-video-downloader/
│
├── bot.py
├── requirements.txt
├── Dockerfile
├── README.md
├── .gitignore
│
└── downloads/
```

---

## ⚙️ Installation | التثبيت

### 1. Clone the repository

```bash
git clone https://github.com/tears665-png/telegram-video-downloader.git
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
```

### 4. Run the bot

```bash
python bot.py
```

---

## ☁️ Railway Deployment

This project supports Docker-based deployment on Railway.

Required environment variable:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
```

FFmpeg and Deno are installed automatically through the Dockerfile.

---

## 🎬 YouTube Support

The bot uses yt-dlp to extract available media formats.

FFmpeg is used to merge separate video and audio streams.

Deno and yt-dlp EJS components help with YouTube JavaScript challenges.

Some videos may still require authentication or be unavailable due to platform restrictions.

---

## 📸 Images & Carousels

The bot supports image downloads and multi-image posts where supported by yt-dlp.

Original image files are sent as documents to preserve their quality.

---

## ⚠️ Important Notes

- Private or restricted content may not be downloadable.
- Some platforms may change their access restrictions.
- File size and Telegram upload limits apply.
- YouTube downloads may require valid authentication cookies.
- Cookies must be kept private and must never be uploaded to GitHub.

---

## 🔐 Security

Never publish your Telegram bot token.

Keep `.env` and authentication cookies outside the public repository.

---

## 👨‍💻 Developer

**GitHub:** [tears665-png](https://github.com/tears665-png)

---

## 📜 Disclaimer

This project is intended for personal and educational use.

Users are responsible for respecting copyright, platform terms of service, privacy, and applicable laws when downloading or sharing content.

---

# 🇸🇦 النسخة العربية

## نبذة عن المشروع

بوت تيليجرام لتحميل الفيديوهات والصور من عدة منصات اجتماعية، مع دعم تحميل المنشورات متعددة الصور والفيديوهات ذات الصوت المنفصل.

### أبرز المميزات

- تحميل فيديوهات يوتيوب.
- تحميل صور وفيديوهات إنستغرام.
- تحميل صور وفيديوهات تيك توك.
- دعم Facebook وX.
- دعم المنشورات متعددة الصور.
- الحفاظ على وصف المنشور قدر الإمكان.
- دمج الصوت والفيديو باستخدام FFmpeg.
- معالجة عدة طلبات بالتزامن.
- حذف الملفات المؤقتة تلقائياً.
- تشغيل مستمر عبر Railway.

### ملاحظات

يعتمد نجاح التحميل على توفر المحتوى وإمكانية الوصول إليه من المنصة الأصلية.

قد تتطلب بعض فيديوهات يوتيوب تسجيل الدخول أو ملفات Cookies صالحة.

المشروع قابل للتطوير وإضافة منصات وميزات جديدة مستقبلاً.
