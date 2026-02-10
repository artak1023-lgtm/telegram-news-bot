import os
import asyncio
import hashlib
import feedparser
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime
import pytz

# ======================
# CONFIG
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHECK_INTERVAL = 60  # seconds
TZ = pytz.timezone("Asia/Yerevan")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ======================
# RSS SOURCES (USA)
# ======================
RSS_SOURCES = {
    "Reuters": "https://feeds.reuters.com/reuters/USNews",
    "AP News": "https://apnews.com/rss",
    "CNN": "http://rss.cnn.com/rss/cnn_us.rss",
    "BBC US": "http://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    "NY Times": "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
}

# ======================
# RUNTIME STORAGE
# ======================
KEYWORDS: set[str] = set()
SEEN_HASHES: set[str] = set()
SUBSCRIBERS: set[int] = set()

# ======================
# HELPERS
# ======================
def normalize(text: str) -> str:
    return text.lower()

def entry_hash(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}{link}".encode()).hexdigest()

def matches_keywords(entry) -> bool:
    text = normalize(
        f"{entry.get('title','')} {entry.get('summary','')}"
    )
    return any(k in text for k in KEYWORDS)

def format_message(source, entry) -> str:
    title = entry.title
    link = entry.link

    published = entry.get("published_parsed")
    if published:
        dt = datetime(*published[:6], tzinfo=pytz.utc).astimezone(TZ)
        time_str = dt.strftime("%H:%M %d.%m.%Y")
    else:
        time_str = "—"

    return (
        f"📰 <b>{source}</b>\n"
        f"<b>{title}</b>\n\n"
        f"⏰ {time_str}\n"
        f"🔗 {link}"
    )

# ======================
# COMMANDS
# ======================
@dp.message(Command("start"))
async def start(msg: Message):
    SUBSCRIBERS.add(msg.chat.id)
    await msg.answer(
        "🟢 News Monitor աշխատում է\n"
        "⏱️ Թարմացում՝ ամեն 60 վրկ\n\n"
        "📌 Հրամաններ:\n"
        "/keywords\n"
        "/add_keyword բառ\n"
        "/remove_keyword բառ\n"
        "/stop"
    )

@dp.message(Command("stop"))
async def stop(msg: Message):
    SUBSCRIBERS.discard(msg.chat.id)
    await msg.answer("⛔ Push-երը անջատված են")

@dp.message(Command("add_keyword"))
async def add_keyword(msg: Message):
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return
    KEYWORDS.add(normalize(parts[1]))
    await msg.answer(f"➕ Keyword ավելացվեց՝ {parts[1]}")

@dp.message(Command("remove_keyword"))
async def remove_keyword(msg: Message):
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return
    KEYWORDS.discard(normalize(parts[1]))
    await msg.answer(f"➖ Keyword հանվեց՝ {parts[1]}")

@dp.message(Command("keywords"))
async def list_keywords(msg: Message):
    if not KEYWORDS:
        await msg.answer("🔍 Keyword չկա")
    else:
        await msg.answer("🔍 Keywords:\n" + ", ".join(sorted(KEYWORDS)))

@dp.message(Command("test_news"))
async def test_news(msg: Message):
    found = 0
    for source, url in RSS_SOURCES.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            if matches_keywords(entry):
                found += 1
                await msg.answer(
                    format_message(source, entry),
                    parse_mode="HTML"
                )
    if found == 0:
        await msg.answer("❌ Ոչ մի match չգտնվեց")

# ======================
# BACKGROUND LOOP
# ======================
async def news_loop():
    while True:
        try:
            for source, url in RSS_SOURCES.items():
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    h = entry_hash(entry.title, entry.link)
                    if h in SEEN_HASHES:
                        continue
                    if matches_keywords(entry):
                        SEEN_HASHES.add(h)
                        msg = format_message(source, entry)
                        for chat_id in SUBSCRIBERS:
                            await bot.send_message(
                                chat_id, msg, parse_mode="HTML"
                            )
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception:
            await asyncio.sleep(10)

# ======================
# MAIN
# ======================
async def main():
    asyncio.create_task(news_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())     
