import os
import asyncio
import feedparser
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime
import pytz

# ======================
# ENV
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = pytz.timezone("Asia/Yerevan")

CHECK_INTERVAL = 10  # 🔁 վայրկյան (test-ի համար 10, prod-ի համար 300)

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
keywords = set()
seen_links = set()
subscribers = set()

# ======================
# HELPERS
# ======================
def match_keywords(text: str) -> bool:
    if not keywords:
        return True
    text = text.lower()
    return any(k in text for k in keywords)

def format_time(entry):
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=pytz.utc)
        return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    return "—"

# ======================
# NEWS CHECK
# ======================
async def check_news():
    sent = 0
    skipped = 0

    for source, url in RSS_SOURCES.items():
        feed = feedparser.parse(url)

        for entry in feed.entries[:20]:
            link = entry.get("link")
            if not link or link in seen_links:
                skipped += 1
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")
            content = f"{title} {summary}"

            if not match_keywords(content):
                skipped += 1
                continue

            seen_links.add(link)
            sent += 1

            time_str = format_time(entry)

            text = (
                f"📰 <b>{title}</b>\n\n"
                f"🗞 <i>{source}</i>\n"
                f"⏰ {time_str} (AM)\n\n"
                f"🔗 {link}"
            )

            for chat_id in subscribers:
                await bot.send_message(
                    chat_id,
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

    print(f"🔄 CHECK DONE | Sent: {sent} | Skipped: {skipped} | Keywords: {keywords}")

# ======================
# LOOP
# ======================
async def news_loop():
    while True:
        await check_news()
        await asyncio.sleep(CHECK_INTERVAL)

# ======================
# COMMANDS
# ======================
@dp.message(Command("start"))
async def start_cmd(message: Message):
    subscribers.add(message.chat.id)
    await message.answer(
        "📰 News Monitor Bot ակտիվ է\n"
        "🔔 Նորությունները կգան այս չատում\n\n"
        "Commands:\n"
        "/add_keyword <word>\n"
        "/keywords\n"
        "/test_news\n"
        "/stop"
    )

@dp.message(Command("stop"))
async def stop_cmd(message: Message):
    subscribers.discard(message.chat.id)
    await message.answer("⛔ Push-ը կանգնեցված է")

@dp.message(Command("add_keyword"))
async def add_keyword(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❗ Օրինակ՝ /add_keyword trump")
        return

    kw = parts[1].lower()
    keywords.add(kw)
    await message.answer(f"➕ Keyword ավելացվեց՝ <b>{kw}</b>", parse_mode="HTML")

@dp.message(Command("keywords"))
async def list_keywords(message: Message):
    if not keywords:
        await message.answer("🔍 Keyword չկա")
    else:
        text = "🔍 Keywords:\n" + ", ".join(sorted(list(keywords)))
        await message.answer(text)

@dp.message(Command("test_news"))
async def test_news(message: Message):
    await message.answer("🧪 Թեստավորում եմ RSS-ները…")
    await check_news()
    await message.answer("✅ Թեստն ավարտվեց (նայիր՝ եկա՞վ նորություն)")

# ======================
# MAIN
# ======================
async def main():
    asyncio.create_task(news_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
