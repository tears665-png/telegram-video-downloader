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

# Regex مرن يقبل أي رابط
URL_PATTERN = re.compile(
    r'https?://[^\s]+',
    re.IGNORECASE
)

def get_ydl_opts(output_path: str) -> dict:
    return {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestaudio/best',
        'outtmpl': output_path,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'retries': 5,
        'fragment_retries': 5,
        'extractor_args': {
            'tiktok': {
                'webpage_download': True,
            }
        },
    }

async def download_media(url: str):
    file_id = str(uuid.uuid4())
    output_template = str(DOWNLOAD_DIR / f"{file_id}.%(ext)s")

    ydl_opts = get_ydl_opts(output_template)
    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            # تحديد نوع الملف
            ext = info.get('ext', '').lower()
            if ext in ['jpg', 'jpeg', 'png', 'webp'] or info.get('vcodec') == 'none':
                return filename, 'photo'
            elif ext in ['mp3', 'm4a', 'ogg', 'wav', 'flac']:
                return filename, 'audio'
            return filename, 'video'

    try:
        filepath, media_type = await loop.run_in_executor(None, _download)
        return filepath, media_type
    except Exception as e:
        return None, str(e)

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "مرحباً 👋\n\n"
        "أرسل لي رابط فيديو أو صوت أو صورة من:\n"
        "• يوتيوب\n"
        "• إنستغرام\n"
        "• تيك توك\n"
        "• ساوند كلاود\n"
        "• تويتر / إكس\n"
        "• فيسبوك وغيرها\n\n"
        "وسأقوم بتحميله لك.",
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

    filepath, media_type = await download_media(url)

    if not filepath or not os.path.exists(filepath):
        await status_msg.edit_text(f"❌ فشل التحميل:\n<code>{media_type}</code>", parse_mode=ParseMode.HTML)
        return

    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)

    try:
        if file_size_mb > 49:
            await status_msg.edit_text(
                f"⚠️ حجم الملف كبير جداً ({file_size_mb:.1f} MB)\n"
                "تيليجرام لا يسمح بإرسال ملفات أكبر من 50 ميجا عبر البوت."
            )
        else:
            file = FSInputFile(filepath)

            if media_type == 'photo' or filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                await message.answer_photo(file, caption="✅ تم التحميل")
            elif media_type == 'audio' or filepath.lower().endswith(('.mp3', '.m4a', '.ogg', '.wav', '.flac')):
                await message.answer_audio(file, caption="✅ تم التحميل")
            else:
                await message.answer_video(
                    file,
                    caption="✅ تم التحميل",
                    supports_streaming=True
                )

            await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ أثناء الإرسال:\n<code>{str(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        # حذف الملف بعد الإرسال
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
