        import logging
import feedparser
import asyncio
import os
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    CallbackQueryHandler, MessageHandler, filters
)

logging.basicConfig(format='%(asctime)s - %(levelname)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')

# Ավելացված աղբյուրներ ավելի լրիվ ծածկույթի համար
DEFAULT_SOURCES = {
    'BBC': 'http://feeds.bbci.co.uk/news/world/rss.xml',
    'CNN': 'http://rss.cnn.com/rss/edition_world.rss',
    'Reuters': 'https://feeds.reuters.com/reuters/worldNews',
    'NYT': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'Al Jazeera': 'https://www.aljazeera.com/xml/rss/all.xml',
    'The Guardian': 'https://www.theguardian.com/world/rss',
}

DEFAULT_KEYWORDS = [
    'russia', 'china', 'ukraine', 'nato', 'geopolit',
    'sanctions', 'conflict', 'war', 'diplomacy', 'trump',
    'europe', 'middle east', 'taiwan', 'israel', 'iran',
    'armenia', 'azerbaijan', 'turkey', 'election', 'military',
    'biden', 'putin', 'xi', 'erdogan', 'macron'
]

# Ավելի մեծ cache վերջին նորությունների համար
last_check = {}
user_settings = {}

def get_user_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            'active': True,
            'keywords': DEFAULT_KEYWORDS.copy(),
            'sources': DEFAULT_SOURCES.copy(),
            'check_interval': 60,  # 1 րոպե (վայրկյաններով)
            'max_items_per_source': 15,  # Ավելի շատ նորություններ ստուգել
        }
    return user_settings[user_id]

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
    except:
        return "", None

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📰 Աղբյուրներ", callback_data='sources')],
        [InlineKeyboardButton("🔍 Ֆիլտրեր", callback_data='filters')],
        [InlineKeyboardButton("⚙️ Կարգավորումներ", callback_data='settings')],
        [InlineKeyboardButton("📊 Ամփոփում (վերջին 1 ժամ)", callback_data='digest')],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    msg = (
        "🌍 <b>News Monitor Bot</b>\n\n"
        "Բարի գալուստ! Ես կուղարկեմ ձեզ աշխարհաքաղաքական նորություններ։\n\n"
        "⚡️ Ստուգում՝ <b>ամեն 1 րոպե</b>\n"
        "🎯 Ոչ մի նորություն չի բաց մնա\n\n"
        "Ընտրեք ցանկալի գործողությունը՝"
    )
    
    await update.message.reply_text(
        msg, 
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )
    logger.info(f"User {user_id} started the bot")
    
    # Մաքրել հին job-երը
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()
    
    # Սկսել նոր monitoring՝ 1 րոպե interval-ով
    context.job_queue.run_repeating(
        check_news,
        interval=settings['check_interval'],  # 60 վայրկյան
        first=5,  # Առաջին ստուգումը 5 վայրկյանից
        data=user_id,
        name=str(user_id)
    )
    logger.info(f"Started 60-second monitoring for user {user_id}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    
    if query.data == 'sources':
        keyboard = []
        for name in settings['sources'].keys():
            keyboard.append([InlineKeyboardButton(f"✓ {name}", callback_data=f'source_{name}')])
        keyboard.append([InlineKeyboardButton("➕ Ավելացնել աղբյուր", callback_data='add_source')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            "📰 <b>Աղբյուրներ</b>\n\nԱկտիվ աղբյուրներ՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'filters':
        keywords_text = ', '.join(settings['keywords'][:15])
        keyboard = [
            [InlineKeyboardButton("➕ Ավելացնել բառ", callback_data='add_keyword')],
            [InlineKeyboardButton("➖ Հեռացնել բառ", callback_data='remove_keyword')],
            [InlineKeyboardButton("📋 Բոլոր բառերը", callback_data='show_all_keywords')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"🔍 <b>Ֆիլտրեր</b>\n\nԲանալի բառեր՝\n{keywords_text}...\n\n"
            f"Ընդամենը՝ {len(settings['keywords'])} բառ",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'show_all_keywords':
        all_keywords = ', '.join(settings['keywords'])
        keyboard = [[InlineKeyboardButton("« Հետ", callback_data='filters')]]
        
        await query.edit_message_text(
            f"📋 <b>Բոլոր բանալի բառերը</b>\n\n{all_keywords}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'settings':
        status = "🟢 Միացված" if settings['active'] else "🔴 Անջատված"
        interval_min = settings['check_interval'] // 60
        keyboard = [
            [InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if settings['active'] else '▶️ Միացնել'}", 
                callback_data='toggle_active'
            )],
            [InlineKeyboardButton(f"⏱ Ստուգում՝ {interval_min} րոպե", callback_data='change_interval')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\n"
            f"Ծանուցումներ՝ {status}\n"
            f"Ստուգման հաճախականություն՝ <b>{interval_min} րոպե</b>\n"
            f"Աղբյուրներ՝ {len(settings['sources'])}\n"
            f"Բանալի բառեր՝ {len(settings['keywords'])}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'change_interval':
        keyboard = [
            [InlineKeyboardButton("⚡️ 1 րոպե (առաջարկվող)", callback_data='interval_60')],
            [InlineKeyboardButton("🔥 2 րոպե", callback_data='interval_120')],
            [InlineKeyboardButton("⏱ 5 րոպե", callback_data='interval_300')],
            [InlineKeyboardButton("« Հետ", callback_data='settings')]
        ]
        
        await query.edit_message_text(
            "⏱ <b>Ստուգման հաճախականություն</b>\n\n"
            "Ընտրեք թե ինչքան հաճախ ստուգել նորությունները՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('interval_'):
        new_interval = int(query.data.replace('interval_', ''))
        settings['check_interval'] = new_interval
        
        # Վերսկսել monitoring-ը նոր interval-ով
        current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
        for job in current_jobs:
            job.schedule_removal()
        
        context.job_queue.run_repeating(
            check_news,
            interval=new_interval,
            first=5,
            data=user_id,
            name=str(user_id)
        )
        
        interval_min = new_interval // 60
        await query.answer(f"✅ Հաճախականությունը փոխվել է՝ {interval_min} րոպե")
        
        keyboard = [[InlineKeyboardButton("« Հետ", callback_data='settings')]]
        await query.edit_message_text(
            f"✅ Հաջողությամբ փոխվեց!\n\n"
            f"Նոր հաճախականություն՝ <b>{interval_min} րոպե</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'digest':
        await query.edit_message_text("📊 Բեռնում եմ վերջին ժամվա նորությունները...")
        await send_digest(query, user_id, settings)
    
    elif query.data == 'toggle_active':
        settings['active'] = not settings['active']
        status = "🟢 Միացված" if settings['active'] else "🔴 Անջատված"
        interval_min = settings['check_interval'] // 60
        keyboard = [
            [InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if settings['active'] else '▶️ Միացնել'}", 
                callback_data='toggle_active'
            )],
            [InlineKeyboardButton(f"⏱ Ստուգում՝ {interval_min} րոպե", callback_data='change_interval')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\n"
            f"Ծանուցումներ՝ {status}\n"
            f"Ստուգման հաճախականություն՝ <b>{interval_min} րոպե</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('source_'):
        source_name = query.data.replace('source_', '')
        keyboard = [
            [InlineKeyboardButton("🗑 Հեռացնել", callback_data=f'remove_source_{source_name}')],
            [InlineKeyboardButton("« Հետ", callback_data='sources')]
        ]
        
        await query.edit_message_text(
            f"📰 <b>{source_name}</b>\n\n{settings['sources'][source_name]}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('remove_source_'):
        source_name = query.data.replace('remove_source_', '')
        if source_name in settings['sources']:
            del settings['sources'][source_name]
        
        keyboard = []
        for name in settings['sources'].keys():
            keyboard.append([InlineKeyboardButton(f"✓ {name}", callback_data=f'source_{name}')])
        keyboard.append([InlineKeyboardButton("➕ Ավելացնել աղբյուր", callback_data='add_source')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            "📰 <b>Աղբյուրներ</b>\n\nԱկտիվ աղբյուրներ՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_source':
        await query.edit_message_text(
            "➕ <b>Ավելացնել աղբյուր</b>\n\n"
            "Ուղարկեք հաղորդագրություն հետևյալ ֆորմատով՝\n\n"
            "<code>Անուն | RSS URL</code>\n\n"
            "Օրինակ՝\n<code>Al Jazeera | https://www.aljazeera.com/xml/rss/all.xml</code>\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
        context.user_data['waiting_for'] = 'add_source'
    
    elif query.data == 'add_keyword':
        await query.edit_message_text(
            "➕ <b>Ավելացնել բանալի բառ</b>\n\n"
            "Ուղարկեք բառը կամ արտահայտությունը՝\n\n"
            "Օրինակ՝ <code>ceasefire</code>\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
        context.user_data['waiting_for'] = 'add_keyword'
    
    elif query.data == 'remove_keyword':
        keywords_list = '\n'.join([f"{i+1}. {kw}" for i, kw in enumerate(settings['keywords'][:30])])
        await query.edit_message_text(
            f"➖ <b>Հեռացնել բանալի բառ</b>\n\n{keywords_list}\n\n"
            "Ուղարկեք բառը որ ուզում եք հեռացնել՝\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
        context.user_data['waiting_for'] = 'remove_keyword'
    
    elif query.data == 'back':
        msg = (
            "🌍 <b>News Monitor Bot</b>\n\n"
            "Ընտրեք ցանկալի գործողությունը՝"
        )
        await query.edit_message_text(
            msg,
            reply_markup=get_main_keyboard(),
            parse_mode='HTML'
        )

async def send_digest(query, user_id, settings):
    articles = []
    
    # Հավաքել բոլոր նորությունները ժամանակով
    for name, url in settings['sources'].items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:settings['max_items_per_source']]:
                title = entry.get('title', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                if any(kw in text for kw in settings['keywords']):
                    time_str, dt = format_time_with_timezones(entry.get('published', ''))
                    articles.append({
                        'source': name,
                        'title': title,
                        'link': entry.get('link', ''),
                        'published': entry.get('published', ''),
                        'time_str': time_str,
                        'datetime': dt
                    })
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")
    
    if not articles:
        await query.edit_message_text(
            "📊 Վերջին ժամում համապատասխան նորություններ չեն գտնվել։",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]])
        )
        return
    
    # Դասավորել ամենավերջիններից՝ առաջինը
    articles_sorted = sorted(
        [a for a in articles if a['datetime']], 
        key=lambda x: x['datetime'], 
        reverse=True  # Ամենավերջինները առաջ
    )
    
    msg = f"📰 <b>Վերջին {len(articles_sorted)} նորություններ</b>\n"
    msg += f"(Ամենավերջինից դեպի հին)\n\n"
    
    for i, a in enumerate(articles_sorted[:12], 1):
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'add_source':
        try:
            parts = update.message.text.split('|')
            if len(parts) == 2:
                name = parts[0].strip()
                url = parts[1].strip()
                settings['sources'][name] = url
                await update.message.reply_text(
                    f"✅ Աղբյուրը ավելացված է՝ {name}",
                    reply_markup=get_main_keyboard()
                )
            else:
                await update.message.reply_text(
                    "❌ Սխալ ֆորմատ։ Օգտագործեք՝ Անուն | URL"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Սխալ։ {e}")
        context.user_data['waiting_for'] = None
    
    elif waiting_for == 'add_keyword':
        keyword = update.message.text.strip().lower()
        if keyword not in settings['keywords']:
            settings['keywords'].append(keyword)
            await update.message.reply_text(
                f"✅ Բառը ավելացված է՝ {keyword}",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ Այս բառն արդեն կա։")
        context.user_data['waiting_for'] = None
    
    elif waiting_for == 'remove_keyword':
        keyword = update.message.text.strip().lower()
        if keyword in settings['keywords']:
            settings['keywords'].remove(keyword)
            await update.message.reply_text(
                f"✅ Բառը հեռացված է՝ {keyword}",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ Այս բառը չի գտնվել։")
        context.user_data['waiting_for'] = None

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for'] = None
    await update.message.reply_text(
        "❌ Չեղարկված է։",
        reply_markup=get_main_keyboard()
    )

async def check_news(context: ContextTypes.DEFAULT_TYPE):
    """Ստուգել նորությունները - կանչվում է ամեն 1 րոպե"""
    user_id = context.job.data
    settings = get_user_settings(user_id)
    
    if not settings['active']:
        return
    
    logger.info(f"Checking news for user {user_id}...")
    new_articles = []
    
    for name, url in settings['sources'].items():
        try:
            feed = feedparser.parse(url)
            
            # Ստուգել ավելի շատ նորություններ (15 հատ)
            for entry in feed.entries[:settings['max_items_per_source']]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                published = entry.get('published', '')
                text = (title + ' ' + entry.get('summary', '')).lower()
                article_id = f"{name}_{link}"
                
                # Եթե արդեն ուղարկել ենք, բաց թողնել
                if article_id in last_check.get(user_id, set()):
                    continue
                
                # Ստուգել բանալի բառերը
                if any(kw in text for kw in settings['keywords']):
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
            logger.error(f"Error in check_news for {name}: {e}")
    
    # Դասավորել ամենավերջիններից առաջ
    new_articles_sorted = sorted(
        [a for a in new_articles if a['datetime']], 
        key=lambda x: x['datetime'], 
        reverse=True
    )
    
    # Ուղարկել ամենավերջինները առաջինը
    for article in new_articles_sorted:
        try:
            msg = f"🌍 <b>{article['name']}</b>\n\n{article['title']}\n\n"
            if article['time_str']:
                msg += f"📅 {article['time_str']}\n\n"
            msg += f"🔗 {article['link']}"
            
            await context.bot.send_message(
                chat_id=user_id, 
                text=msg,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            # Պահպանել որ չկրկնվի
            if user_id not in last_check:
                last_check[user_id] = set()
            last_check[user_id].add(article['article_id'])
            
            # Պահպանել վերջին 200 նորությունները cache-ում
            if len(last_check[user_id]) > 200:
                last_check[user_id] = set(list(last_check[user_id])[-100:])
            
            await asyncio.sleep(1.5)  # Փոքր ընդմիջում spam-ից խուսափելու համար
            
        except Exception as e:
            logger.error(f"Error sending article: {e}")
    
    if new_articles_sorted:
        logger.info(f"Sent {len(new_articles_sorted)} new articles to user {user_id}")

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    logger.info("Starting bot with 60-second monitoring...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))
    
