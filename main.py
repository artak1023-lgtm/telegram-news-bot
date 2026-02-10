import os
import logging
import feedparser
from datetime import datetime
import pytz

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")   # https://xxx.up.railway.app
PORT = int(os.getenv("PORT", 8080))

# ================== LOG ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("news-bot")

# ================== TIMEZONES ==================
TZ_US = pytz.timezone("America/New_York")
TZ_AM = pytz.timezone("Asia/Yerevan")

# ================== DEFAULT SOURCES ==================
SOURCES = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "CNN": "https://rss.cnn.com/rss/edition_world.rss",
    "Reuters": "https://feeds.reuters.com/reuters/worldNews",
}

# ================== DEFAULT KEYWORDS ==================
KEYWORDS = [
    "armenia", "azerbaijan", "russia", "ukraine",
    "iran", "turkey", "war", "conflict",
    "nato", "election", "military", "sanction"
]

# ================== STATE ==================
SUBSCRIBERS = set()
SENT_LINKS = set()

# ================== HELPERS ==================
def format_times(published):
    try:
        dt = datetime(*published[:6], tzinfo=pytz.utc)
        us = dt.astimezone(TZ_US).strftime("%H:%M")
        am = dt.astimezone(TZ_AM).strftime("%H:%M")
        return f"🕒 🇺🇸 {us}\n🕒 🇦🇲 {am}"
    except Exception:
        return ""

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)

    await update.message.reply_text(
        "✅ Բոտը միացված է\n"
        "📰 Աղբյուրներ՝ BBC, CNN, Reuters\n"
        "🔎 Ֆիլտրում՝ վերնագիր + նկարագրություն\n"
        "⏱ Ստուգում՝ ամեն 1 րոպե"
    )

# ================== NEWS CHECK ==================
async def check_news(context: ContextTypes.DEFAULT_TYPE):
    for name, url in SOURCES.items():
        feed = feedparser.parse(url)

        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            text = f"{title} {summary}".lower()

            if not any(k in text for k in KEYWORDS):
                continue

            link = entry.get("link")
            if not link or link in SENT_LINKS:
                continue

            times = format_times(entry.get("published_parsed", []))

            message = (
                f"📰 <b>{name}</b>\n"
                f"📌 {title}\n\n"
                f"{times}\n\n"
                f"🔗 {link}"
            )

            for chat_id in SUBSCRIBERS:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

            SENT_LINKS.add(link)

# ================== MAIN ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.job_queue.run_repeating(
        check_news,
        interval=60,   # 1 րոպե
        first=10
    )

    logger.info("Bot started")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
