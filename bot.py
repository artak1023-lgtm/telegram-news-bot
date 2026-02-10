import logging
import feedparser
import asyncio
import os
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
CHANNEL_ID = os.environ.get('CHANNEL_ID')

# RSS աղբյուրներ
DEFAULT_SOURCES = {
    'BBC': 'http://feeds.bbci.co.uk/news/world/rss.xml',
    'CNN': 'http://rss.cnn.com/rss/edition_world.rss',
    'Reuters': 'https://feeds.reuters.com/reuters/worldNews',
    'NYT': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'Al Jazeera': 'https://www.aljazeera.com/xml/rss/all.xml',
    'The Guardian': 'https://www.theguardian.com/world/rss',
}

# Բանալի բառեր
DEFAULT_KEYWORDS = [
    'russia', 'china', 'ukraine', 'nato', 'geopolit',
    'sanctions', 'conflict', 'war', 'diplomacy', 'trump',
    'europe', 'middle east', 'taiwan', 'israel', 'iran',
    'armenia', 'azerbaijan', 'turkey', 'election', 'military',
    'biden', 'putin', 'xi', 'erdogan', 'macron'
]

# Global փոփոխականներ
sent_articles = set()
monitoring_active = True
current_sources = DEFAULT_SOURCES.copy()
current_keywords = DEFAULT_KEYWORDS.copy()

