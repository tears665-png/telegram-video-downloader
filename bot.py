import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from dotenv import load_dotenv

from telegram import InputMediaPhoto, InputMediaVideo, Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ============================================================
# 1. SETTINGS
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing. Add BOT_TOKEN to Railway Variables."
    )

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(49 * 1024 * 1024)))
MAX_MEDIA_ITEMS = int(os.getenv("MAX_MEDIA_ITEMS", "10"))
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))

YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. LOGGING
# ============================================================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("telegram-downloader")


# ============================================================
# 3. SUPPORTED PLATFORMS
# ============================================================

ALLOWED_DOMAINS = {
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
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif"
}

VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".webm", ".mkv"
}

AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"
}

URL_PATTERN = re.compile(
    r"https?://[^\s<>\]\[()\"']+",
    re.IGNORECASE
)

download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


# ============================================================
# 4. URL VALIDATION
# ============================================================

def extract_url(text):
    match = URL_PATTERN.search(text or "")

    if not match:
        return None

    return match.group(0).rstrip(".,!?؛،)")


def validate_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return False

        if not parsed.hostname:
            return False

        host = parsed.hostname.lower().removeprefix("www.")

        for domain in ALLOWED_DOMAINS:
            if host == domain or host.endswith("." + domain):
                return True

        return False

    except Exception:
        return False


def is_youtube(url):
    host = (urlparse(url).hostname or "").lower()
    host = host.removeprefix("www.")

    return (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
    )


# ============================================================
# 5. YT-DLP CONFIGURATION
# ============================================================

def get_ydl_options(folder, url):

    if is_youtube(url):

        # مرن: لا يفرض امتداداً قد لا يكون متوفراً
        format_selector = (
            "bv*[height<=1080]+ba/"
            "b[height<=1080]/"
            "bv*+ba/b"
        )

    else:

        # أفضل فيديو وصوت متاحين، أو أفضل صيغة مفردة
        format_selector = "bestvideo*+bestaudio/best"

    options = {

        "outtmpl": str(
            folder / "%(autonumber)03d_%(id)s.%(ext)s"
        ),

        "format": format_selector,

        # يحتاج FFmpeg الموجود في Dockerfile
        "merge_output_format": "mp4",

        # يسمح باستخراج الألبومات والمنشورات متعددة العناصر
        "noplaylist": False,
        "playlistend": MAX_MEDIA_ITEMS,

        "ignoreerrors": False,

        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "file_access_retries": 2,

        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,

        "continuedl": True,
        "overwrites": True,

        "quiet": True,
        "no_warnings": True,

        "restrictfilenames": True,
        "windowsfilenames": True,

        # Deno هو محرك JavaScript الذي ثبّتناه في Dockerfile
        "js_runtimes": {
            "deno": {}
        },

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            )
        },

        "logger": logger,
    }

    # Cookies اختيارية ليوتيوب فقط
    if is_youtube(url) and YOUTUBE_COOKIES_FILE:

        cookie_path = Path(YOUTUBE_COOKIES_FILE)

        if cookie_path.is_file():
            options["cookiefile"] = str(cookie_path)
            logger.info("YouTube cookies file found and enabled.")

        else:
            logger.warning(
                "YouTube cookies path was configured, but file was not found."
            )

    return options


# ============================================================
# 6. FILE DETECTION
# ============================================================

def get_media_kind(path):

    extension = path.suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        return "photo"

    if extension in VIDEO_EXTENSIONS:
        return "video"

    if extension in AUDIO_EXTENSIONS:
        return "audio"

    return "document"


def find_downloaded_files(folder):

    supported_extensions = (
        IMAGE_EXTENSIONS
        | VIDEO_EXTENSIONS
        | AUDIO_EXTENSIONS
    )

    downloaded = []

    for path in folder.iterdir():

        if not path.is_file():
            continue

        if path.suffix.lower() not in supported_extensions:
            continue

        if path.stat().st_size <= 0:
            continue

        downloaded.append(path)

    return sorted(
        downloaded,
        key=lambda item: item.name.lower()
    )


def get_description(info):

    description = (
        info.get("description")
        or info.get("title")
        or "Downloaded media"
    )

    return str(description).strip()[:900]


# ============================================================
# 7. DOWNLOAD FUNCTION
# ============================================================

def download_media_sync(url, folder):

    options = get_ydl_options(folder, url)

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

    if not info:
        raise RuntimeError(
            "The website did not return downloadable media."
        )

    description = get_description(info)

    downloaded_files = find_downloaded_files(folder)

    # في حال كان الرابط منشوراً متعدد العناصر
    if info.get("entries") and not downloaded_files:

        for entry in info["entries"]:

            if entry:
                description = get_description(entry)

            downloaded_files = find_downloaded_files(folder)

            if downloaded_files:
                break

    downloaded_files = downloaded_files[:MAX_MEDIA_ITEMS]

    return downloaded_files, description


