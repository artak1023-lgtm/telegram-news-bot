import os
import asyncio
import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from datetime import datetime
import pytz

# ======================
# ENV
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

UTC = pytz.utc
ARM = pytz.timezone("Asia/Yerevan")

# ======================
# RSS SOURCES (USA)
# ======================
RSS_SOURCES = {
    "Reuters": "https://feeds.reuters.com/reuters/USNews",
    "AP News": "https://apnews.com/rss",
    "CNN": "http://rss.cnn.com/rss/cnn_us.rss",
    "BBC US": "http://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    "NY Times": "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
    "Washington Post": "https://feeds.washingtonpost.com/rss/national",
    "Politico": "https://www.politico.com/rss/politics08.xml",
    "NBC News": "https://feeds.nbcnews.com/nbcnews/public/news",
    "ABC News": "https://abcnews.go.com/abcnews/usheadlines",
    "Fox News": "https://feeds.foxnews.com/foxnews/national"
}

# ======================
# RUNTIME STORAGE
# ======================
KEYWORDS: set[str] = set()
SENT_LINKS: set[str] = set()
SUBSCRIBERS: set[int] = set()

CHECK_INTERVAL = 60  # seconds

# ======================
# HELPERS
# ======================
def format_times(published):
    utc_time = datetime(*published[:6], tzinfo=UTC)
    arm_time = utc_time.astimezone(ARM)
    return (
        f"⏰ 🇺🇸 {utc_time.strftime('%H:%M %d.%m.%Y')} UTC | "
        f"🇦🇲 {arm_time.strftime('%H:%M %d.%m.%Y')} ARM"
    )

def match_keywords(text: str) -> bool:
    if not KEYWORDS:
        return True
    text = text.lower()
    return any(k in text for k in KEYWORDS)

# ======================
# COMMANDS
# ======================
@dp.message(Command("start"))
async def start(msg: types.Message):
    SUBSCRIBERS.add(msg.chat.id)
    await msg.answer(
        "🌍 News Monitor Bot — Ակտիվ է\n\n"
        "📌 Հրամաններ\n"
        "/keywords — Keywords\n"
        "/add_keyword բառ\n"
        "/remove_keyword բառ\n"
        "/test_news — Թեստ\n"
        "/stop — Դադարեցնել"
    )

@dp.message(Command("stop"))
async def stop(msg: types.Message):
    SUBSCRIBERS.discard(msg.chat.id)
    await msg.answer("⛔️ Push նորությունները կանգնեցված են")

@dp.message(Command("keywords"))
async def keywords(msg: types.Message):
    if not KEYWORDS:
        await msg.answer("🔍 Keywords չկան")
    else:
        await msg.answer("🔍 Keywords:\n" + ", ".join(sorted(KEYWORDS)))

@dp.message(Command("add_keyword"))
async def add_keyword(msg: types.Message):
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer("❗ Օրինակ՝ /add_keyword Trump")
    KEYWORDS.add(parts[1].lower())
    await msg.answer(f"➕ Keyword ավելացված է՝ {parts[1]}")

@dp.message(Command("remove_keyword"))
async def remove_keyword(msg: types.Message):
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer("❗ Օրինակ՝ /remove_keyword Trump")
    KEYWORDS.discard(parts[1].lower())
    await msg.answer(f"➖ Keyword հեռացված է՝ {parts[1]}")

@dp.message(Command("test_news"))
async def test_news(msg: types.Message):
    await msg.answer("🧪 Թեստավորում եմ RSS-երը…")
    await check_news(test_chat=msg.chat.id)

# ======================
# NEWS LOOP
# ======================
async def check_news(test_chat: int | None = None):
    for source, url in RSS_SOURCES.items():
        feed = feedparser.parse(url)

        for entry in feed.entries[:5]:
            if not hasattr(entry, "published_parsed"):
                continue

            title = entry.title
            summary = getattr(entry, "summary", "")
            content = f"{title} {summary}".lower()

            if not match_keywords(content):
                continue

            if entry.link in SENT_LINKS:
                continue

            SENT_LINKS.add(entry.link)

            time_text = format_times(entry.published_parsed)

            message = (
                f"📰 <b>{source}</b>\n"
                f"<b>{title}</b>\n\n"
                f"{time_text}\n"
                f"🔗 {entry.link}"
            )

            targets = [test_chat] if test_chat else SUBSCRIBERS

            for chat_id in targets:
                try:
                    await bot.send_message(chat_id, message, parse_mode="HTML")
                except Exception:
                    pass

async def news_loop():
    while True:
        await check_news()
        await asyncio.sleep(CHECK_INTERVAL)

# ======================
# MAIN
# ======================
async def main():
    asyncio.create_task(news_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
