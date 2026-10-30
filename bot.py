import asyncio
import os
import re
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import yt_dlp

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN غير موجود! ضعه في ملف .env")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

URL_PATTERN = re.compile(r'https?://[^\s]+', re.IGNORECASE)

def get_ydl_opts(output_path: str) -> dict:
    return {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'retries': 5,
        'fragment_retries': 5,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if False else [],  # نخليها False عشان ما نجبر تحويل لكل شيء
    }

async def download_media(url: str):
    file_id = str(uuid.uuid4())
    output_template = str(DOWNLOAD_DIR / f"{file_id}.%(ext)s")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestaudio/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'retries': 5,
        'fragment_retries': 5,
    }

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info

    try:
        filepath, info = await loop.run_in_executor(None, _download)
        return filepath, info
    except Exception as e:
        return None, str(e)

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "مرحباً 👋\n\n"
        "أرسل لي رابط من أي منصة (يوتيوب، تيك توك، إنستغرام، ساوند كلاود...)\n"
        "وأحمل لك الملف.",
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text)
async def url_handler(message: Message):
    text = message.text.strip()
    match = URL_PATTERN.search(text)

    if not match:
        await message.answer("أرسل رابط صحيح...")
        return

    url = match.group(0)
    status_msg = await message.answer("⏳ جاري التحميل... انتظر قليلاً")

    result = await download_media(url)

    if not result or not result[0] or not os.path.exists(result[0]):
        error_msg = result[1] if result else "خطأ غير معروف"
        await status_msg.edit_text(f"❌ فشل التحميل:\n<code>{error_msg}</code>", parse_mode=ParseMode.HTML)
        return

    filepath, info = result
    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)

    try:
        if file_size_mb > 49:
            await status_msg.edit_text(
                f"⚠️ حجم الملف كبير جداً ({file_size_mb:.1f} MB)\n"
                "تيليجرام لا يسمح بإرسال ملفات أكبر من 50 ميجا عبر البوت."
            )
            return

        file = FSInputFile(filepath)
        ext = Path(filepath).suffix.lower()

        # تحديد نوع الإرسال بطريقة آمنة
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            await message.answer_photo(file, caption="✅ تم التحميل")
        elif ext in ['.mp3', '.m4a', '.ogg', '.wav', '.flac', '.aac']:
            await message.answer_audio(file, caption="✅ تم التحميل")
        elif ext in ['.mp4', '.mkv', '.webm', '.mov']:
            await message.answer_video(file, caption="✅ تم التحميل", supports_streaming=True)
        else:
            # لو ما عرفنا النوع، نرسله كـ Document (آمن دائماً)
            await message.answer_document(file, caption="✅ تم التحميل")

        await status_msg.delete()

    except Exception as e:
        # لو فشل الإرسال كـ فيديو أو صورة، نجرب نرسله كـ Document
        try:
            file = FSInputFile(filepath)
            await message.answer_document(file, caption="✅ تم التحميل (كملف)")
            await status_msg.delete()
        except Exception as e2:
            await status_msg.edit_text(f"❌ خطأ أثناء الإرسال:\n<code>{str(e2)}</code>", parse_mode=ParseMode.HTML)
    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except:
            pass

async def main():
    print("✅ البوت يعمل الآن...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
