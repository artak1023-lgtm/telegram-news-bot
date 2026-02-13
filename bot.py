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
CHANNEL_ID = os.environ.get('CHANNEL_ID')  # Main channel (անգլերեն)
MY_CHANNEL_ID = os.environ.get('MY_CHANNEL_ID')  # Քո անձնական channel (թարգմանված)
TRANSLATION_LANG = os.environ.get('TRANSLATION_LANG', 'ru')  # 'ru' or 'hy'

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

def translate_text(text: str, target_lang: str = None) -> str:
    """Translate text to target language"""
    if not target_lang:
        target_lang = TRANSLATION_LANG
    
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        
        # Split long text into chunks
        max_length = 4500
        if len(text) <= max_length:
            return translator.translate(text)
        
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
        return text

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
    lang_name = "Ռուսերեն" if TRANSLATION_LANG == 'ru' else "Հայերեն"
    
    msg = (
        f"🌍 <b>Artak News Monitor</b>\n\n"
        f"Բարի գալուստ!\n\n"
        f"⚡️ Ավտոմատ monitoring՝ ամեն 30 վայրկյան\n"
        f"📢 Main channel՝ անգլերեն բնօրինակ\n"
        f"📱 Քո channel՝ թարգմանված {lang_name}\n"
        f"📝 Ամբողջական նկարագրություն + թարգմանություն\n\n"
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
    
    global monitoring_active, current_sources, current_keywords
    
    if query.data == 'sources':
        keyboard = []
        for name in current_sources.keys():
            keyboard.append([InlineKeyboardButton(f"✅ {name}", callback_data=f'src_{name}')])
        keyboard.append([InlineKeyboardButton("➕ Ավելացնել", callback_data='add_source')])
        keyboard.append([InlineKeyboardButton("➖ Հեռացնել", callback_data='remove_source')])
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            f"📰 <b>Աղբյուրներ</b>\n\nԱկտիվ՝ {len(current_sources)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_source':
        context.user_data['waiting_for'] = 'source_name'
        await query.edit_message_text(
            "➕ <b>Ավելացնել RSS աղբյուր</b>\n\n"
            "Քայլ 1/2: Անունը\n"
            "Օրինակ՝ <code>Arminfo</code>\n\n"
            "/cancel չեղարկել",
            parse_mode='HTML'
        )
    
    elif query.data == 'remove_source':
        if not current_sources:
            await query.answer("Աղբյուրներ չկան!", show_alert=True)
            return
        
        keyboard = [[InlineKeyboardButton(f"❌ {name}", callback_data=f'del_src_{name}')] for name in current_sources.keys()]
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='sources')])
        
        await query.edit_message_text(
            "➖ <b>Հեռացնել</b>\n\nՈւշտրեք՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('del_src_'):
        name = query.data.replace('del_src_', '')
        if name in current_sources:
            del current_sources[name]
            await query.answer(f"✅ Հեռացված՝ {name}", show_alert=True)
            
            keyboard = []
            for n in current_sources.keys():
                keyboard.append([InlineKeyboardButton(f"✅ {n}", callback_data=f'src_{n}')])
            keyboard.append([InlineKeyboardButton("➕ Ավելացնել", callback_data='add_source')])
            keyboard.append([InlineKeyboardButton("➖ Հեռացնել", callback_data='remove_source')])
            keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
            
            await query.edit_message_text(
                f"📰 <b>Աղբյուրներ</b>\n\nԱկտիվ՝ {len(current_sources)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
    
    elif query.data == 'filters':
        preview = ', '.join(current_keywords[:10])
        keyboard = [
            [InlineKeyboardButton("📋 Բոլորը", callback_data='show_keywords')],
            [InlineKeyboardButton("➕ Ավելացնել", callback_data='add_keyword')],
            [InlineKeyboardButton("➖ Հեռացնել", callback_data='remove_keyword')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"🔍 <b>Ֆիլտրեր</b>\n\n{preview}...\n\nՁնդամենը՝ {len(current_keywords)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_keyword':
        context.user_data['waiting_for'] = 'keyword_add'
        await query.edit_message_text(
            "➕ <b>Ավելացնել բառ</b>\n\n"
            "Ուղարկեք բառը՝\n"
            "Օրինակ՝ <code>pashinyan</code>\n\n"
            "/cancel չեղարկել",
            parse_mode='HTML'
        )
    
    elif query.data == 'remove_keyword':
        if not current_keywords:
            await query.answer("Բառեր չկան!", show_alert=True)
            return
        
        keyboard = [[InlineKeyboardButton(f"❌ {kw}", callback_data=f'del_kw_{kw}')] for kw in current_keywords[:15]]
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='filters')])
        
        await query.edit_message_text(
            "➖ <b>Հեռացնել</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('del_kw_'):
        kw = query.data.replace('del_kw_', '')
        if kw in current_keywords:
            current_keywords.remove(kw)
            await query.answer(f"✅ Հեռացված՝ {kw}", show_alert=True)
            
            preview = ', '.join(current_keywords[:10])
            keyboard = [
                [InlineKeyboardButton("📋 Բոլորը", callback_data='show_keywords')],
                [InlineKeyboardButton("➕ Ավելացնել", callback_data='add_keyword')],
                [InlineKeyboardButton("➖ Հեռացնել", callback_data='remove_keyword')],
                [InlineKeyboardButton("« Հետ", callback_data='back')]
            ]
            
            await query.edit_message_text(
                f"🔍 <b>Ֆիլտրեր</b>\n\n{preview}...\n\nՁնդամենը՝ {len(current_keywords)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
    
    elif query.data == 'show_keywords':
        all_kw = ', '.join(current_keywords)
        await query.edit_message_text(
            f"📋 <b>Բոլոր բառերը</b>\n\n{all_kw}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='filters')]]),
            parse_mode='HTML'
        )
    
    elif query.data == 'settings':
        status = "🟢 ON" if monitoring_active else "🔴 OFF"
        lang = "Ռուսերեն" if TRANSLATION_LANG == 'ru' else "Հայերեն"
        
        keyboard = [
            [InlineKeyboardButton(f"{'⏸ Stop' if monitoring_active else '▶️ Start'}", callback_data='toggle')],
            [InlineKeyboardButton("« Հետ", callback_data='back')]
        ]
        
        await query.edit_message_text(
            f"⚙️ <b>Կարգավորումներ</b>\n\n"
            f"Վիճակ՝ {status}\n"
            f"Interval՝ 30 վրկ\n"
            f"Թարգմանություն՝ {lang}\n"
            f"Աղբյուրներ՝ {len(current_sources)}\n"
            f"Բառեր՝ {len(current_keywords)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'toggle':
        monitoring_active = not monitoring_active
        await query.answer(f"✅ {'ON' if monitoring_active else 'OFF'}", show_alert=True)
        await query.edit_message_text(
            f"✅ Monitoring՝ <b>{'ON' if monitoring_active else 'OFF'}</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='settings')]]),
            parse_mode='HTML'
        )
    
    elif query.data == 'digest':
        await query.edit_message_text("🔄 Loading...")
        await send_digest(query)
    
    elif query.data == 'back':
        await query.edit_message_text(
            "🌍 <b>Artak News Monitor</b>",
            reply_markup=get_main_keyboard(),
            parse_mode='HTML'
        )

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    global current_sources, current_keywords
    
    waiting = context.user_data.get('waiting_for')
    
    if waiting == 'source_name':
        context.user_data['new_source_name'] = update.message.text.strip()
        context.user_data['waiting_for'] = 'source_url'
        await update.message.reply_text(
            f"Անուն՝ <code>{context.user_data['new_source_name']}</code>\n\n"
            f"Քայլ 2/2: RSS URL-ը",
            parse_mode='HTML'
        )
    
    elif waiting == 'source_url':
        name = context.user_data.get('new_source_name')
        url = update.message.text.strip()
        
        if not url.startswith('http'):
            await update.message.reply_text("❌ Սխալ URL")
            return
        
        current_sources[name] = url
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Ավելացված՝ {name}",
            reply_markup=get_main_keyboard()
        )
    
    elif waiting == 'keyword_add':
        kw = update.message.text.strip().lower()
        
        if kw in current_keywords:
            await update.message.reply_text(f"⚠️ Արդեն կա՝ {kw}")
            return
        
        current_keywords.append(kw)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Ավելացված՝ {kw}",
            reply_markup=get_main_keyboard()
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel"""
    context.user_data.clear()
    await update.message.reply_text("❌ Չեղարկված", reply_markup=get_main_keyboard())

async def check_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual check"""
    await update.message.reply_text("🔍 Checking...")
    await check_news_job(context)
    await update.message.reply_text("✅ Done", reply_markup=get_main_keyboard())

async def send_digest(query):
    """Show recent news"""
    articles = []
    
    for name, url in current_sources.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
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
        except:
            pass
    
    if not articles:
        await query.edit_message_text(
            "📊 Չկան",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]])
        )
        return
    
    articles.sort(key=lambda x: x['datetime'] or datetime.min, reverse=True)
    
    msg = f"📰 <b>Վերջին {len(articles[:10])}</b>\n\n"
    for i, a in enumerate(articles[:10], 1):
        msg += f"{i}. <b>[{a['source']}]</b> {a['title'][:80]}...\n🔗 {a['link']}\n\n"
    
    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Հետ", callback_data='back')]]),
        parse_mode='HTML',
        disable_web_page_preview=True
    )

