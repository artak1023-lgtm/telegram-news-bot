import logging
import feedparser
import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
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
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))

# Admin data file
ADMIN_FILE = Path('/tmp/admins.json')

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
WAITING_SOURCE_NAME, WAITING_SOURCE_URL, WAITING_KEYWORD_ADD, WAITING_ADMIN_ID, WAITING_PERSONAL_CHANNEL = range(5)

# Global փոփոխականներ
sent_articles = set()
monitoring_active = True
current_sources = DEFAULT_SOURCES.copy()
current_keywords = DEFAULT_KEYWORDS.copy()
admin_list = set()
admin_notifications = {}  # {user_id: True/False}
personal_channels = {}  # {user_id: channel_id}

def load_admins():
    """Load admin list and personal channels from file"""
    global admin_list, admin_notifications, personal_channels
    try:
        if ADMIN_FILE.exists():
            with open(ADMIN_FILE, 'r') as f:
                data = json.load(f)
                admin_list = set(data.get('admins', []))
                admin_notifications = data.get('notifications', {})
                personal_channels = data.get('personal_channels', {})
                
                # Convert string keys to int
                admin_notifications = {int(k): v for k, v in admin_notifications.items()}
                personal_channels = {int(k): v for k, v in personal_channels.items()}
                
                logger.info(f"Loaded {len(admin_list)} admins, {len(personal_channels)} personal channels")
        
        if OWNER_ID and OWNER_ID != 0:
            admin_list.add(OWNER_ID)
            if OWNER_ID not in admin_notifications:
                admin_notifications[OWNER_ID] = True
                
    except Exception as e:
        logger.error(f"Error loading admins: {e}")
        admin_list = set()
        admin_notifications = {}
        personal_channels = {}
        if OWNER_ID and OWNER_ID != 0:
            admin_list.add(OWNER_ID)
            admin_notifications[OWNER_ID] = True

def save_admins():
    """Save admin list and personal channels to file"""
    try:
        data = {
            'admins': list(admin_list),
            'notifications': {str(k): v for k, v in admin_notifications.items()},
            'personal_channels': {str(k): v for k, v in personal_channels.items()}
        }
        with open(ADMIN_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(admin_list)} admins, {len(personal_channels)} personal channels")
    except Exception as e:
        logger.error(f"Error saving admins: {e}")

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in admin_list

def is_owner(user_id: int) -> bool:
    """Check if user is the owner"""
    return user_id == OWNER_ID

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

