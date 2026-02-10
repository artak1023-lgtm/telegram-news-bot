import logging
import feedparser
import asyncio
import os
import time
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    CallbackQueryHandler, MessageHandler, filters
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')

DEFAULT_SOURCES = {
    'BBC': 'http://feeds.bbci.co.uk/news/world/rss.xml',
    'CNN': 'http://rss.cnn.com/rss/edition_world.rss',
    'Reuters': 'https://feeds.reuters.com/reuters/worldNews',
    'NYT': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'Al Jazeera': 'https://www.aljazeera.com/xml/rss/all.xml',
}

DEFAULT_KEYWORDS = [
    'russia', 'china', 'ukraine', 'nato', 'geopolit',
    'sanctions', 'conflict', 'war', 'diplomacy', 'trump',
    'europe', 'middle east', 'taiwan', 'israel', 'iran',
    'armenia', 'azerbaijan', 'turkey', 'election', 'military',
    'biden', 'putin'
]

# Global storage
last_check = {}
user_settings = {}

def get_user_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            'active': True,
            'keywords': DEFAULT_KEYWORDS.copy(),
            'sources': DEFAULT_SOURCES.copy(),
            'check_interval': 60,
            'max_items': 20,
        }
    return user_settings[user_id]

def format_time_with_timezones(published_time):
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(published_time)
        
        us_tz = pytz.timezone('America/New_York')
        us_time = dt.astimezone(us_tz)
        us_formatted = us_time.strftime('%b %d, %Y • %I:%M %p %Z')
        
        am_tz = pytz.timezone('Asia/Yerevan')
        am_time = dt.astimezone(am_tz)
        am_formatted = am_time.strftime('%b %d, %Y • %H:%M %Z')
        
        return f"📅 🇺🇸 {us_formatted}\n    🇦🇲 {am_formatted}", dt
    except Exception as e:
        logger.error(f"Time parsing error: {e}")
        return "", None

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📰 Աղբյուրներ", callback_data='sources')],
        [InlineKeyboardButton("🔍 Ֆիլտրեր", callback_data='filters')],
        [InlineKeyboardButton("⚙️ Կարգավորումներ", callback_data='settings')],
        [InlineKeyboardButton("📊 Վերջին նորություններ", callback_data='digest')],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    msg = (
        "🌍 <b>News Monitor Bot</b>\n\n"
        "Բարի գալուստ! Ես կուղարկեմ ձեզ աշխարհաքաղաքական նորություններ։\n\n"
        "⚡️ Ստուգում՝ <b>ամեն 1 րոպե</b>\n"
        "🎯 Ամենավերջին նորություններ\n\n"
        "Ընտրեք ցանկալի գործողությունը՝"
    )
    
    await update.message.reply_text(
        msg, 
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )
    
    # Initialize last check
    if user_id not in last_check:
        last_check[user_id] = set()
    
    # Remove old jobs
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()
    
    # Start monitoring
    context.job_queue.run_repeating(
        check_news_job,
        interval=60,
        first=10,
        data=user_id,
        name=str(user_id)
    )
    
    logger.info(f"Started monitoring for user {user_id}")