async def check_news_job(context: ContextTypes.DEFAULT_TYPE):
    """Check news and send"""
    global sent_articles, monitoring_active
    
    if not CHANNEL_ID or not monitoring_active:
        return
    
    logger.info(f"Checking... (sent: {len(sent_articles)})")
    new = []
    
    for name, url in current_sources.items():
        try:
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:15]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                published = entry.get('published', '')
                summary = entry.get('summary', '') or entry.get('description', '')
                
                import re
                clean_summary = re.sub('<[^<]+?>', '', summary)
                
                text = (title + ' ' + clean_summary).lower()
                aid = f"{name}::{link}"
                
                if aid in sent_articles:
                    continue
                
                if any(kw in text for kw in current_keywords):
                    time_str, dt = format_time_with_timezones(published) if published else ("", None)
                    
                    new.append({
                        'name': name,
                        'title': title,
                        'summary': clean_summary,
                        'link': link,
                        'time_str': time_str,
                        'datetime': dt,
                        'aid': aid
                    })
        except Exception as e:
            logger.error(f"Error {name}: {e}")
    
    new.sort(key=lambda x: x['datetime'] or datetime.min, reverse=True)
    
    for a in new:
        try:
            # Original for main channel
            msg_orig = f"🌍 <b>{a['name']}</b>\n\n{a['title']}\n\n"
            if a['time_str']:
                msg_orig += f"📅 {a['time_str']}\n\n"
            msg_orig += f"🔗 {a['link']}"
            
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=msg_orig,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            # Translated for your channel
            if MY_CHANNEL_ID:
                try:
                    logger.info(f"Translating: {a['title'][:40]}...")
                    
                    tr_title = translate_text(a['title'], TRANSLATION_LANG)
                    tr_summary = ""
                    
                    if a['summary'] and len(a['summary']) > 50:
                        tr_summary = translate_text(a['summary'][:1000], TRANSLATION_LANG)
                    
                    msg_tr = f"🌍 <b>{a['name']}</b>\n\n<b>{tr_title}</b>\n\n"
                    
                    if tr_summary:
                        msg_tr += f"{tr_summary}\n\n"
                    
                    if a['time_str']:
                        msg_tr += f"📅 {a['time_str']}\n\n"
                    
                    msg_tr += f"🔗 {a['link']}"
                    
                    await context.bot.send_message(
                        chat_id=MY_CHANNEL_ID,
                        text=msg_tr,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    
                    logger.info("Translated OK")
                    
                except Exception as e:
                    logger.error(f"Translation error: {e}")
            
            sent_articles.add(a['aid'])
            
            if len(sent_articles) > 300:
                sent_articles = set(list(sent_articles)[-150:])
            
            await asyncio.sleep(3)
            
        except Exception as e:
            logger.error(f"Send error: {e}")
    
    if new:
        logger.info(f"✅ Sent {len(new)}")

async def post_init(application: Application):
    """Init"""
    logger.info("=" * 50)
    logger.info("🚀 STARTING...")
    logger.info("=" * 50)
    
    if not CHANNEL_ID:
        logger.error("❌ CHANNEL_ID not set!")
        return
    
    lang = "Russian" if TRANSLATION_LANG == 'ru' else "Armenian"
    
    logger.info(f"✅ Main Channel: {CHANNEL_ID}")
    logger.info(f"✅ My Channel: {MY_CHANNEL_ID or 'Not set'}")
    logger.info(f"✅ Translation: {lang} ({TRANSLATION_LANG})")
    logger.info(f"✅ Interval: 30s")
    
    application.job_queue.run_repeating(
        check_news_job,
        interval=30,
        first=10,
        name='monitor'
    )
    
    logger.info("=" * 50)
    logger.info("✅ STARTED")
    logger.info("=" * 50)

def main():
    """Main"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    try:
        app = Application.builder().token(TOKEN).post_init(post_init).build()
        
        if not app.job_queue:
            logger.error("❌ No job queue!")
            return
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("cancel", cancel_command))
        app.add_handler(CommandHandler("check", check_news_command))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
        
        logger.info("Starting...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")

if __name__ == '__main__':
    main()