def get_main_keyboard(user_id: int):
    """Հիմնական menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("📰 Աղբյուրներ", callback_data='sources')],
        [InlineKeyboardButton("🔍 Ֆիլտրեր", callback_data='filters')],
        [InlineKeyboardButton("⚙️ Կարգավորումներ", callback_data='settings')],
        [InlineKeyboardButton("📊 Վերջին նորություններ", callback_data='digest')],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👥 Ադմիններ", callback_data='admins')])
        keyboard.append([InlineKeyboardButton("📢 Իմ Personal Channel", callback_data='my_channel')])
    
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if OWNER_ID == 0:
        await update.message.reply_text(
            "⚠️ <b>Owner ID-ն սահմանված չէ!</b>\n\n"
            f"Քո User ID-ն՝ <code>{user_id}</code>\n\n"
            "Railway-ում environment variables-ում ավելացրու՝\n"
            "<code>OWNER_ID={user_id}</code>\n\n"
            "Հետո վերսկսիր bot-ը։",
            parse_mode='HTML'
        )
        return
    
    admin_status = ""
    if is_owner(user_id):
        admin_status = "\n👑 Դու Owner ես"
    elif is_admin(user_id):
        admin_status = "\n👤 Դու Admin ես"
    
    personal_channel_info = ""
    if user_id in personal_channels:
        personal_channel_info = f"\n📢 Personal Channel՝ միացված"
    
    msg = (
        f"🌍 <b>Artak News Monitor</b>\n\n"
        f"Բարի գալուստ, @{username}!{admin_status}{personal_channel_info}\n\n"
        f"⚡️ Ավտոմատ monitoring՝ ամեն 30 վայրկյան\n"
        f"📢 Նորությունները ուղարկվում են channel-ին\n"
        f"🎯 Ոչ մի կարևոր նորություն չի բաց մնա\n\n"
        f"Օգտագործեք menu-ն՝"
    )
    
    await update.message.reply_text(
        msg,
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback query handler"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    global monitoring_active, current_sources, current_keywords
    
    # Admin-only actions
    admin_only_actions = ['admins', 'add_admin', 'remove_admin', 'list_admins', 
                          'toggle_notifications', 'sources', 'add_source', 'remove_source',
                          'filters', 'add_keyword', 'remove_keyword', 'my_channel',
                          'add_personal_channel', 'remove_personal_channel']
    
    if any(query.data.startswith(action) for action in admin_only_actions):
        if not is_admin(user_id):
            await query.answer("❌ Միայն admin-ները կարող են օգտագործել", show_alert=True)
            return
    
    if query.data == 'my_channel':
        has_channel = user_id in personal_channels
        
        keyboard = []
        
        if has_channel:
            channel_id = personal_channels[user_id]
            keyboard.append([InlineKeyboardButton("📋 Տեսնել իմ channel-ը", callback_data='view_personal_channel')])
            keyboard.append([InlineKeyboardButton("❌ Հեռացնել իմ channel-ը", callback_data='remove_personal_channel')])
            status_text = f"✅ Միացված է\n\n📢 Channel ID՝ <code>{channel_id}</code>"
        else:
            keyboard.append([InlineKeyboardButton("➕ Ավելացնել իմ channel-ը", callback_data='add_personal_channel')])
            status_text = "❌ Չի ավելացված"
        
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        await query.edit_message_text(
            f"📢 <b>Personal Channel</b>\n\n"
            f"Վիճակ՝ {status_text}\n\n"
            f"<i>Personal channel-ում դու կստանաս միայն նորություններ, "
            f"առանց admin panel հաղորդագրությունների։</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_personal_channel':
        context.user_data['waiting_for'] = 'personal_channel'
        await query.edit_message_text(
            "➕ <b>Ավելացնել Personal Channel</b>\n\n"
            "<b>Քայլ 1:</b> Ստեղծիր private channel Telegram-ում\n"
            "   (օրինակ՝ 'Artak News')\n\n"
            "<b>Քայլ 2:</b> Bot-ին admin արա այդ channel-ում\n"
            "   • Channel Settings → Administrators → Add Admin\n"
            "   • Գտիր @your_bot_username\n"
            "   • Տուր 'Post messages' permission\n\n"
            "<b>Քայլ 3:</b> Forward արա մի հաղորդագրություն channel-ից "
            "[@getidsbot](https://t.me/getidsbot) bot-ին\n\n"
            "<b>Քայլ 4:</b> Ուղարկիր channel-ի ID-ն այստեղ\n"
            "   (օրինակ՝ <code>-1001234567890</code>)\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
    
    elif query.data == 'view_personal_channel':
        if user_id in personal_channels:
            channel_id = personal_channels[user_id]
            keyboard = [[InlineKeyboardButton("« Հետ", callback_data='my_channel')]]
            
            await query.edit_message_text(
                f"📢 <b>Քո Personal Channel</b>\n\n"
                f"Channel ID՝ <code>{channel_id}</code>\n\n"
                f"✅ Նորությունները ուղարկվում են՝\n"
                f"• Main Channel ({CHANNEL_ID})\n"
                f"• Քո Personal Channel ({channel_id})\n\n"
                f"💡 <i>Կարող ես mute անել այս bot-ի chat-ը և "
                f"տեսնել միայն նորությունները քո channel-ում։</i>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
    
    elif query.data == 'remove_personal_channel':
        if user_id in personal_channels:
            del personal_channels[user_id]
            save_admins()
            
            await query.answer("✅ Personal channel-ը հեռացված է", show_alert=True)
            
            keyboard = [
                [InlineKeyboardButton("➕ Ավելացնել իմ channel-ը", callback_data='add_personal_channel')],
                [InlineKeyboardButton("« Հետ", callback_data='back')]
            ]
            
            await query.edit_message_text(
                f"📢 <b>Personal Channel</b>\n\n"
                f"Վիճակ՝ ❌ Չի ավելացված\n\n"
                f"<i>Personal channel-ում դու կստանաս միայն նորություններ, "
                f"առանց admin panel հաղորդագրությունների։</i>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
    
    elif query.data == 'admins':
        keyboard = [
            [InlineKeyboardButton("➕ Ավելացնել admin", callback_data='add_admin')],
            [InlineKeyboardButton("📋 Admin-ների ցուցակ", callback_data='list_admins')],
            [InlineKeyboardButton(
                f"{'🔔 Ծանուցումներ ON' if admin_notifications.get(user_id, True) else '🔕 Ծանուցումներ OFF'}", 
                callback_data='toggle_notifications'
            )],
        ]
        
        if is_owner(user_id):
            keyboard.insert(1, [InlineKeyboardButton("➖ Հեռացնել admin", callback_data='remove_admin')])
        
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        # Count personal channels
        channels_count = len(personal_channels)
        
        await query.edit_message_text(
            f"👥 <b>Admin Management</b>\n\n"
            f"Ընդհանուր admin-ներ՝ {len(admin_list)}\n"
            f"Personal channels՝ {channels_count}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'add_admin':
        context.user_data['waiting_for'] = 'admin_id'
        await query.edit_message_text(
            "➕ <b>Ավելացնել նոր Admin</b>\n\n"
            "Քայլ 1: Նոր admin-ը պետք է գրի bot-ին /start\n"
            "Քայլ 2: Նա կստանա իր User ID-ն\n"
            "Քայլ 3: Ուղարկիր այդ User ID-ն այստեղ\n\n"
            "Կամ /cancel չեղարկելու համար",
            parse_mode='HTML'
        )
    
    elif query.data == 'remove_admin':
        if not is_owner(user_id):
            await query.answer("❌ Միայն Owner-ը կարող է հեռացնել admin-ներ", show_alert=True)
            return
        
        keyboard = []
        for admin_id in admin_list:
            if admin_id != OWNER_ID:
                has_channel = "📢" if admin_id in personal_channels else ""
                keyboard.append([InlineKeyboardButton(
                    f"❌ Admin ID: {admin_id} {has_channel}", 
                    callback_data=f'del_admin_{admin_id}'
                )])
        
        if not keyboard:
            await query.answer("Հեռացնելու admin-ներ չկան", show_alert=True)
            return
        
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='admins')])
        
        await query.edit_message_text(
            "➖ <b>Հեռացնել Admin</b>\n\n"
            "📢 = ունի personal channel\n\n"
            "Ընտրեք հեռացվող admin-ին՝",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('del_admin_'):
        if not is_owner(user_id):
            await query.answer("❌ Միայն Owner-ը կարող է հեռացնել admin-ներ", show_alert=True)
            return
        
        admin_id = int(query.data.replace('del_admin_', ''))
        if admin_id in admin_list:
            admin_list.remove(admin_id)
            if admin_id in admin_notifications:
                del admin_notifications[admin_id]
            if admin_id in personal_channels:
                del personal_channels[admin_id]
            save_admins()
            await query.answer(f"✅ Admin {admin_id} հեռացված է", show_alert=True)
            
            keyboard = [
                [InlineKeyboardButton("➕ Ավելացնել admin", callback_data='add_admin')],
                [InlineKeyboardButton("➖ Հեռացնել admin", callback_data='remove_admin')],
                [InlineKeyboardButton("📋 Admin-ների ցուցակ", callback_data='list_admins')],
                [InlineKeyboardButton("« Հետ", callback_data='back')]
            ]
            
            channels_count = len(personal_channels)
            
            await query.edit_message_text(
                f"👥 <b>Admin Management</b>\n\n"
                f"Ընդհանուր admin-ներ՝ {len(admin_list)}\n"
                f"Personal channels՝ {channels_count}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
    
    elif query.data == 'list_admins':
        admin_info = []
        for admin_id in admin_list:
            role = "👑 Owner" if admin_id == OWNER_ID else "👤 Admin"
            notif = "🔔" if admin_notifications.get(admin_id, True) else "🔕"
            channel = "📢" if admin_id in personal_channels else ""
            admin_info.append(f"{role} {notif} {channel} - <code>{admin_id}</code>")
        
        msg = (
            "👥 <b>Admin-ների ցուցակ</b>\n\n" + 
            "\n".join(admin_info) +
            "\n\n🔔 = ծանուցումներ ON\n"
            "🔕 = ծանուցումներ OFF\n"
            "📢 = ունի personal channel"
        )
        keyboard = [[InlineKeyboardButton("« Հետ", callback_data='admins')]]
        
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'toggle_notifications':
        current = admin_notifications.get(user_id, True)
        admin_notifications[user_id] = not current
        save_admins()
        
        status = "միացված" if admin_notifications[user_id] else "անջատված"
        await query.answer(f"✅ Ծանուցումները {status} են", show_alert=True)
        
        keyboard = [
            [InlineKeyboardButton("➕ Ավելացնել admin", callback_data='add_admin')],
            [InlineKeyboardButton("📋 Admin-ների ցուցակ", callback_data='list_admins')],
            [InlineKeyboardButton(
                f"{'🔔 Ծանուցումներ ON' if admin_notifications[user_id] else '🔕 Ծանուցումներ OFF'}", 
                callback_data='toggle_notifications'
            )],
        ]
        
        if is_owner(user_id):
            keyboard.insert(1, [InlineKeyboardButton("➖ Հեռացնել admin", callback_data='remove_admin')])
        
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
        channels_count = len(personal_channels)
        
        await query.edit_message_text(
            f"👥 <b>Admin Management</b>\n\n"
            f"Ընդհանուր admin-ներ՝ {len(admin_list)}\n"
            f"Personal channels՝ {channels_count}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'sources':
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
            
            await notify_admins(context, f"📰 Աղբյուրը հեռացված է՝ {source_name}")
            
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
            
            await notify_admins(context, f"🔍 Ֆիլտրը հեռացված է՝ {keyword}")
            
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
        channel_info = f"📢 Channel՝ {CHANNEL_ID}" if CHANNEL_ID else "⚠️ Channel չի սահմանված"
        
        keyboard = []
        
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton(
                f"{'⏸ Դադարեցնել' if monitoring_active else '▶️ Միացնել'}", 
                callback_data='toggle'
            )])
        
        keyboard.append([InlineKeyboardButton("« Հետ", callback_data='back')])
        
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
        
        await notify_admins(context, f"⚙️ Monitoring-ը {status} է")
    
    elif query.data == 'digest':
        await query.edit_message_text("🔄 Հավաքում եմ նորություններ...")
        await send_digest(query)
    
    elif query.data == 'back':
        await query.edit_message_text(
            "🌍 <b>Artak News Monitor</b>\n\nՈւղտրեք գործողությունը՝",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Send notification to all admins who have notifications enabled (to bot chat only, not personal channels)"""
    for admin_id in admin_list:
        if admin_notifications.get(admin_id, True):
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📢 <b>Admin Notification</b>\n\n{message}",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error notifying admin {admin_id}: {e}")

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    global current_sources, current_keywords, personal_channels
    
    user_id = update.effective_user.id
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'personal_channel':
        if not is_admin(user_id):
            await update.message.reply_text("❌ Միայն admin-ները կարող են ավելացնել")
            return
        
        try:
            channel_id = update.message.text.strip()
            
            # Validate format
            if not channel_id.startswith('-') or not channel_id[1:].isdigit():
                await update.message.reply_text(
                    "❌ Սխալ ֆորմատ։\n\n"
                    "Channel ID-ն պետք է լինի negative թիվ՝\n"
                    "Օրինակ՝ <code>-1001234567890</code>\n\n"
                    "Փորձեք նորից կամ /cancel չեղարկելու համար",
                    parse_mode='HTML'
                )
                return
            
            # Test if bot can send to this channel
            try:
                test_msg = await context.bot.send_message(
                    chat_id=channel_id,
                    text="✅ Bot-ը հաջողությամբ միացավ այս channel-ին!\n\n"
                         "Այս հաղորդագրությունը կարող ես ջնջել։"
                )
                
                # Save the channel
                personal_channels[user_id] = channel_id
                save_admins()
                
                await update.message.reply_text(
                    f"✅ Personal channel-ը հաջողությամբ ավելացվել է!\n\n"
                    f"📢 Channel ID՝ <code>{channel_id}</code>\n\n"
                    f"Այժմ բոլոր նորությունները կուղարկվեն և՛ main channel-ին, "
                    f"և՛ քո personal channel-ին։\n\n"
                    f"💡 <i>Կարող ես mute անել այս bot-ի chat-ը և "
                    f"տեսնել միայն նորությունները քո channel-ում։</i>",
                    reply_markup=get_main_keyboard(user_id),
                    parse_mode='HTML'
                )
                
                # Notify other admins
                await notify_admins(context, f"📢 Admin {user_id}-ը ավելացրել է personal channel")
                
                context.user_data.clear()
                
            except Exception as e:
                error_msg = str(e)
                if "Chat not found" in error_msg:
                    await update.message.reply_text(
                        "❌ Channel-ը չի գտնվել։\n\n"
                        "Համոզվիր որ՝\n"
                        "1️⃣ Bot-ը admin է channel-ում\n"
                        "2️⃣ Bot-ը ունի 'Post messages' permission\n"
                        "3️⃣ Channel ID-ն ճիշտ է\n\n"
                        "Փորձեք նորից կամ /cancel չեղարկելու համար"
                    )
                elif "Forbidden" in error_msg:
                    await update.message.reply_text(
                        "❌ Bot-ը չի կարող գրել այս channel-ում։\n\n"
                        "Համոզվիր որ՝\n"
                        "1️⃣ Bot-ը admin է channel-ում\n"
                        "2️⃣ Bot-ը ունի 'Post messages' permission\n\n"
                        "Փորձեք նորից կամ /cancel չեղարկելու համար"
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Սխալ՝ {error_msg}\n\n"
                        "Փորձեք նորից կամ /cancel չեղարկելու համար"
                    )
                    
        except Exception as e:
            await update.message.reply_text(
                f"❌ Սխալ՝ {e}\n\n"
                "Փորձեք նորից կամ /cancel չեղարկելու համար"
            )
    
    elif waiting_for == 'admin_id':
        if not is_admin(user_id):
            await update.message.reply_text("❌ Միայն admin-ները կարող են ավելացնել admin")
            return
        
        try:
            new_admin_id = int(update.message.text.strip())
            
            if new_admin_id in admin_list:
                await update.message.reply_text(
                    f"⚠️ User {new_admin_id}-ն արդեն admin է։",
                    reply_markup=get_main_keyboard(user_id)
                )
                context.user_data.clear()
                return
            
            admin_list.add(new_admin_id)
            admin_notifications[new_admin_id] = True
            save_admins()
            
            await update.message.reply_text(
                f"✅ Նոր admin-ը ավելացված է!\n\n"
                f"👤 User ID: <code>{new_admin_id}</code>\n"
                f"🔔 Ծանուցումներ: Միացված\n\n"
                f"Ընդհանուր admin-ներ՝ {len(admin_list)}",
                reply_markup=get_main_keyboard(user_id),
                parse_mode='HTML'
            )
            
            try:
                await context.bot.send_message(
                    chat_id=new_admin_id,
                    text="🎉 <b>Դու admin ես դարձել!</b>\n\n"
                         "Այժմ դու կարող ես՝\n"
                         "• Ավելացնել/հեռացնել աղբյուրներ\n"
                         "• Ավելացնել/հեռացնել ֆիլտրեր\n"
                         "• Ստանալ նորությունների ծանուցումներ\n"
                         "• Ավելացնել քո personal channel\n\n"
                         "Գրիր /start և օգտագործիր menu-ն։",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Could not notify new admin: {e}")
            
            await notify_admins(context, f"👥 Նոր admin ավելացվել է՝ {new_admin_id}")
            
            context.user_data.clear()
            
        except ValueError:
            await update.message.reply_text(
                "❌ Սխալ ֆորմատ։ Ուղարկեք User ID թիվը\n\n"
                "Փորձեք նորից կամ /cancel չեղարկելու համար"
            )
    
    elif waiting_for == 'source_name':
        if not is_admin(user_id):
            await update.message.reply_text("❌ Միայն admin-ները կարող են ավելացնել")
            return
            
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
        if not is_admin(user_id):
            await update.message.reply_text("❌ Միայն admin-ները կարող են ավելացնել")
            return
            
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
            reply_markup=get_main_keyboard(user_id)
        )
        
        await notify_admins(context, f"📰 Նոր աղբյուր ավելացվել է՝ {source_name}")
    
    elif waiting_for == 'keyword_add':
        if not is_admin(user_id):
            await update.message.reply_text("❌ Միայն admin-ները կարող են ավելացնել")
            return
            
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
            reply_markup=get_main_keyboard(user_id)
        )
        
        await notify_admins(context, f"🔍 Նոր ֆիլտր ավելացվել է՝ {keyword}")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing operation"""
    user_id = update.effective_user.id
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Գործողությունը չեղարկված է։",
        reply_markup=get_main_keyboard(user_id)
    )

async def check_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual news check command"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Միայն admin-ները կարող են ստուգել")
        return
    
    await update.message.reply_text("🔍 Ստուգում եմ նորությունները...")
    await check_news_job(context)
    await update.message.reply_text(
        "✅ Ստուգումը ավարտված է։",
        reply_markup=get_main_keyboard(user_id)
    )

async def my_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user's Telegram ID"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Անուն չկա"
    first_name = update.effective_user.first_name or ""
    
    admin_status = ""
    if is_owner(user_id):
        admin_status = "\n\n👑 Դու Owner ես"
    elif is_admin(user_id):
        admin_status = "\n\n👤 Դու Admin ես"
    
    channel_status = ""
    if user_id in personal_channels:
        channel_status = f"\n📢 Personal Channel՝ {personal_channels[user_id]}"
    
    await update.message.reply_text(
        f"👤 <b>Քո տեղեկությունները</b>\n\n"
        f"Անուն՝ {first_name}\n"
        f"Username՝ @{username}\n"
        f"User ID՝ <code>{user_id}</code>{admin_status}{channel_status}",
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
                
                if article_id in sent_articles:
                    continue
                
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
    
    new_articles_sorted = sorted(
        [a for a in new_articles if a['datetime']],
        key=lambda x: x['datetime'],
        reverse=True
    )
    
    for article in new_articles_sorted:
        try:
            msg = f"🌍 <b>{article['name']}</b>\n\n{article['title']}\n\n"
            if article['time_str']:
                msg += f"📅 {article['time_str']}\n\n"
            msg += f"🔗 {article['link']}"
            
            # Send to main channel
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=msg,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            # Send to admins' personal channels
            for admin_id in admin_list:
                if admin_id in personal_channels:
                    try:
                        await context.bot.send_message(
                            chat_id=personal_channels[admin_id],
                            text=msg,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                        logger.info(f"Sent to admin {admin_id}'s personal channel")
                    except Exception as e:
                        logger.error(f"Error sending to admin {admin_id}'s channel: {e}")
            
            # Also send to admins who have notifications enabled (in bot chat)
            for admin_id in admin_list:
                if admin_notifications.get(admin_id, True):
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=msg,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logger.error(f"Error sending to admin {admin_id}: {e}")
            
            sent_articles.add(article['article_id'])
            
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
    """Initialize bot"""
    logger.info("=" * 70)
    logger.info("🚀 BOT STARTING...")
    logger.info("=" * 70)
    
    load_admins()
    
    if OWNER_ID == 0:
        logger.error("❌ OWNER_ID not set!")
        logger.error("Set environment variable: OWNER_ID=your_telegram_user_id")
        logger.info("=" * 70)
        return
    
    if not CHANNEL_ID:
        logger.error("❌ CHANNEL_ID not set!")
        logger.error("Set environment variable: CHANNEL_ID=-1001234567890")
        logger.info("=" * 70)
        return
    
    logger.info(f"✅ Owner ID: {OWNER_ID}")
    logger.info(f"✅ Channel ID: {CHANNEL_ID}")
    logger.info(f"✅ Admin count: {len(admin_list)}")
    logger.info(f"✅ Personal channels: {len(personal_channels)}")
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
    logger.info("✅ MONITORING STARTED")
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
