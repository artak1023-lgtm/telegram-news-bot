import os
import logging
import feedparser
import pytz
from datetime import datetime
from typing import Dict, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # օրինակ՝ https://xxxx.up.railway.app
PORT = int(os.getenv("PORT", "8080"))

CHECK_INTERVAL_SECONDS = 60  # 1 րոպե (fixed, ինչպես ուզեցիր)

DEFAULT_SOURCES = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "CNN": "https://rss.cnn.com/rss/edition_world.rss",
    "Reuters": "https://feeds.reuters.com/reuters/worldNews",
}

DEFAULT_KEYWORDS = [
    "armenia", "azerbaijan", "russia", "ukraine",
    "war", "conflict", "nato", "iran", "turkey",
    "election", "military", "sanction",
]

US_TZ = pytz.timezone("America/New_York")
AM_TZ = pytz.timezone("Asia/Yerevan")

# ================== STATE ==================

user_settings: Dict[int, Dict] = {}
sent_articles: Dict[int, Set[str]] = {}

# ================== LOGGING ==================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("news-bot")

# ================== HELPERS ==================

def get_user_settings(user_id: int) -> Dict:
    if user_id not in user_settings:
        user_settings[user_id] = {
            "sources": DEFAULT_SOURCES.copy(),
            "keywords": DEFAULT_KEYWORDS.copy(),
            "active": True,
        }
    return user_settings[user_id]


def format_times(published: str) -> str:
    try:
        dt = datetime(*feedparser.parse(published).updated_parsed[:6], tzinfo=pytz.utc)
        us = dt.astimezone(US_TZ).strftime("%H:%M")
        am = dt.astimezone(AM_TZ).strftime("%H:%M")
        return f"🕒 🇺🇸 {us}\n🕒 🇦🇲 {am}"
    except Exception:
        return ""


# ================== BOT HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user_settings(update.effective_user.id)

    keyboard = [
        [InlineKeyboardButton("📰 Աղբյուրներ", callback_data="sources")],
        [InlineKeyboardButton("🔎 Ֆիլտրներ", callback_data="filters")],
        [InlineKeyboardButton("📊 Կարգավիճակ", callback_data="status")],
    ]

    await update.message.reply_text(
        "🎯 Բոտը աշխատում է և նորությունները կհետևի ավտոմատ։",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    settings = get_user_settings(user_id)

    if query.data == "filters":
        text = "🔎 Ֆիլտրներ (keywords):\n\n" + ", ".join(settings["keywords"])
        await query.edit_message_text(text)

    elif query.data == "status":
        status = "🟢 Ակտիվ" if settings["active"] else "🔴 Անջատված"
        await query.edit_message_text(f"📊 Կարգավիճակ\n\n{status}")

    elif query.data == "sources":
        text = "📰 Աղբյուրներ:\n\n" + "\n".join(settings["sources"].keys())
        await query.edit_message_text(text)


# ================== NEWS CHECK ==================

async def check_news(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    settings = get_user_settings(user_id)

    if not settings["active"]:
        return

    sent_articles.setdefault(user_id, set())

    for source, url in settings["sources"].items():
        feed = feedparser.parse(url)

        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            text = f"{title} {summary}".lower()

            if not any(k.lower() in text for k in settings["keywords"]):
                continue

            article_id = entry.get("link")
            if article_id in sent_articles[user_id]:
                continue

            time_block = format_times(entry.get("published", ""))

            message = (
                f"📰 <b>{source}</b>\n"
                f"📌 {title}\n\n"
                f"{time_block}\n\n"
                f"🔗 {article_id}"
            )

            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            sent_articles[user_id].add(article_id)


# ================== MAIN ==================

async def on_startup(app: Application):
    await app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    logger.info("Webhook set")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.job_queue.run_repeating(
        check_news,
        interval=CHECK_INTERVAL_SECONDS,
        first=5,
        data=None,
        name="news-check",
    )

    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            on_startup=on_startup,
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
