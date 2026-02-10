import os
import logging
import feedparser
from datetime import datetime
import pytz

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from apscheduler.schedulers.background import BackgroundScheduler

# ---------------- CONFIG ----------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))

RSS_URLS = [
    "https://news.am/arm/rss/",
    "https://armenpress.am/arm/rss/"
]

CHECK_INTERVAL_MINUTES = 1
TIMEZONE_AM = pytz.timezone("Asia/Yerevan")

# ---------------- LOGGING ----------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ---------------- STORAGE ----------------

sent_links = set()

# ---------------- BOT COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["🔎 Ֆիլտրեր"],
        ["⚙️ Կարգավորումներ"],
        ["📊 Ակտիվություն (վերջին 1 ժամ)"],
    ]
    await update.message.reply_text(
        "🎯 Բոտը ակտիվացված է ✅",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

# ---------------- RSS JOB ----------------

async def check_rss(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat_id = context.application.bot_data.get("chat_id")

    if not chat_id:
        return

    for url in RSS_URLS:
        feed = feedparser.parse(url)

        for entry in feed.entries[:5]:
            link = entry.get("link")
            if not link or link in sent_links:
                continue

            sent_links.add(link)

            title = entry.get("title", "Առանց վերնագրի")
            description = entry.get("summary", "")

            published = entry.get("published_parsed")
            if published:
                published_dt = datetime(*published[:6], tzinfo=pytz.utc)
                am_time = published_dt.astimezone(TIMEZONE_AM)
                time_text = am_time.strftime("%H:%M %d-%m-%Y")
            else:
                time_text = "Ժամը անհայտ"

            message = (
                f"📰 <b>{title}</b>\n\n"
                f"{description}\n\n"
                f"🕒 🇦🇲 {time_text}\n"
                f"🔗 {link}"
            )

            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

# ---------------- MAIN ----------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # հիշում ենք առաջին chat_id-ն
    async def remember_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.application.bot_data["chat_id"] = update.message.chat_id

    app.add_handler(CommandHandler("remember", remember_chat))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: app.create_task(check_rss(ContextTypes.DEFAULT_TYPE(application=app))),
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
    )
    scheduler.start()

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()
