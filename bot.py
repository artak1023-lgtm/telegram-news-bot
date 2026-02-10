import logging
import feedparser
import asyncio
import os
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')

SOURCES = {
    'BBC': 'http://feeds.bbci.co.uk/news/world/rss.xml',
    'CNN': 'http://rss.cnn.com/rss/edition_world.rss',
    'Reuters': 'https://feeds.reuters.com/reuters/worldNews',
    'NYT': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
}

KEYWORDS = ['russia', 'china', 'ukraine', 'nato', 'war', 'armenia', 'azerbaijan']
sent_articles = {}

def format_time(pub_time):
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_time)
        us = dt.astimezone(pytz.timezone('America/New_York')).strftime('%b %d • %I:%M %p EST')
        am = dt.astimezone(pytz.timezone('Asia/Yerevan')).strftime('%b %d • %H:%M +04')
        return f"📅 🇺🇸 {us}\n    🇦🇲 {am}", dt
    except:
        return "", None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sent_articles[uid] = set()
    
    keyboard = [
        [InlineKeyboardButton("📊 Վերջին նորությունները", callback_data='news')]
    ]
    
    await update.message.reply_text(
        "🌍 <b>News Monitor</b>\n\nԱկտիվ է։ Կստանաք նորություններ ավտոմատ։",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    
    # Remove old jobs
    for job in context.job_queue.get_jobs_by_name(str(uid)):
        job.schedule_removal()
    
    # Start job
    context.job_queue.run_repeating(check, interval=60, first=5, data=uid, name=str(uid))
    logger.info(f"Started for {uid}")

async def check(context: ContextTypes.DEFAULT_TYPE):
    uid = context.job.data
    
    for name, url in SOURCES.items():
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                continue
            
            for entry in feed.entries[:10]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                pub = entry.get('published', '')
                text = (title + entry.get('summary', '')).lower()
                aid = f"{name}_{link}"
                
                if aid in sent_articles.get(uid, set()):
                    continue
                
                if any(k in text for k in KEYWORDS):
                    time_str, _ = format_time(pub) if pub else ("", None)
                    
                    msg = f"🌍 <b>{name}</b>\n\n{title}\n\n"
                    if time_str:
                        msg += f"{time_str}\n\n"
                    msg += f"🔗 {link}"
                    
                    await context.bot.send_message(
                        chat_id=uid,
                        text=msg,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    
                    if uid not in sent_articles:
                        sent_articles[uid] = set()
                    sent_articles[uid].add(aid)
                    
                    if len(sent_articles[uid]) > 200:
                        sent_articles[uid] = set(list(sent_articles[uid])[-100:])
                    
                    await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"{name}: {e}")
    
    logger.info(f"Checked for {uid}")

async def show_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📊 Բեռնում...")
    
    articles = []
    for name, url in SOURCES.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get('title', '')
                text = (title + entry.get('summary', '')).lower()
                if any(k in text for k in KEYWORDS):
                    time_str, dt = format_time(entry.get('published', ''))
                    articles.append({
                        'source': name,
                        'title': title,
                        'link': entry.get('link', ''),
                        'time': time_str,
                        'dt': dt
                    })
        except:
            pass
    
    if not articles:
        await query.edit_message_text("Նորություններ չկան։")
        return
    
    sorted_arts = sorted([a for a in articles if a['dt']], key=lambda x: x['dt'], reverse=True)
    
    msg = "📰 <b>Վերջին նորություններ</b>\n\n"
    for i, a in enumerate(sorted_arts[:10], 1):
        msg += f"{i}. <b>[{a['source']}]</b> {a['title']}\n"
        if a['time']:
            msg += f"{a['time']}\n"
        msg += f"🔗 {a['link']}\n\n"
    
    await query.edit_message_text(msg, parse_mode='HTML', disable_web_page_preview=True)

def main():
    if not TOKEN:
        return
    
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_news, pattern='news'))
    
    logger.info("Starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
