import os
import asyncio
import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from datetime import datetime, timedelta
import pytz

# ======================
# ENV
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

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
    "Washington Post": "https://feeds.washingtonpost.com/rss/national",
    "Politico": "https://www.politico.com/rss/politics08.xml",
    "NBC News": "https://feeds.nbcnews.com/nbcnews/public/news",
    "ABC News": "https://abcnews.go.com/abcnews/usheadlines",
    "Fox News": "https://feeds.foxnews.com/foxnews/national"
}

# ======================
# RUNTIME STORAGE
# ======================
KEYWORDS = set()
HASHTAGS = set()
ENABLED_SOURCES = set(RSS_SOURCES.keys())
SUBSCRIBERS = set()
SEEN_LINKS = set()

CHECK_INTERVAL = 60            # seconds
MAX_DELAY_MINUTES = 5          # freshness window

# ======================
# HELPERS
# ======================
def match_keywords(text: str) -> bool:
    if not KEYWORDS:
        return True
    text = text.lower()
    return any(k in text for k in KEYWORDS)

def format_message(source, title, link, published):
    time_str = published.strftime("%Y-%m-%d %H:%M")
    return (
        f"📰 <b>{title}</b>\n\n"
        f"🏷 <b>Աղբյուր</b>: {source}\n"
        f"🕒 <b>Ժամ</b>: {time_str} (Հայաստան)\n\n"
        f"🔗 {link}"
    )

# ======================
# COMMANDS
# ======================
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    SUBSCRIBERS.add(message.chat.id)
    await message.answer(
        "🌍 <b>News Monitor Bot — Ակտիվ է</b>\n\n"
        "📡 ԱՄՆ նորություններ (Reuters, CNN, BBC, NYT...)\n"
        "🔔 Push՝ հենց նոր հրապարակման ժամանակ\n"
        "🕒 Հայաստան ժամով\n\n"
        "📌 Օգնական հրամաններ՝\n"
        "/sources\n"
        "/keywords\n"
        "/add_keyword բառ\n"
        "/remove_keyword բառ\n"
        "/stop",
        parse_mode="HTML"
    )

@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    SUBSCRIBERS.discard(message.chat.id)
    await message.answer("⛔ Push նորությունները կանգնեցված են")

@dp.message(Command("keywords"))
async def list_keywords(message: types.Message):
    if not KEYWORDS:
        await message.answer("🔍 Keyword չկա")
    else:
        await message.answer("🔍 Keywords:\n" + ", ".join(sorted(KEYWORDS)))

@dp.message(Command("add_keyword"))
async def add_keyword(message: types.Message):
    try:
        word = message.text.split(maxsplit=1)[1].lower()
        KEYWORDS.add(word)
        await message.answer(f"➕ Keyword ավելացված՝ <b>{word}</b>", parse_mode="HTML")
    except:
        await message.answer("❗ Օգտագործում՝ /add_keyword բառ")

@dp.message(Command("remove_keyword"))
async def remove_keyword(message: types.Message):
    try:
        word = message.text.split(maxsplit=1)[1].lower()
        KEYWORDS.discard(word)
        await message.answer(f"➖ Keyword հեռացված՝ <b>{word}</b>", parse_mode="HTML")
    except:
        await message.answer("❗ Օգտագործում՝ /remove_keyword բառ")

@dp.message(Command("sources"))
async def list_sources(message: types.Message):
    text = "🗞 <b>Աղբյուրներ</b>:\n\n"
    for s in RSS_SOURCES:
        mark = "✅" if s in ENABLED_SOURCES else "❌"
        text += f"{mark} {s}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("test_news"))
async def test_news(message: types.Message):
    await message.answer("🧪 Թեստավորում եմ RSS-երը...")
    await check_news(force_send=True)
    await message.answer("✅ Թեստն ավարտված է")

# ======================
# NEWS LOOP
# ======================
async def check_news(force_send=False):
    now = datetime.now(TZ)

    for source, url in RSS_SOURCES.items():
        if source not in ENABLED_SOURCES:
            continue

        feed = feedparser.parse(url)

        for entry in feed.entries:
            link = entry.get("link")
            if not link or link in SEEN_LINKS:
                continue

            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(
                    *entry.published_parsed[:6],
                    tzinfo=pytz.utc
                ).astimezone(TZ)

            if not published:
                continue

            if not force_send:
                if now - published > timedelta(minutes=MAX_DELAY_MINUTES):
                    continue

            title = entry.get("title", "")
            text = f"{title} {entry.get('summary', '')}".lower()

            if not match_keywords(text):
                continue

            message = format_message(source, title, link, published)

            for chat_id in list(SUBSCRIBERS):
                try:
                    await bot.send_message(chat_id, message, parse_mode="HTML")
                except:
                    pass

            SEEN_LINKS.add(link)

# ======================
# BACKGROUND TASK
# ======================
async def news_loop():
    while True:
        try:
            await check_news()
        except Exception as e:
            print("ERROR:", e)
        await asyncio.sleep(CHECK_INTERVAL)

# ======================
# MAIN
# ======================
async def main():
    asyncio.create_task(news_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