# ============================================================
# 8. SEND SINGLE FILE
# ============================================================

async def send_single_file(message, path, caption=None):

    media_kind = get_media_kind(path)

    with path.open("rb") as file:

        if media_kind == "photo":

            await message.reply_photo(
                photo=file,
                caption=caption
            )

        elif media_kind == "video":

            await message.reply_video(
                video=file,
                caption=caption,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30
            )

        elif media_kind == "audio":

            await message.reply_audio(
                audio=file,
                caption=caption
            )

        else:

            await message.reply_document(
                document=file,
                caption=caption
            )


# ============================================================
# 9. SEND MEDIA GROUPS
# ============================================================

async def send_downloaded_media(message, files, description):

    ready_files = []
    oversized_files = 0

    for path in files:

        try:
            file_size = path.stat().st_size

        except OSError:
            continue

        if file_size > MAX_FILE_SIZE:
            oversized_files += 1
            continue

        ready_files.append(path)

    if not ready_files:
        return 0, oversized_files

    sent_count = 0
    index = 0

    while index < len(ready_files):

        current = ready_files[index]
        current_kind = get_media_kind(current)

        # تجميع الصور والفيديوهات المتتالية في ألبوم
        if current_kind in {"photo", "video"}:

            group = []

            while (
                index < len(ready_files)
                and len(group) < 10
                and get_media_kind(ready_files[index])
                in {"photo", "video"}
            ):

                group.append(ready_files[index])
                index += 1

            # Telegram يحتاج عنصرين على الأقل للألبوم
            if len(group) >= 2:

                media = []
                opened_files = []

                try:

                    for position, item in enumerate(group):

                        file_handle = item.open("rb")
                        opened_files.append(file_handle)

                        caption = (
                            description[:900]
                            if position == 0
                            else None
                        )

                        if get_media_kind(item) == "photo":

                            media.append(
                                InputMediaPhoto(
                                    media=file_handle,
                                    caption=caption
                                )
                            )

                        else:

                            media.append(
                                InputMediaVideo(
                                    media=file_handle,
                                    caption=caption,
                                    supports_streaming=True
                                )
                            )

                    await message.reply_media_group(
                        media=media,
                        read_timeout=180,
                        write_timeout=180
                    )

                    sent_count += len(group)

                finally:

                    for file_handle in opened_files:
                        file_handle.close()

            else:

                await send_single_file(
                    message,
                    group[0],
                    description[:900]
                )

                sent_count += 1

        else:

            await send_single_file(
                message,
                current,
                description[:900]
            )

            sent_count += 1
            index += 1

    return sent_count, oversized_files


# ============================================================
# 10. TELEGRAM COMMANDS
# ============================================================

async def start_command(update, context):

    message = update.effective_message

    if not message:
        return

    await message.reply_text(
        "أهلاً بك في بوت تحميل الوسائط! 👋\n\n"

        "أرسل رابطاً عاماً من إحدى المنصات التالية:\n\n"

        "• YouTube\n"
        "• Instagram\n"
        "• TikTok\n"
        "• Facebook\n"
        "• X / Twitter\n"
        "• SoundCloud\n"
        "• Reddit\n"
        "• Pinterest\n"
        "• Threads\n\n"

        "يمكنني محاولة تنزيل الفيديوهات والصور "
        "والمنشورات متعددة العناصر.\n\n"

        "أرسل الرابط وابدأ!"
    )


async def help_command(update, context):

    message = update.effective_message

    if not message:
        return

    await message.reply_text(
        "طريقة الاستخدام:\n\n"
        "1. انسخ رابط الفيديو أو المنشور.\n"
        "2. أرسله إلى البوت.\n"
        "3. انتظر حتى ينتهي التنزيل.\n\n"
        "ملاحظة: الروابط الخاصة أو التي تتطلب تسجيل دخول "
        "قد لا تعمل."
    )


# ============================================================
# 11. ERROR MESSAGES
# ============================================================

