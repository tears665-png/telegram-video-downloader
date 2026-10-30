import os
import re
import shutil
import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from dotenv import load_dotenv

from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in Railway Variables or .env")

DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_DIR", BASE_DIR / "downloads"))
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# Telegram Bot API upload limit can vary by method/platform.
# Keep a safety margin rather than attempting very large uploads.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "49")) * 1024 * 1024
MAX_ALBUM_ITEMS = 10
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("video-downloader")

download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


# =========================================================
# URL / FILE HELPERS
# =========================================================

def clean_url(text: str) -> str:
    """Accept a plain URL or a message containing one URL."""
    match = re.search(r"https?://\S+", text or "")
    if not match:
        return ""
    return match.group(0).rstrip(").,]}>\"'")


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w.\- ]+", "_", value or "media")
    value = value.strip(" ._")
    return (value or "media")[:90]


def flatten_entries(info: dict) -> list:
    """Return individual media entries from playlist/carousel results."""
    if not isinstance(info, dict):
        return []

    entries = info.get("entries")
    if entries:
        result = []
        for entry in entries:
            if not entry:
                continue
            if entry.get("entries"):
                result.extend(flatten_entries(entry))
            else:
                result.append(entry)
        return result

    return [info]


def candidate_paths(info: dict, workdir: Path) -> list[Path]:
    """Find downloaded files reported by yt-dlp, including post-processed files."""
    found = []

    def add(value):
        if not value:
            return
        try:
            p = Path(value)
            if not p.is_absolute():
                p = workdir / p
            if p.is_file() and p not in found:
                found.append(p)
        except (TypeError, ValueError, OSError):
            pass

    def inspect(item):
        if not isinstance(item, dict):
            return
        add(item.get("filepath"))
        add(item.get("_filename"))
        add(item.get("filename"))
        for requested in item.get("requested_downloads") or []:
            add(requested.get("filepath"))
            add(requested.get("_filename"))

    inspect(info)
    for entry in flatten_entries(info):
        inspect(entry)

    # Fallback: yt-dlp may have used a post-processed filename.
    if not found:
        for p in workdir.iterdir():
            if p.is_file() and p.suffix.lower() not in {".json", ".part", ".ytdl"}:
                found.append(p)

    # Stable order, no duplicate paths.
    return sorted(set(found), key=lambda p: p.name.lower())


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return "photo"
    if ext in {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}:
        return "video"
    if ext in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}:
        return "audio"
    return "document"


def choose_download_options(workdir: Path) -> dict:
    # Prefer MP4-compatible video. If separate streams are required,
    # FFmpeg (installed on Railway) merges them into MP4 where possible.
    return {
        "outtmpl": str(workdir / "%(autonumber)03d_%(title).70s.%(ext)s"),
        "format": (
            "best[ext=mp4][protocol^=https]/"
            "best[ext=mp4]/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best"
        ),
        "merge_output_format": "mp4",
        "noplaylist": False,  # Needed for Instagram/TikTok carousels.
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "continuedl": True,
        "overwrites": True,
        "windowsfilenames": True,
        "restrictfilenames": True,
        "writethumbnail": False,
        "writeinfojson": False,
        "extractor_retries": 2,
    }


def download_media(url: str, workdir: Path) -> tuple[list[Path], dict]:
    """Download one URL and return the media files yt-dlp created."""
    options = choose_download_options(workdir)

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

        if not info:
            raise RuntimeError("The extractor did not return media information.")

        files = candidate_paths(info, workdir)
        # Include any files created even if the extractor didn't report paths.
        for p in workdir.iterdir():
            if p.is_file() and p.suffix.lower() not in {
                ".json", ".part", ".ytdl", ".description", ".vtt", ".srt"
            }:
                if p not in files:
                    files.append(p)

        files = sorted(
            [p for p in set(files) if p.is_file()],
            key=lambda p: p.name.lower()
        )
        if not files:
            raise RuntimeError(
                "No downloadable media file was produced. "
                "The post may be private, restricted, or unsupported."
            )

        title = info.get("title") or "Downloaded media"
        return files, {"title": title, "extractor": info.get("extractor_key", "")}


# =========================================================
# TELEGRAM SENDING
# =========================================================