async def check_news_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job - runs every 60 seconds"""
    user_id = context.job.data
    settings = get_user_settings(user_id)
    
    if not settings.get('active', True):
        return
    
    try:
        logger.info(f"Checking news for user {user_id}...")
        new_articles = []
        
        for source_name, feed_url in settings['sources'].items():
            try:
                feed = feedparser.parse(feed_url, timeout=10)
                
                for entry in feed.entries[:settings['max_items']]:
                    title = entry.get('title', '')
                    link = entry.get('link', '')
                    published = entry.get('published', '')
                    summary = entry.get('summary', '')
                    
                    article_id = f"{source_name}_{link}"
                    
                    # Skip if already sent
                    if article_id in last_check.get(user_id, set()):
                        continue
                    
                    # Check keywords
                    text = (title + ' ' + summary).lower()
                    if any(kw in text for kw in settings['keywords']):
                        time_str, dt = format_time_with_timezones(published) if published else ("", None)
                        
                        new_articles.append({
                            'source': source_name,
                            'title': title,
                            'link': link,
                            'time_str': time_str,
                            'datetime': dt,
                            'article_id': article_id
                        })
            except Exception as e:
                logger.error(f"Error fetching {source_name}: {e}")
                continue
        
        # Sort by datetime (newest first)
        articles_with_time = [a for a in new_articles if a['datetime']]
        articles_sorted = sorted(articles_with_time, key=lambda x: x['datetime'], reverse=True)
        
        # Send new articles
        for article in articles_sorted[:10]:  # Max 10 per check
            try:
                msg = f"🌍 <b>{article['source']}</b>\n\n{article['title']}\n\n"
                if article['time_str']:
                    msg += f"{article['time_str']}\n\n"
                msg += f"🔗 {article['link']}"
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                
                # Mark as sent
                if user_id not in last_check:
                    last_check[user_id] = set()
                last_check[user_id].add(article['article_id'])
                
                # Cleanup old entries
                if len(last_check[user_id]) > 300:
                    last_check[user_id] = set(list(last_check[user_id])[-150:])
                
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error sending article: {e}")
        
        if articles_sorted:
            logger.info(f"Sent {len(articles_sorted[:10])} articles to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in check_news_job: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    
    if query.data == 'digest':
        await query.edit_message_text("📊 Բեռնում եմ...")
        await send_digest(query, user_id, settings)
    
    elif query.data == 'sources':
        keyboard = []
        for name in settings['sources'].keys():
            keyboard.append([InlineKeyboardButton(f"✓ {name}", callback_data=f'src_{name}')])
        keyboard.append([InlineKeyboardButton("➕ Ավելացնել", callback_data='add_source')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            "📰 <b>Աղբյուրներ</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'filters':
        kw_text = ', '.join(settings['keywords'][:10])
        keyboard = [
            [InlineKeyboardButton("➕ Ավելացնել բառ", callback_data='add_kw')],
            [InlineKeyboardButton("➖ Հեռացնել բառ", callback_data='rem_kw')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"🔍 <b>Բանալի բառեր</b>\n\n{kw_text}...\n\nԸնդամենը՝ {len(settings['keywords'])}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'settings':
        status = "🟢" if settings['active'] else "🔴"
        keyboard = [
            [InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if settings['active'] else '▶️ Միացնել'}",
                callback_data='toggle'
            )],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\nԿարգավիճակ՝ {status}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'toggle':
        settings['active'] = not settings['active']
        status = "🟢" if settings['active'] else "🔴"
        keyboard = [
            [InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if settings['active'] else '▶️ Միացնել'}",
                callback_data='toggle'
            )],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\nԿարգավիճակ՝ {status}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'back':
        await query.edit_message_text(
            "🌍 <b>News Monitor Bot</b>\n\nՈւզում եք՝",
            reply_markup=get_main_keyboard(),
            parse_mode='HTML'
        )

async def send_digest(query, user_id, settings):
    articles = []
    
    for name, url in settings['sources'].items():
        try:
            feed = feedparser.parse(url, timeout=10)
            for entry in feed.entries[:15]:
                title = entry.get('title', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                if any(kw in text for kw in settings['keywords']):
                    time_str, dt = format_time_with_timezones(entry.get('published', ''))
                    articles.append({
                        'source': name,
                        'title': title,
                        'link': entry.get('link', ''),
                        'time_str': time_str,
                        'datetime': dt
                    })
        except Exception as e:
            logger.error(f"Digest error for {name}: {e}")
    
    if not articles:
        await query.edit_message_text(
            "Նորություններ չկան։",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]])
        )
        return
    
    articles_sorted = sorted([a for a in articles if a['datetime']], key=lambda x: x['datetime'], reverse=True)
    
    msg = f"📰 <b>Վերջին {len(articles_sorted[:31])} նորություններ</b>\n(Ամենավերջինից դեպի հին)\n\n"
    
    for i, a in enumerate(articles_sorted[:31], 1):
        msg += f"{i}. <b>[{a['source']}]</b> {a['title']}\n"
        if a['time_str']:
            msg += f"{a['time_str']}\n"
        msg += f"🔗 {a['link']}\n\n"
        
        # Split long messages
        if i % 10 == 0 and i < len(articles_sorted[:31]):
            await query.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
            msg = ""
            await asyncio.sleep(1)
    
    if msg:
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]]),
            parse_mode='HTML',
            disable_web_page_preview=True
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    logger.info("Starting bot...")
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    
    logger.info("Bot polling started...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=1.0,
        timeout=30,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30
    )

if __name__ == '__main__':
    main()