def get_friendly_error(error, url):

    error_text = str(error).lower()

    if is_youtube(url):

        if any(
            word in error_text
            for word in (
                "sign in",
                "not a bot",
                "cookies",
                "confirm you're"
            )
        ):

            return (
                "⚠️ يوتيوب طلب تسجيل الدخول أو تحققاً إضافياً.\n\n"
                "قد نحتاج إلى Cookies صالحة، "
                "لكن لا يوجد ضمان أن ذلك سيحل المشكلة."
            )

        if "requested format is not available" in error_text:

            return (
                "⚠️ لم أتمكن من إيجاد صيغة مناسبة لهذا الفيديو.\n"
                "جرّب رابطاً آخر أو أعد المحاولة لاحقاً."
            )

        if "po token" in error_text:

            return (
                "⚠️ يوتيوب يطلب تحققاً إضافياً (PO Token) "
                "لهذا الفيديو."
            )

    if "ffmpeg" in error_text:

        return (
            "⚠️ حدثت مشكلة أثناء دمج الصوت والفيديو.\n"
            "يجب التأكد من تثبيت FFmpeg في نسخة Docker."
        )

    if any(
        word in error_text
        for word in ("private", "login", "authentication")
    ):

        return (
            "⚠️ يبدو أن هذا المحتوى خاص أو يتطلب تسجيل الدخول."
        )

    if "unsupported url" in error_text:

        return "⚠️ هذا الرابط غير مدعوم حالياً."

    if "timed out" in error_text or "timeout" in error_text:

        return "⚠️ استغرق التنزيل وقتاً طويلاً. حاول مرة أخرى."

    return (
        "❌ لم أتمكن من تنزيل الرابط.\n"
        "قد يكون الرابط غير متاح أو أن المنصة منعت التنزيل."
    )


# ============================================================
# 12. MAIN MESSAGE HANDLER
# ============================================================

async def handle_message(update, context):

    message = update.effective_message

    if not message or not message.text:
        return

    url = extract_url(message.text)

    if not url:

        await message.reply_text(
            "أرسل رابطاً صحيحاً يبدأ بـ http:// أو https://"
        )

        return

    if not validate_url(url):

        await message.reply_text(
            "⚠️ الرابط غير صالح أو أن المنصة غير مدعومة."
        )

        return

    status_message = await message.reply_text(
        "⏳ وصل الرابط!\n"
        "جارٍ فحصه وتحضير الملفات..."
    )

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    try:

        async with download_semaphore:

            with tempfile.TemporaryDirectory(
                prefix="telegram_download_"
            ) as temporary_folder:

                folder = Path(temporary_folder)

                await status_message.edit_text(
                    "⬇️ جارٍ تنزيل الوسائط...\n"
                    "قد يستغرق الأمر بعض الوقت."
                )

                # لا نستخدم wait_for حول to_thread حتى لا نحذف
                # مجلد الملفات بينما خيط التنزيل ما زال يعمل.
                downloaded_files, description = await asyncio.to_thread(
                    download_media_sync,
                    url,
                    folder
                )

                if not downloaded_files:

                    raise RuntimeError(
                        "No downloadable media was found."
                    )

                await status_message.edit_text(
                    "📤 اكتمل التنزيل!\n"
                    "جارٍ إرسال الملفات إليك..."
                )

                sent_count, oversized_count = await send_downloaded_media(
                    message,
                    downloaded_files,
                    description
                )

                if sent_count == 0 and oversized_count:

                    await status_message.edit_text(
                        "⚠️ تم تنزيل الملفات، لكن حجمها أكبر "
                        "من الحد المسموح لإرسالها."
                    )

                elif sent_count > 0:

                    result = (
                        f"✅ اكتمل التنزيل والإرسال!\n"
                        f"عدد الملفات: {sent_count}"
                    )

                    if oversized_count:

                        result += (
                            f"\n⚠️ تم تجاوز {oversized_count} "
                            "ملف بسبب الحجم."
                        )

                    await status_message.edit_text(result)

                else:

                    await status_message.edit_text(
                        "❌ لم أجد ملفات قابلة للإرسال."
                    )

    except Exception as error:

        logger.exception(
            "Download failed for URL: %s",
            url
        )

        try:

            await status_message.edit_text(
                get_friendly_error(error, url)
            )

        except Exception:

            await message.reply_text(
                get_friendly_error(error, url)
            )


# ============================================================
# 13. GLOBAL ERROR HANDLER
# ============================================================

async def error_handler(update, context):

    logger.error(
        "Unhandled Telegram error: %s",
        context.error,
        exc_info=context.error
    )


# ============================================================
# 14. START BOT
# ============================================================

def main():

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(8)
        .connection_pool_size(16)
        .pool_timeout(30)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    application.add_error_handler(error_handler)

    logger.info("====================================")
    logger.info("TELEGRAM DOWNLOADER BOT")
    logger.info("BOT IS STARTING...")
    logger.info("====================================")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
