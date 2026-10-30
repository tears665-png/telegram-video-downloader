import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yt_dlp

# إعداد السجل (Logging) لمتابعة الأخطاء والعمليات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توكن البوت الخاص بك
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Please set the BOT_TOKEN environment variable."
    )

# مجلد مؤقت لحفظ الفيديوهات قبل إرسالها
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الترحيب بالمستخدم عند إرسال /start"""
    user_name = update.effective_user.first_name
    welcome_message = (
        f"أهلاً بك يا {user_name}! 👋\n\n"
        "أنا بوت تحميل الفيديوهات. أرسل لي رابطاً من أي من المنصات التالية وسأقوم بتحميله وإرساله لك:\n"
        "• يوتيوب (YouTube)\n"
        "• إنستغرام (Instagram)\n"
        "• فيسبوك (Facebook)\n"
        "• تيك توك (TikTok)\n"
        "• إكس / تويتر (X / Twitter)\n"
    )
    await update.message.reply_text(welcome_message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الروابط المرسلة وتحميل الفيديو"""
    url = update.message.text.strip()
    
    # التحقق البسيط أن الرسالة تبدو كرابط
    if not url.startswith("http://") and not url.startswith("https://"):
        await update.message.reply_text("❌ الرجاء إرسال رابط صالح يبدأ بـ http أو https.")
        return

    status_message = await update.message.reply_text("⏳ جاري معالجة الرابط وتحميل الفيديو، يرجى الانتظار...")

    output_template = os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s')
    
    ydl_opts = {
        'outtmpl': output_template,
        'format': 'bestvideo+bestaudio/best', # اختيار أفضل جودة متاحة
        'max_filesize': 50 * 1024 * 1024,   # الحد الأقصى لحجم الملف (50 ميجابايت كحد إرسال مجاني لتيليجرام عبر البوتات)
        'noplaylist': True,                 # تحميل فيديو واحد وليس قائمة تشغيل كاملة
    }

    file_path = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await update.message.chat.send_action(action="upload_video")
            # استخراج معلومات الفيديو وتحميله
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        # التأكد من أن الملف موجود وجاهز للإرسال
        if os.path.exists(file_path):
            await status_message.edit_text("📤 جاري رفع الفيديو وإرساله إليك...")
            
            with open(file_path, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption="✅ تم التحميل بواسطة البوت بنجاح!"
                )
            await status_message.delete()
        else:
            await status_message.edit_text("❌ حدث خطأ: لم يتم العثور على الملف المُحمّل.")

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download error: {e}")
        await status_message.edit_text("❌ عذراً، فشل تحميل الفيديو. تأكد أن الرابط صحيح وعام (ليس خاصاً).")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await status_message.edit_text("❌ حدث خطأ غير متوقع أثناء المعالجة.")
    
    finally:
        # تنظيف وحذف الملف من الخادم بعد إرساله للمحافظة على مساحة التخزين
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Error removing file: {e}")

def main():
    """تشغيل التطبيق"""
    app = ApplicationBuilder().token(TOKEN).build()

    # الأوامر والرسائل
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 البوت يعمل الآن ويستمع للرسائل...")
    app.run_polling()

if __name__ == '__main__':
    main()
