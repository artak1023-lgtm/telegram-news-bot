import logging
import feedparser
import asyncio
import os
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator
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
USER_ID = int(os.environ.get('USER_ID', '0'))
USER_CHANNEL_ID = os.environ.get('USER_CHANNEL_ID')
TRANSLATION_LANG = os.environ.get('TRANSLATION_LANG', 'ru')  # 'ru' for Russian, 'hy' for Armenian

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

def is_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot"""
    return user_id == USER_ID

def translate_text(text: str, target_lang: str = None) -> str:
    """Translate text to target language"""
    if not target_lang:
        target_lang = TRANSLATION_LANG
    
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        
        # Split long text into chunks (Google Translate has limits)
        max_length = 4500
        if len(text) <= max_length:
            return translator.translate(text)
        
        # Split by sentences and translate in chunks
        chunks = []
        current_chunk = ""
        
        sentences = text.split('. ')
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < max_length:
                current_chunk += sentence + '. '
            else:
                if current_chunk:
                    chunks.append(translator.translate(current_chunk))
                current_chunk = sentence + '. '
        
        if current_chunk:
            chunks.append(translator.translate(current_chunk))
        
        return ' '.join(chunks)
        
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text  # Return original if translation fails

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
    user_id = update.effective_user.id
    
    if USER_ID == 0:
        await update.message.reply_text(
            "⚠️ <b>USER_ID-ն սահմանված չէ!</b>\n\n"
            f"Քո User ID-ն՝ <code>{user_id}</code>\n\n"
            "Railway-ում environment variables-ում ավելացրու՝\n"
            "<code>USER_ID={user_id}</code>\n\n"
            "Հետո վերսկսիր bot-ը։",
            parse_mode='HTML'
        )
        return
    
    if not is_authorized(user_id):
        await update.message.reply_text(
            "❌ Դու չունես հասանելիություն այս bot-ին։\n\n"
            f"Քո User ID՝ <code>{user_id}</code>",
            parse_mode='HTML'
        )
        return
    
    lang_name = "Ռուսերեն" if TRANSLATION_LANG == 'ru' else "Հայերեն" if TRANSLATION_LANG == 'hy' else TRANSLATION_LANG
    channel_status = ""
    if USER_CHANNEL_ID:
        channel_status = f"\n📢 Քո Personal Channel՝ միացված\n🌐 Թարգմանություն՝ {lang_name}"
    
    msg = (
        f"🌍 <b>Artak News Monitor</b>\n\n"
        f"Բարի գալուստ!{channel_status}\n\n"
        f"⚡️ Ավտոմատ monitoring՝ ամեն 30 վայրկյան\n"
        f"📢 Main channel՝ անգլերեն (բնօրինակ)\n"
        f"📱 Քո channel՝ թարգմանված {lang_name}\n"
        f"🎯 Ամբողջական նկարագրություն + թարգմանություն\n\n"
        f"Օգտագործեք menu-ն՝"
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
    
    user_id = query.from_user.id
    
    if not is_authorized(user_id):
        await query.answer("❌ Դու չունես հասանելիություն", show_alert=True)
        return
    
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
        lang_name = "Ռուսերեն" if TRANSLATION_LANG == 'ru' else "Հայերեն" if TRANSLATION_LANG == 'hy' else TRANSLATION_LANG
        
        main_channel_info = f"📢 Main Channel՝ {CHANNEL_ID}" if CHANNEL_ID else "⚠️ Main Channel չի սահմանված"
        user_channel_info = f"📱 Personal Channel՝ {USER_CHANNEL_ID}" if USER_CHANNEL_ID else "⚠️ Personal Channel չի սահմանված"
        
        keyboard = [
            [InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if monitoring_active else '▶️ Միացնել'}", 
                callback_data='toggle'
            )],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\n"
            f"{main_channel_info}\n"
            f"{user_channel_info}\n\n"
            f"Վիճակ՝ {status}\n"
            f"Ստուգում՝ <b>ամեն 30 վայրկյան</b>\n"
            f"Թարգմանություն՝ <b>{lang_name}</b>\n"
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
    """Handle text messages"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        return
    
    global current_sources, current_keywords
    
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'source_name':
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
        source_name = context.user_data.get('new_source_name')
        source_url = update.message.text.strip()
        
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
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        return
    
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Գործողությունը չեղարկված է։",
        reply_markup=get_main_keyboard()
    )

async def check_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual news check command"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Դու չունես հասանելիություն")
        return
    
    await update.message.reply_text("🔍 Ստուգում եմ նորությունները...")
    await check_news_job(context)
    await update.message.reply_text(
        "✅ Ստուգումը ավարտված է։",
        reply_markup=get_main_keyboard()
    )

