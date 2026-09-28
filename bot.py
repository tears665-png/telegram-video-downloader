import os
import asyncio
import yt_dlp

from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# TELEGRAM BOT TOKEN
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Please set the BOT_TOKEN environment variable."
    )

# Folder for downloaded videos
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# =========================================================
# /start
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! ابعتلي رابط الفيديو وأنا بحاول أحمله وأبعثه إلك."
    )


# =========================================================
# Download video
# =========================================================

def download_video(url):
    output_template = os.path.join(
        DOWNLOAD_DIR,
        "%(title).80s.%(ext)s"
    )

    options = {
        "outtmpl": output_template,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

        # If downloaded format is not MP4, look for the actual file
        if not os.path.exists(filename):
            base = os.path.splitext(filename)[0]

            for file in os.listdir(DOWNLOAD_DIR):
                if file.startswith(os.path.basename(base)):
                    return os.path.join(DOWNLOAD_DIR, file)

        return filename


# =========================================================
# Handle links
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    url = update.message.text.strip()

    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "❌ ابعتلي رابط فيديو صالح."
        )
        return

    status = await update.message.reply_text(
        "⏳ جاري تحميل الفيديو..."
    )

    try:
        # yt-dlp is blocking, so run it in a separate thread
        video_path = await asyncio.to_thread(
            download_video,
            url
        )

        if not os.path.exists(video_path):
            raise Exception("Video file was not found.")

        await status.edit_text(
            "📤 تم التحميل، جاري إرسال الفيديو..."
        )

        with open(video_path, "rb") as video:
            await update.message.reply_video(
                video=video,
                supports_streaming=True
            )

        # Delete downloaded file after sending
        try:
            os.remove(video_path)
        except Exception:
            pass

        await status.delete()

    except Exception as e:
        print("ERROR:", repr(e))

        try:
            await status.edit_text(
                "❌ ما قدرت حمّل هالفيديو.\n"
                "تأكد إن الرابط عام وقابل للوصول."
            )
        except Exception:
            pass


# =========================================================
# MAIN
# =========================================================

def main():
    print("===================================")
    print("VIDEO DOWNLOADER BOT")
    print("Bot is starting...")
    print("===================================")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("BOT IS RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()