def format_time_with_timezones(published_time):
    """Ֆորմատավորել ժամը երկու ժամային գոտիներով"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(published_time)
        
        us_tz = pytz.timezone('America/New_York')
        us_time = dt.astimezone(us_tz)
        us_formatted = us_time.strftime('%b %d, %Y • %I:%M %p %Z')
        
        am_tz = pytz.timezone('Asia/Yerevan')
        am_time = dt.astimezone(am_tz)
        am_formatted = am_time.strftime('%b %d, %Y • %H:%M %Z')
        
        return f"🇺🇸 {us_formatted}\n🇦🇲 {am_formatted}", dt
    except Exception as e:
        logger.error(f"Error formatting time: {e}")
        return "", None

def get_main_keyboard():
    """Հիմնական menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("📰 Աղբյուրներ", callback_data='sources')],
        [InlineKeyboardButton("🔍 Ֆիլտրեր", callback_data='filters')],
        [InlineKeyboardButton("⚙️ Կարգավորումներ", callback_data='settings')],
        [InlineKeyboardButton("📊 Վերջին նորություններ", callback_data='digest')],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    msg = (
        "🌍 <b>Artak News Monitor</b>\n\n"
        "Բարի գալուստ!\n\n"
        "⚡️ Ավտոմատ monitoring՝ ամեն 1 րոպե\n"
        "📢 Նորությունները ուղարկվում են channel-ին\n"
        "🎯 Ոչ մի կարևոր նորություն չի բաց մնա\n\n"
        "Օգտագործեք menu-ն՝"
    )
    
    await update.message.reply_text(
        msg,
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback query handler"""
    query = update.callback_query
    await query.answer()
    
    global monitoring_active, current_sources, current_keywords
    
    if query.data == 'sources':
        keyboard = []
        for name in current_sources.keys():
            keyboard.append([InlineKeyboardButton(f"✅ {name}", callback_data=f'src_{name}')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            "📰 <b>Աղբյուրներ</b>\n\nԱկտիվ RSS աղբյուրներ՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'filters':
        keywords_preview = ', '.join(current_keywords[:15])
        keyboard = [
            [InlineKeyboardButton("📋 Բոլոր բառերը", callback_data='show_keywords')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"🔍 <b>Ֆիլտրեր</b>\n\n"
            f"Բանալի բառեր՝\n{keywords_preview}...\n\n"
            f"Ընդամենը՝ {len(current_keywords)} բառ",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'show_keywords':
        all_keywords = ', '.join(current_keywords)
        keyboard = [[InlineKeyboardButton("« Հետ", callback_data='filters')]]
        
        await query.edit_message_text(
            f"📋 <b>Բոլոր բանալի բառերը</b>\n\n{all_keywords}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'settings':
        status = "🟢 Միացված" if monitoring_active else "🔴 Անջատված"
        channel_info = f"📢 Channel՝ {CHANNEL_ID}" if CHANNEL_ID else "⚠️ Channel չի սահմանված"
        
        keyboard = [
            [InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if monitoring_active else '▶️ Միացնել'}", 
                callback_data='toggle'
            )],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\n"
            f"{channel_info}\n"
            f"Վիճակ՝ {status}\n"
            f"Ստուգում՝ <b>ամեն 1 րոպե</b>\n"
            f"Աղբյուրներ՝ {len(current_sources)}\n"
            f"Բանալի բառեր՝ {len(current_keywords)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'toggle':
        monitoring_active = not monitoring_active
        status = "միացված" if monitoring_active else "անջատված"
        
        await query.edit_message_text(
            f"✅ Monitoring-ը <b>{status}</b> է։",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='settings')]]),
            parse_mode='HTML'
        )
    
    elif query.data == 'digest':
        await query.edit_message_text("🔄 Հավաքում եմ նորություններ...")
        await send_digest(query)
    
    elif query.data == 'back':
        await query.edit_message_text(
            "🌍 <b>Artak News Monitor</b>\n\nՈւղտրեք գործողությունը՝",
            reply_markup=get_main_keyboard(),
            parse_mode='HTML'
        )

async def send_digest(query):
    """Ցույց տալ վերջին նորությունները"""
    articles = []
    
    for name, url in current_sources.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get('title', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                
                if any(kw in text for kw in current_keywords):
                    time_str, dt = format_time_with_timezones(entry.get('published', ''))
                    articles.append({
                        'source': name,
                        'title': title,
                        'link': entry.get('link', ''),
                        'time_str': time_str,
                        'datetime': dt
                    })
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")
    
    if not articles:
        await query.edit_message_text(
            "📊 Համապատասխան նորություններ չեն գտնվել։",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]])
        )
        return
    
    articles_sorted = sorted(
        [a for a in articles if a['datetime']],
        key=lambda x: x['datetime'],
        reverse=True
    )
    
    msg = f"📰 <b>Վերջին {len(articles_sorted)} նորություններ</b>\n\n"
    
    for i, a in enumerate(articles_sorted[:10], 1):
        msg += f"{i}. <b>[{a['source']}]</b> {a['title']}\n"
        if a['time_str']:
            msg += f"📅 {a['time_str']}\n"
        msg += f"🔗 {a['link']}\n\n"
    
    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]]),
        parse_mode='HTML',
        disable_web_page_preview=True
    )

async def check_news_job(context: ContextTypes.DEFAULT_TYPE):
    """Job function - ստուգում է նորությունները"""
    global sent_articles, monitoring_active, current_sources, current_keywords
    
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID not set - skipping")
        return
    
    if not monitoring_active:
        logger.info("Monitoring disabled - skipping")
        return
    
    logger.info(f"🔍 Checking news... (sent: {len(sent_articles)})")
    new_articles = []
    
    for name, url in current_sources.items():
        try:
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:15]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                published = entry.get('published', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                
                article_id = f"{name}::{link}"
                
                # Skip if already sent
                if article_id in sent_articles:
                    continue
                
                # Check keywords
                if any(kw in text for kw in current_keywords):
                    time_str, dt = format_time_with_timezones(published) if published else ("", None)
                    
                    new_articles.append({
                        'name': name,
                        'title': title,
                        'link': link,
                        'time_str': time_str,
                        'datetime': dt,
                        'article_id': article_id
                    })
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")
    
    # Sort by datetime (newest first)
    new_articles_sorted = sorted(
        [a for a in new_articles if a['datetime']],
        key=lambda x: x['datetime'],
        reverse=True
    )
    
    # Send articles
    for article in new_articles_sorted:
        try:
            msg = f"🌍 <b>{article['name']}</b>\n\n{article['title']}\n\n"
            if article['time_str']:
                msg += f"📅 {article['time_str']}\n\n"
            msg += f"🔗 {article['link']}"
            
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=msg,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            sent_articles.add(article['article_id'])
            
            # Keep cache under control
            if len(sent_articles) > 300:
                sent_articles = set(list(sent_articles)[-150:])
            
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Error sending article: {e}")
    
    if new_articles_sorted:
        logger.info(f"✅ Sent {len(new_articles_sorted)} new articles")
    else:
        logger.info("ℹ️ No new articles")

async def post_init(application: Application):
    """Initialize bot - կանչվում է bot-ը սկսելիս"""
    logger.info("=" * 70)
    logger.info("🚀 BOT STARTING...")
    logger.info("=" * 70)
    
    if not CHANNEL_ID:
        logger.error("❌ CHANNEL_ID not set!")
        logger.error("Set environment variable: CHANNEL_ID=-1001234567890")
        logger.error("Bot will NOT send automatic updates")
        logger.info("=" * 70)
        return
    
    logger.info(f"✅ Channel ID: {CHANNEL_ID}")
    logger.info(f"✅ Monitoring interval: 60 seconds")
    logger.info(f"✅ Sources: {len(DEFAULT_SOURCES)}")
    logger.info(f"✅ Keywords: {len(DEFAULT_KEYWORDS)}")
    
    # Start the monitoring job
    application.job_queue.run_repeating(
        check_news_job,
        interval=60,
        first=10,
        name='news_monitor'
    )
    
    logger.info("=" * 70)
    logger.info("✅ MONITORING STARTED - checking every 60 seconds")
    logger.info("=" * 70)

def main():
    """Main function"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    logger.info("Initializing bot...")
    
    # Build application
    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
