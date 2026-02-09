import os
import asyncio
import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from datetime import datetime
import pytz

BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = pytz.timezone("Asia/Yerevan")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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

SUBSCRIBERS = set()
SENT_LINKS = set()

@dp.message(Command("start"))
async def start(message: types.Message):
    SUBSCRIBERS.add(message.chat.id)
    await message.answer(
        "🇺🇸 ԱՄՆ ՆՈՐՈՒԹՅՈՒՆՆԵՐ\n\n"
        "📰 Բոլոր հիմնական աղբյուրներից\n"
        "📲 Push տարբերակով\n"
        "⏰ Ժամը՝ Հայաստանի ժամանակով"
    )

@dp.message(Command("stop"))
async def stop(message: types.Message):
    SUBSCRIBERS.discard(message.chat.id)
    await message.answer("🔕 Push նորությունները դադարեցված են")

@dp.message(Command("ping"))
async def ping(message: types.Message):
    now = datetime.now(TZ).strftime("%H:%M:%S")
    await message.answer(f"✅ Բոտը ակտիվ է\n🕒 Հայաստան՝ {now}")

async def fetch_news():
    while True:
        for source, url in RSS_SOURCES.items():
            feed = feedparser.parse(url)

            for entry in feed.entries[:5]:
                link = entry.get("link")
                if not link or link in SENT_LINKS:
                    continue

                title = entry.get("title", "Նորություն")
                published = entry.get("published_parsed")

                if published:
                    dt = datetime(*published[:6], tzinfo=pytz.utc).astimezone(TZ)
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = "—"

                text = (
                    f"🇺🇸 ԱՄՆ ՆՈՐՈՒԹՅՈՒՆ\n\n"
                    f"🗞 Աղբյուր՝ {source}\n"
                    f"🕒 Ժամ՝ {time_str} (Հայաստանի ժամանակով)\n\n"
                    f"📝 {title}\n\n"
                    f"🔗 {link}"
                )

                for chat_id in SUBSCRIBERS:
                    await bot.send_message(chat_id, text)

                SENT_LINKS.add(link)

        await asyncio.sleep(300)

async def main():
    asyncio.create_task(fetch_news())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