async def my_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user's Telegram ID"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Անուն չկա"
    first_name = update.effective_user.first_name or ""
    
    authorized = "✅ Դու ունես հասանելիություն" if is_authorized(user_id) else "❌ Դու չունես հասանելիություն"
    
    await update.message.reply_text(
        f"👤 <b>Քո տեղեկությունները</b>\n\n"
        f"Անուն՝ {first_name}\n"
        f"Username՝ @{username}\n"
        f"User ID՝ <code>{user_id}</code>\n\n"
        f"{authorized}",
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
                summary = entry.get('summary', '') or entry.get('description', '')
                
                text = (title + ' ' + summary).lower()
                article_id = f"{name}::{link}"
                
                if article_id in sent_articles:
                    continue
                
                if any(kw in text for kw in current_keywords):
                    time_str, dt = format_time_with_timezones(published) if published else ("", None)
                    
                    new_articles.append({
                        'name': name,
                        'title': title,
                        'summary': summary,
                        'link': link,
                        'time_str': time_str,
                        'datetime': dt,
                        'article_id': article_id
                    })
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")
    
    new_articles_sorted = sorted(
        [a for a in new_articles if a['datetime']],
        key=lambda x: x['datetime'],
        reverse=True
    )
    
    for article in new_articles_sorted:
        try:
            # Original message for main channel (English)
            msg_original = f"🌍 <b>{article['name']}</b>\n\n{article['title']}\n\n"
            if article['time_str']:
                msg_original += f"📅 {article['time_str']}\n\n"
            msg_original += f"🔗 {article['link']}"
            
            # Send to main channel (original English)
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=msg_original,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            # Translated message for user's personal channel
            if USER_CHANNEL_ID:
                try:
                    logger.info(f"Translating article: {article['title'][:50]}...")
                    
                    # Translate title and summary
                    translated_title = translate_text(article['title'], TRANSLATION_LANG)
                    translated_summary = ""
                    
                    if article['summary']:
                        # Clean HTML tags from summary
                        import re
                        clean_summary = re.sub('<[^<]+?>', '', article['summary'])
                        translated_summary = translate_text(clean_summary, TRANSLATION_LANG)
                    
                    # Build translated message
                    msg_translated = f"🌍 <b>{article['name']}</b>\n\n"
                    msg_translated += f"<b>{translated_title}</b>\n\n"
                    
                    if translated_summary:
                        msg_translated += f"{translated_summary}\n\n"
                    
                    if article['time_str']:
                        msg_translated += f"📅 {article['time_str']}\n\n"
                    
                    msg_translated += f"🔗 {article['link']}"
                    
                    await context.bot.send_message(
                        chat_id=USER_CHANNEL_ID,
                        text=msg_translated,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    
                    logger.info(f"Sent translated article to user's channel")
                    
                except Exception as e:
                    logger.error(f"Error sending translated article: {e}")
            
            sent_articles.add(article['article_id'])
            
            if len(sent_articles) > 300:
                sent_articles = set(list(sent_articles)[-150:])
            
            await asyncio.sleep(3)  # Increased delay for translation
            
        except Exception as e:
            logger.error(f"Error sending article: {e}")
    
    if new_articles_sorted:
        logger.info(f"✅ Sent {len(new_articles_sorted)} new articles")
    else:
        logger.info("ℹ️ No new articles")

async def post_init(application: Application):
    """Initialize bot"""
    logger.info("=" * 70)
    logger.info("🚀 BOT STARTING...")
    logger.info("=" * 70)
    
    if USER_ID == 0:
        logger.error("❌ USER_ID not set!")
        logger.error("Set environment variable: USER_ID=telegram_user_id")
        logger.info("=" * 70)
    
    if not CHANNEL_ID:
        logger.error("❌ CHANNEL_ID not set!")
        logger.error("Set environment variable: CHANNEL_ID=-1001234567890")
        logger.info("=" * 70)
        return
    
    lang_name = "Russian" if TRANSLATION_LANG == 'ru' else "Armenian" if TRANSLATION_LANG == 'hy' else TRANSLATION_LANG
    
    logger.info(f"✅ Main Channel ID: {CHANNEL_ID}")
    logger.info(f"✅ Authorized User ID: {USER_ID}")
    logger.info(f"✅ User's Personal Channel: {USER_CHANNEL_ID or 'Not set'}")
    logger.info(f"✅ Translation Language: {lang_name} ({TRANSLATION_LANG})")
    logger.info(f"✅ Monitoring interval: 30 seconds")
    logger.info(f"✅ Sources: {len(DEFAULT_SOURCES)}")
    logger.info(f"✅ Keywords: {len(DEFAULT_KEYWORDS)}")
    
    application.job_queue.run_repeating(
        check_news_job,
        interval=30,
        first=10,
        name='news_monitor'
    )
    
    logger.info("=" * 70)
    logger.info("✅ MONITORING STARTED WITH AUTO-TRANSLATION")
    logger.info("=" * 70)

def main():
    """Main function"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    logger.info("Initializing bot...")
    
    try:
        application = (
            Application.builder()
            .token(TOKEN)
            .post_init(post_init)
            .build()
        )
        
        if application.job_queue is None:
            logger.error("❌ Job queue is None! Install: pip install 'python-telegram-bot[job-queue]'")
            return
        
        logger.info("✅ Job queue initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize application: {e}")
        return
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("check_news", check_news_command))
    application.add_handler(CommandHandler("myid", my_id_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
