
import os
import re
import shutil
import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from contextlib import ExitStack

import yt_dlp
from dotenv import load_dotenv

from telegram import (
    Update,
    InputMediaDocument,
    InputMediaVideo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing!")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 49 * 1024 * 1024
MAX_MEDIA_ITEMS = 10
MAX_CONCURRENT_DOWNLOADS = 3

download_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_DOWNLOADS
)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp"
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov"
}

AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav"
}

ALLOWED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
    "x.com",
    "twitter.com",
    "soundcloud.com",
    "reddit.com",
    "redd.it",
    "pinterest.com",
    "pin.it",
    "threads.net",
)

# ==========================================
# LOGGING
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("DownloaderBot")


# ==========================================
# URL VALIDATION
# ==========================================

def validate_url(url):

    try:
        parsed = urlparse(url.strip())

        if parsed.scheme not in ("http", "https"):
            return False

        host = (parsed.hostname or "").lower()

        return any(
            host == domain or host.endswith("." + domain)
            for domain in ALLOWED_DOMAINS
        )

    except Exception:
        return False


def is_youtube(url):

    host = (urlparse(url).hostname or "").lower()

    return (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
    )


# ==========================================
# YT-DLP DOWNLOAD ENGINE
# ==========================================

def download_media(url, folder):

    youtube = is_youtube(url)

    output_template = str(
        Path(folder) / "%(autonumber)03d_%(id)s.%(ext)s"
    )

    ydl_opts = {

        "outtmpl": output_template,

        # YouTube: best video + best audio
        # Other platforms: best available format
        "format": (
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
            "b[ext=mp4]/b"
            if youtube else
            "best/bestvideo+bestaudio"
        ),

        "merge_output_format": "mp4",

        # Do not download YouTube playlists
        "noplaylist": youtube,

        # Allow Instagram/TikTok carousels
        "playlistend": MAX_MEDIA_ITEMS,

        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,

        "socket_timeout": 30,

        "concurrent_fragment_downloads": 4,

        "continuedl": True,
        "overwrites": True,

        "quiet": True,
        "no_warnings": True,

        "ignoreerrors": False,

        "logger": logger,

        "js_runtimes": {
            "deno": {}
        },

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
            )
        },
    }

    # Optional YouTube cookies file
    cookies_file = os.getenv("YOUTUBE_COOKIES_FILE")

    if cookies_file and os.path.isfile(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

    files = sorted(
        [
            p for p in Path(folder).iterdir()
            if p.is_file()
            and p.suffix.lower() in (
                IMAGE_EXTENSIONS
                | VIDEO_EXTENSIONS
                | AUDIO_EXTENSIONS
            )
            and ".part" not in p.name
        ],
        key=lambda p: p.name
    )

    if not files:
        raise RuntimeError("No downloadable media found.")

    description = (
        info.get("description")
        or info.get("title")
        or ""
    )

    description = description[:1000]

    return files, description


# ==========================================
# TELEGRAM MEDIA SENDER
# ==========================================

async def send_downloaded_media(
    update,
    files,
    description
):

    chat_id = update.effective_chat.id

    # Check file sizes
    valid_files = []

    for file in files:

        size = file.stat().st_size

        if size > MAX_FILE_SIZE:
            logger.warning(
                "File too large: %s (%s bytes)",
                file.name,
                size
            )
            continue

        valid_files.append(file)

    if not valid_files:

        await update.effective_message.reply_text(
            "❌ الملف أكبر من الحد المسموح لإرساله عبر البوت."
        )

        return

    caption_used = False

    # Send image-only albums as documents
    # This preserves the original image files.
    if all(
        f.suffix.lower() in IMAGE_EXTENSIONS
        for f in valid_files
    ):

        for start in range(0, len(valid_files), MAX_MEDIA_ITEMS):

            batch = valid_files[
                start:start + MAX_MEDIA_ITEMS
            ]

            if len(batch) == 1:

                with open(batch[0], "rb") as photo:

                    await update.effective_message.reply_document(
                        document=photo,
                        caption=(
                            description if not caption_used else None
                        )
                    )

                caption_used = True
                continue

            with ExitStack() as stack:

                media = []

                for file in batch:

                    opened = stack.enter_context(
                        open(file, "rb")
                    )

                    media.append(
                        InputMediaDocument(
                            media=opened,
                            caption=(
                                description
                                if not caption_used else None
                            )
                        )
                    )

                    caption_used = True

                await context_bot_send_group(
                    update,
                    media
                )

        return

    # Send video-only albums
    if all(
        f.suffix.lower() in VIDEO_EXTENSIONS
        for f in valid_files
    ):

        for start in range(0, len(valid_files), MAX_MEDIA_ITEMS):

            batch = valid_files[
                start:start + MAX_MEDIA_ITEMS
            ]

            if len(batch) == 1:

                with open(batch[0], "rb") as video:

                    await update.effective_message.reply_video(
                        video=video,
                        caption=(
                            description if not caption_used else None
                        ),
                        supports_streaming=True
                    )

                caption_used = True
                continue

            with ExitStack() as stack:

                media = []

                for file in batch:

                    opened = stack.enter_context(
                        open(file, "rb")
                    )

                    media.append(
                        InputMediaVideo(
                            media=opened,
                            caption=(
                                description
                                if not caption_used else None
                            ),
                            supports_streaming=True
                        )
                    )

                    caption_used = True

                await context_bot_send_group(
                    update,
                    media
                )

        return

    # Mixed media or audio: preserve file order
    for file in valid_files:

        caption = (
            description if not caption_used else None
        )

        with open(file, "rb") as media_file:

            ext = file.suffix.lower()

            if ext in VIDEO_EXTENSIONS:

                await update.effective_message.reply_video(
                    video=media_file,
                    caption=caption,
                    supports_streaming=True
                )

            elif ext in IMAGE_EXTENSIONS:

                await update.effective_message.reply_document(
                    document=media_file,
                    caption=caption
                )

            elif ext in AUDIO_EXTENSIONS:

                await update.effective_message.reply_audio(
                    audio=media_file,
                    caption=caption
                )

            else:

                await update.effective_message.reply_document(
                    document=media_file,
                    caption=caption
                )

        caption_used = True


async def context_bot_send_group(update, media):

    await update.get_bot().send_media_group(
        chat_id=update.effective_chat.id,
        media=media,
        reply_to_message_id=update.effective_message.message_id
    )


# ==========================================
# START COMMAND
# ==========================================

async def start(update, context):

    name = update.effective_user.first_name or "صديقي"

    message = f"""
أهلاً {name}! 👋

أنا بوت تحميل الوسائط.

أرسل رابطاً وسأحاول تنزيل المحتوى وإرساله إليك.

المنصات المدعومة:

▶️ YouTube
📸 Instagram
🎵 TikTok
📘 Facebook
🐦 X / Twitter
🎧 SoundCloud
🔴 Reddit
📌 Pinterest
🧵 Threads

المميزات:

✅ فيديوهات بأفضل جودة متاحة
✅ صور ومنشورات متعددة الصور
✅ الحفاظ على ترتيب الصور
✅ الاحتفاظ بوصف المنشور قدر الإمكان
✅ تنظيف الملفات تلقائياً

أرسل الرابط للبدء 🚀
"""

    await update.message.reply_text(message)


# ==========================================
# DOWNLOAD COMMAND HANDLER
# ==========================================

async def handle_message(update, context):

    message = update.effective_message

    if not message or not message.text:
        return

    url = message.text.strip()

    # Accept a URL even if extra text follows it
    match = re.search(r"https?://\S+", url)

    if not match:
        await message.reply_text(
            "❌ أرسل رابطاً يبدأ بـ http أو https."
        )
        return

    url = match.group(0).rstrip(".,،)")

    if not validate_url(url):

        await message.reply_text(
            "❌ هذا الرابط غير مدعوم أو غير صالح."
        )

        return

    status = await message.reply_text(
        "⏳ استلمت الرابط!\n"
        "جاري تحليل المحتوى وتحميل الوسائط..."
    )

    work_dir = None

    try:

        async with download_semaphore:

            work_dir = tempfile.mkdtemp(
                prefix="download_",
                dir=str(DOWNLOAD_DIR)
            )

            await status.edit_text(
                "⬇️ جاري التحميل...\n"
                "يرجى الانتظار."
            )

            files, description = await asyncio.to_thread(
                download_media,
                url,
                work_dir
            )

            await status.edit_text(
                f"📤 تم تحميل {len(files)} ملف.\n"
                "جاري الإرسال إلى تيليجرام..."
            )

            await send_downloaded_media(
                update,
                files,
                description
            )

            await status.edit_text(
                "✅ انتهى التحميل والإرسال بنجاح!"
            )

    except yt_dlp.utils.DownloadError as error:

        logger.exception("YT-DLP download error")

        error_text = str(error).lower()

        if "sign in" in error_text or "not a bot" in error_text:

            user_error = (
                "⚠️ يوتيوب طلب تسجيل الدخول أو تحققاً إضافياً.\n"
                "قد نحتاج إلى ملف Cookies صالح."
            )

        elif "requested format is not available" in error_text:

            user_error = (
                "⚠️ صيغة الفيديو المطلوبة غير متاحة.\n"
                "يمكن أن تكون المشكلة من صيغ يوتيوب المتاحة."
            )

        else:

            user_error = (
                "❌ تعذر تحميل المحتوى.\n"
                "قد يكون الرابط خاصاً أو غير متاح."
            )

        await status.edit_text(user_error)

    except Exception:

        logger.exception("Unexpected download error")

        await status.edit_text(
            "❌ حدث خطأ أثناء التحميل أو إرسال الملفات.\n"
            "تم تسجيل تفاصيل الخطأ لفحصها."
        )

    finally:

        if work_dir and os.path.exists(work_dir):

            try:

                shutil.rmtree(work_dir)

            except Exception:

                logger.exception(
                    "Temporary directory cleanup failed"
                )


# ==========================================
# ERROR HANDLER
# ==========================================

async def error_handler(update, context):

    logger.error(
        "Telegram application error",
        exc_info=context.error
    )


# ==========================================
# MAIN
# ==========================================

def main():

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(16)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_error_handler(error_handler)

    logger.info("===================================")
    logger.info("VIDEO DOWNLOADER BOT")
    logger.info("BOT IS RUNNING")
    logger.info("===================================")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
