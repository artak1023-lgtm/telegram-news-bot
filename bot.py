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
SUBSCRIBERS = set()
SENT_LINKS = set()

KEYWORDS = set()
HASHTAGS = set()
ENABLED_SOURCES = set()  # դատարկ = բոլորը միացված

# ======================
# BASIC COMMANDS
# ======================
@dp.message(Command("start"))
async def start(message: types.Message):
    SUBSCRIBERS.add(message.chat.id)
    await message.answer(
        "🌍 News Monitor Bot — Ակտիվ է\n\n"
        "📰 ԱՄՆ նորություններ (BBC, CNN, Reuters, NYT…)\n"
        "📲 Push ավտոմատ\n"
        "⏰ Ժամը՝ Հայաստանի ժամանակով 🇦🇲\n\n"
        "📌 Օգտակար հրամաններ՝\n"
        "/sources – Աղբյուրներ\n"
        "/keywords – Keywords\n"
        "/hashtags – Hashtags\n"
        "/stop – Դադարեցնել"
    )

@dp.message(Command("stop"))
async def stop(message: types.Message):
    SUBSCRIBERS.discard(message.chat.id)
    await message.answer("🔕 Push նորությունները դադարեցված են")

@dp.message(Command("ping"))
async def ping(message: types.Message):
    now = datetime.now(TZ).strftime("%H:%M:%S")
    await message.answer(f"✅ Բոտը ակտիվ է\n🕒 Հայաստան՝ {now}")

# ======================
# KEYWORDS
# ======================
@dp.message(Command("add_keyword"))
async def add_keyword(message: types.Message):
    try:
        word = message.text.split(maxsplit=1)[1].lower()
        KEYWORDS.add(word)
        await message.answer(f"➕ Keyword ավելացվեց՝ {word}")
    except:
        await message.answer("Օգտագործում՝ /add_keyword Trump")

@dp.message(Command("remove_keyword"))
async def remove_keyword(message: types.Message):
    try:
        word = message.text.split(maxsplit=1)[1].lower()
        KEYWORDS.discard(word)
        await message.answer(f"➖ Keyword հեռացվեց՝ {word}")
    except:
        await message.answer("Օգտագործում՝ /remove_keyword Trump")

@dp.message(Command("keywords"))
async def list_keywords(message: types.Message):
    if not KEYWORDS:
        await message.answer("🔍 Keyword ֆիլտր չկա")
    else:
        await message.answer("🔍 Keywords:\n" + ", ".join(KEYWORDS))

# ======================
# HASHTAGS
# ======================
@dp.message(Command("add_hashtag"))
async def add_hashtag(message: types.Message):
    try:
        tag = message.text.split(maxsplit=1)[1].lower().lstrip("#")
        HASHTAGS.add(tag)
        await message.answer(f"➕ Hashtag ավելացվեց՝ #{tag}")
    except:
        await message.answer("Օգտագործում՝ /add_hashtag Ukraine")

@dp.message(Command("remove_hashtag"))
async def remove_hashtag(message: types.Message):
    try:
        tag = message.text.split(maxsplit=1)[1].lower().lstrip("#")
        HASHTAGS.discard(tag)
        await message.answer(f"➖ Hashtag հեռացվեց՝ #{tag}")
    except:
        await message.answer("Օգտագործում՝ /remove_hashtag Ukraine")

@dp.message(Command("hashtags"))
async def list_hashtags(message: types.Message):
    if not HASHTAGS:
        await message.answer("#️⃣ Hashtag ֆիլտր չկա")
    else:
        await message.answer("#️⃣ Hashtags:\n" + ", ".join(f"#{h}" for h in HASHTAGS))

# ======================
# SOURCES
# ======================
@dp.message(Command("sources"))
async def list_sources(message: types.Message):
    text = "🗞 Աղբյուրներ:\n"
    for s in RSS_SOURCES:
        status = "✅" if (not ENABLED_SOURCES or s in ENABLED_SOURCES) else "❌"
        text += f"{status} {s}\n"
    await message.answer(text)

@dp.message(Command("enable"))
async def enable_source(message: types.Message):
    try:
        src = message.text.split(maxsplit=1)[1]
        if src in RSS_SOURCES:
            ENABLED_SOURCES.add(src)
            await message.answer(f"✅ Միացվեց՝ {src}")
        else:
            await message.answer("❌ Նման աղբյուր չկա")
    except:
        await message.answer("Օգտագործում՝ /enable Reuters")

@dp.message(Command("disable"))
async def disable_source(message: types.Message):
    try:
        src = message.text.split(maxsplit=1)[1]
        ENABLED_SOURCES.discard(src)
        await message.answer(f"❌ Անջատվեց՝ {src}")
    except:
        await message.answer("Օգտագործում՝ /disable CNN")

# ======================
# NEWS FETCHER
# ======================
async def fetch_news():
    while True:
        for source, url in RSS_SOURCES.items():

            if ENABLED_SOURCES and source not in ENABLED_SOURCES:
                continue

            feed = feedparser.parse(url)

            for entry in feed.entries[:5]:
                link = entry.get("link")
                if not link or link in SENT_LINKS:
                    continue

                title = entry.get("title", "")
                content = title.lower()

                if KEYWORDS and not any(k in content for k in KEYWORDS):
                    continue

                if HASHTAGS and not any(f"#{h}" in content for h in HASHTAGS):
                    continue

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

# ======================
# MAIN
# ======================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
