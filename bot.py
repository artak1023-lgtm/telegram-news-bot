import logging
import feedparser
import asyncio
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(levelname)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')

NEWS_SOURCES = {
    'BBC': 'http://feeds.bbci.co.uk/news/world/rss.xml',
    'CNN': 'http://rss.cnn.com/rss/edition_world.rss',
    'Reuters': 'https://feeds.reuters.com/reuters/worldNews',
    'NYT': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
}

KEYWORDS = [
    'russia', 'china', 'ukraine', 'nato', 'geopolit',
    'sanctions', 'conflict', 'war', 'diplomacy', 'trump',
    'europe', 'middle east', 'taiwan', 'israel', 'iran',
    'armenia', 'azerbaijan', 'turkey', 'election', 'military'
]

last_check = {}
user_settings = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_settings[user_id] = {'active': True, 'keywords': KEYWORDS.copy()}
    
    msg = "🌍 News Monitor Bot\n\nԱկտիվացված է!\n\nԵս կուղարկեմ աշխարհաքաղաքական նորություններ՝\n• BBC\n• CNN\n• Reuters\n• NYT\n\n📋 Հրամաններ՝\n/start - Սկսել\n/stop - Կանգնեցնել\n/resume - Վերսկսել\n/digest - Ամփոփում\n/help - Օգնություն\n\n✅ Ավտոմատ ծանուցումներ միացված են!"
    
    await update.message.reply_text(msg)
    logger.info(f"User {user_id} started the bot")
    
    if not context.job_queue.get_jobs_by_name(str(user_id)):
        context.job_queue.run_repeating(
            check_news,
            interval=300,
            first=10,
            data=user_id,
            name=str(user_id)
        )
        logger.info(f"Started news monitoring for user {user_id}")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_settings:
        user_settings[user_id]['active'] = False
    await update.message.reply_text("🔕 Ծանուցումները կանգնեցված են։")
    logger.info(f"User {user_id} stopped notifications")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_settings:
        user_settings[user_id]['active'] = True
    await update.message.reply_text("🔔 Ծանուցումները վերսկսված են!")
    logger.info(f"User {user_id} resumed notifications")

async def get_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Բեռնում եմ...")
    user_id = update.effective_user.id
    keywords = user_settings.get(user_id, {}).get('keywords', KEYWORDS)
    articles = []
    
    for name, url in NEWS_SOURCES.items():
        try:
            logger.info(f"Fetching {name}...")
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = entry.get('title', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                if any(kw in text for kw in keywords):
                    articles.append({
                        'source': name,
                        'title': title,
                        'link': entry.get('link', '')
                    })
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")
    
    if not articles:
        await update.message.reply_text("Նորություններ չեն գտնվել։")
        return
    
    msg = "📰 Վերջին նորություններ՝\n\n"
    for i, a in enumerate(articles[:10], 1):
        msg += f"{i}. [{a['source']}] {a['title']}\n{a['link']}\n\n"
    
    await update.message.reply_text(msg)
    logger.info(f"Sent digest to user {user_id} with {len(articles)} articles")

async def check_news(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    
    if not user_settings.get(user_id, {}).get('active', True):
        return
    
    keywords = user_settings.get(user_id, {}).get('keywords', KEYWORDS)
    
    for name, url in NEWS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:3]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                article_id = f"{name}_{link}"
                
                if article_id in last_check.get(user_id, set()):
                    continue
                
                if any(kw in text for kw in keywords):
                    msg = f"🌍 {name}\n\n{title}\n\n{link}"
                    await context.bot.send_message(chat_id=user_id, text=msg)
                    
                    if user_id not in last_check:
                        last_check[user_id] = set()
                    last_check[user_id].add(article_id)
                    
                    if len(last_check[user_id]) > 100:
                        last_check[user_id] = set(list(last_check[user_id])[-50:])
                    
                    await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error in check_news for {name}: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📚 Հրամաններ՝\n\n/start - Սկսել\n/stop - Կանգնեցնել\n/resume - Վերսկսել\n/digest - Ամփոփում\n/help - Օգնություն"
    await update.message.reply_text(text)

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    logger.info("Starting bot...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("digest", get_digest))
    app.add_handler(CommandHandler("help", help_command))
    
    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