async def send_one(chat, path: Path, caption: str | None = None):
    kind = classify_file(path)
    size = path.stat().st_size

    if size > MAX_UPLOAD_BYTES:
        await chat.send_message(
            f"⚠️ الملف أكبر من الحد المسموح للإرسال عبر البوت "
            f"({MAX_UPLOAD_BYTES // (1024 * 1024)} MB): {path.name}"
        )
        return

    with path.open("rb") as file_obj:
        if kind == "photo":
            await chat.send_photo(photo=file_obj, caption=caption)
        elif kind == "video":
            await chat.send_video(
                video=file_obj,
                caption=caption,
                supports_streaming=True,
            )
        elif kind == "audio":
            await chat.send_audio(audio=file_obj, caption=caption)
        else:
            await chat.send_document(document=file_obj, caption=caption)


async def send_album(chat, files: list[Path], title: str):
    # Telegram media groups accept 2–10 items. Single files are sent normally.
    # Audio and generic documents are sent separately because album types are restricted.
    album_files = [
        p for p in files
        if classify_file(p) in {"photo", "video"}
        and p.stat().st_size <= MAX_UPLOAD_BYTES
    ]
    other_files = [
        p for p in files
        if p not in album_files
    ]

    if len(album_files) == 1:
        await send_one(chat, album_files[0], caption=title[:900])
    elif len(album_files) >= 2:
        for start in range(0, len(album_files), MAX_ALBUM_ITEMS):
            chunk = album_files[start:start + MAX_ALBUM_ITEMS]

            # Telegram requires at least two items in a media group.
            if len(chunk) == 1:
                await send_one(chat, chunk[0])
                continue

            media = []
            opened_files = []
            try:
                for index, path in enumerate(chunk):
                    file_obj = path.open("rb")
                    opened_files.append(file_obj)
                    caption = title[:900] if start == 0 and index == 0 else None
                    if classify_file(path) == "photo":
                        media.append(InputMediaPhoto(media=file_obj, caption=caption))
                    else:
                        media.append(
                            InputMediaVideo(
                                media=file_obj,
                                caption=caption,
                                supports_streaming=True,
                            )
                        )
                await chat.send_media_group(media=media)
            finally:
                for file_obj in opened_files:
                    file_obj.close()

    for path in other_files:
        await send_one(chat, path)


# =========================================================
# COMMANDS AND MESSAGE HANDLER
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 أهلاً فيك!\n"
        "ابعت رابط منشور أو فيديو، وأنا بحاول أحمل الصور أو الفيديو أو الصوت "
        "وأبعته إلك.\n\n"
        "📸 المنشورات متعددة الصور بتوصلك كألبوم واحد."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "طريقة الاستخدام:\n"
        "1) انسخ رابط المنشور العام.\n"
        "2) أرسله هون.\n"
        "3) انتظر التحميل والإرسال.\n\n"
        "ملاحظة: الروابط الخاصة أو التي تتطلب تسجيل دخول قد لا تعمل، "
        "وبعض المنصات تفرض قيوداً على التحميل."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    url = clean_url(message.text)
    if not url:
        await message.reply_text("❌ ما لقيت رابط صالح. ابعت رابط يبدأ بـ http أو https.")
        return

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        await message.reply_text("❌ الرابط غير صالح.")
        return

    status = await message.reply_text("⏳ وصل الرابط، جاري فحص المنشور وتحميل الوسائط...")

    # A separate temporary folder per request prevents filename collisions
    # when several users submit links at the same time.
    with tempfile.TemporaryDirectory(
        prefix="request_",
        dir=str(DOWNLOAD_ROOT)
    ) as temp_dir:
        workdir = Path(temp_dir)

        try:
            async with download_semaphore:
                await context.bot.send_chat_action(
                    chat_id=message.chat_id,
                    action=ChatAction.TYPING,
                )
                files, details = await asyncio.to_thread(
                    download_media, url, workdir
                )

            await status.edit_text("📤 اكتمل التحميل، جاري إرسال الملفات...")
            await send_album(
                message.chat,
                files,
                details.get("title") or "تم التحميل بنجاح",
            )
            await status.delete()

        except Exception as exc:
            logger.exception("Download/send failed for %s", url)
            user_error = (
                "❌ ما قدرت أحمل هالرابط.\n\n"
                "ممكن يكون المنشور خاص، أو يحتاج تسجيل دخول، أو المنصة "
                "مانعة الوصول، أو نوع المحتوى غير مدعوم حالياً.\n"
                "جرّب رابطاً عاماً آخر."
            )
            try:
                await status.edit_text(user_error)
            except Exception:
                await message.reply_text(user_error)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled Telegram update error", exc_info=context.error)


# =========================================================
# MAIN
# =========================================================

def main():
    logger.info("Starting Telegram media downloader...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)

    logger.info("BOT IS RUNNING")
    # Run exactly one polling instance. Stop local/Pydroid copies while Railway runs.
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
