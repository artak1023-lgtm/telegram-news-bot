import logging
import feedparser
import asyncio
import os
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
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

# Conversation states
WAITING_SOURCE_NAME, WAITING_SOURCE_URL, WAITING_KEYWORD_ADD, WAITING_KEYWORD_REMOVE = range(4)

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
        "⚡️ Ավտոմատ monitoring՝ ամեն 30 վայրկյան\n"
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
        keyboard.append([InlineKeyboardButton("➕ Ավելացնել աղբյուր", callback_data='add_source')])
        keyboard.append([InlineKeyboardButton("➖ Հեռացնել աղբյուր", callback_data='remove_source')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            f"📰 <b>Աղբյուրներ</b>\n\nԱկտիվ RSS աղբյուրներ՝ {len(current_sources)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_source':
        context.user_data['waiting_for'] = 'source_name'
        await query.edit_message_text(
            "➕ <b>Ավելացնել նոր RSS աղբյուր</b>\n\n"
            "Քայլ 1/2: Ուղարկեք աղբյուրի անունը\n"
            "Օրինակ՝ <code>Arminfo</code>\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
    
    elif query.data == 'remove_source':
        if len(current_sources) == 0:
            await query.answer("Աղբյուրներ չկան!", show_alert=True)
            return
        
        keyboard = []
        for name in current_sources.keys():
            keyboard.append([InlineKeyboardButton(f"❌ {name}", callback_data=f'del_src_{name}')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='sources')])
        
        await query.edit_message_text(
            "➖ <b>Հեռացնել աղբյուր</b>\n\nՈւշտրեք հեռացվող աղբյուրը՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('del_src_'):
        source_name = query.data.replace('del_src_', '')
        if source_name in current_sources:
            del current_sources[source_name]
            await query.answer(f"✅ Հեռացված է՝ {source_name}", show_alert=True)
            
            # Return to sources menu
            keyboard = []
            for name in current_sources.keys():
                keyboard.append([InlineKeyboardButton(f"✅ {name}", callback_data=f'src_{name}')])
            keyboard.append([InlineKeyboardButton("➕ Ավելացնել աղբյուր", callback_data='add_source')])
            keyboard.append([InlineKeyboardButton("➖ Հեռացնել աղբյուր", callback_data='remove_source')])
            keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
            
            await query.edit_message_text(
                f"📰 <b>Աղբյուրներ</b>\n\nԱկտիվ RSS աղբյուրներ՝ {len(current_sources)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        else:
            await query.answer("❌ Աղբյուրը չի գտնվել", show_alert=True)
    
    elif query.data == 'filters':
        keywords_preview = ', '.join(current_keywords[:15])
        keyboard = [
            [InlineKeyboardButton("📋 Բոլոր բառերը", callback_data='show_keywords')],
            [InlineKeyboardButton("➕ Ավելացնել բառ", callback_data='add_keyword')],
            [InlineKeyboardButton("➖ Հեռացնել բառ", callback_data='remove_keyword')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"🔍 <b>Ֆիլտրեր</b>\n\n"
            f"Բանալի բառեր՝\n{keywords_preview}...\n\n"
            f"Ընդամենը՝ {len(current_keywords)} բառ",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_keyword':
        context.user_data['waiting_for'] = 'keyword_add'
        await query.edit_message_text(
            "➕ <b>Ավելացնել նոր բանալի բառ</b>\n\n"
            "Ուղարկեք բանալի բառը (անգլերեն)՝\n"
            "Օրինակ՝ <code>pashinyan</code>\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
    
    elif query.data == 'remove_keyword':
        if len(current_keywords) == 0:
            await query.answer("Բառեր չկան!", show_alert=True)
            return
        
        # Show first 20 keywords with delete buttons
        keyboard = []
        for kw in current_keywords[:20]:
            keyboard.append([InlineKeyboardButton(f"❌ {kw}", callback_data=f'del_kw_{kw}')])
        
        if len(current_keywords) > 20:
            keyboard.append([InlineKeyboardButton(f"... ևս {len(current_keywords) - 20}", callback_data='show_more_keywords')])
        
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='filters')])
        
        await query.edit_message_text(
            "➖ <b>Հեռացնել բանալի բառ</b>\n\nՈւշտրեք հեռացվող բառը՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('del_kw_'):
        keyword = query.data.replace('del_kw_', '')
        if keyword in current_keywords:
            current_keywords.remove(keyword)
            await query.answer(f"✅ Հեռացված է՝ {keyword}", show_alert=True)
            
            # Return to filters menu
            keywords_preview = ', '.join(current_keywords[:15])
            keyboard = [
                [InlineKeyboardButton("📋 Բոլոր բառերը", callback_data='show_keywords')],
                [InlineKeyboardButton("➕ Ավելացնել բառ", callback_data='add_keyword')],
                [InlineKeyboardButton("➖ Հեռացնել բառ", callback_data='remove_keyword')],
                [InlineKeyboardButton("« Հետ", callback_data='back')]
            ]
            
            await query.edit_message_text(
                f"🔍 <b>Ֆիլտրեր</b>\n\n"
                f"Բանալի բառեր՝\n{keywords_preview}...\n\n"
                f"Ընդամենը՝ {len(current_keywords)} բառ",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        else:
            await query.answer("❌ Բառը չի գտնվել", show_alert=True)
    
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
            f"Ստուգում՝ <b>ամեն 30 վայրկյան</b>\n"
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

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for adding sources and keywords"""
    global current_sources, current_keywords
    
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'source_name':
        # Save source name and ask for URL
        context.user_data['new_source_name'] = update.message.text.strip()
        context.user_data['waiting_for'] = 'source_url'
        
        await update.message.reply_text(
            f"➕ <b>Ավելացնել նոր RSS աղբյուր</b>\n\n"
            f"Անուն՝ <code>{context.user_data['new_source_name']}</code>\n\n"
            f"Քայլ 2/2: Ուղարկեք RSS feed URL-ը\n"
            f"Օրինակ՝ <code>https://arminfo.am/rss</code>\n\n"
            f"Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
    
    elif waiting_for == 'source_url':
        # Save the source
        source_name = context.user_data.get('new_source_name')
        source_url = update.message.text.strip()
        
        # Validate URL
        if not source_url.startswith('http'):
            await update.message.reply_text(
                "❌ Սխալ URL ֆորմատ։ URL-ը պետք է սկսվի http:// կամ https://\n\n"
                "Փորձեք նորից կամ /cancel չեղարկելու համար"
            )
            return
        
        current_sources[source_name] = source_url
        context.user_data.clear()
        
        await update.message.reply_text(
            f"✅ Աղբյուրը հաջողությամբ ավելացված է!\n\n"
            f"📰 {source_name}\n"
            f"🔗 {source_url}",
            reply_markup=get_main_keyboard()
        )
    
    elif waiting_for == 'keyword_add':
        # Add keyword
        keyword = update.message.text.strip().lower()
        
        if keyword in current_keywords:
            await update.message.reply_text(
                f"⚠️ Բառը <code>{keyword}</code> արդեն գոյություն ունի։\n\n"
                f"Փորձեք այլ բառ կամ /cancel չեղարկելու համար",
                parse_mode='HTML'
            )
            return
        
        current_keywords.append(keyword)
        context.user_data.clear()
        
        await update.message.reply_text(
            f"✅ Բանալի բառը հաջողությամբ ավելացված է!\n\n"
            f"🔍 {keyword}\n\n"
            f"Ընդհանուր բառեր՝ {len(current_keywords)}",
            reply_markup=get_main_keyboard()
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing operation"""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Գործողությունը չեղարկված է։",
        reply_markup=get_main_keyboard()
    )

async def check_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual news check command"""
    await update.message.reply_text("🔍 Ստուգում եմ նորությունները...")
    await check_news_job(context)
    await update.message.reply_text(
        "✅ Ստուգումը ավարտված է։",
        reply_markup=get_main_keyboard()
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
    logger.info(f"✅ Monitoring interval: 30 seconds")
    logger.info(f"✅ Sources: {len(DEFAULT_SOURCES)}")
    logger.info(f"✅ Keywords: {len(DEFAULT_KEYWORDS)}")
    
    # Start the monitoring job - 30 վայրկյան
    application.job_queue.run_repeating(
        check_news_job,
        interval=30,  # 30 վայրկյան
        first=10,
        name='news_monitor'
    )
    
    logger.info("=" * 70)
    logger.info("✅ MONITORING STARTED - checking every 30 seconds")
    logger.info("=" * 70)

def main():
    """Main function"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    logger.info("Initializing bot...")
    
    # Build application with job queue explicitly enabled
    try:
        application = (
            Application.builder()
            .token(TOKEN)
            .post_init(post_init)
            .build()
        )
        
        # Verify job queue exists
        if application.job_queue is None:
            logger.error("❌ Job queue is None! Install: pip install 'python-telegram-bot[job-queue]'")
            return
        
        logger.info("✅ Job queue initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize application: {e}")
        return
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("check_news", check_news_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    # Start bot
    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
