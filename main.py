import os
import json
import logging
from datetime import datetime
import pytz
import feedparser
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'supersecret123')

DATA_FILE = 'data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'sources': [], 'hashtags': [], 'monitoring': False, 'last_seen': {}, 'user_id': None}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

def get_main_menu_keyboard():
    keyboard = [
        ["Ավելացնել աղբյուր", "Ավելացնել հաշթագ"],
        ["Միացնել մոնիտորինգ", "Անջատել մոնիտորինգ"],
        ["Ցուցադրել կարգավորումները"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    data['user_id'] = update.message.from_user.id
    save_data(data)
    keyboard = get_main_menu_keyboard()
    await update.message.reply_text('Բոտը սկսված է! Օգտագործիր կոճակները:', reply_markup=keyboard)

async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /add_source <RSS URL>')
        return
    url = context.args[0]
    data = load_data()
    if url not in data['sources']:
        data['sources'].append(url)
        save_data(data)
        await update.message.reply_text(f'Աղբյուրը ավելացված է: {url}')
    else:
        await update.message.reply_text('Աղբյուրը արդեն կա:')

async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /remove_source <RSS URL>')
        return
    url = context.args[0]
    data = load_data()
    if url in data['sources']:
        data['sources'].remove(url)
        save_data(data)
        await update.message.reply_text(f'Աղբյուրը հեռացված է: {url}')
    else:
        await update.message.reply_text('Աղբյուրը չի գտնվել:')

async def add_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /add_hashtag <tag>')
        return
    tag = context.args[0].lower()
    data = load_data()
    if tag not in data['hashtags']:
        data['hashtags'].append(tag)
        save_data(data)
        await update.message.reply_text(f'Հաշթագը ավելացված է: {tag}')
    else:
        await update.message.reply_text('Հաշթագը արդեն կա:')

async def remove_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /remove_hashtag <tag>')
        return
    tag = context.args[0].lower()
    data = load_data()
    if tag in data['hashtags']:
        data['hashtags'].remove(tag)
        save_data(data)
        await update.message.reply_text(f'Հաշթագը հեռացված է: {tag}')
    else:
        await update.message.reply_text('Հաշթագը չի գտնվել:')

async def start_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if data['monitoring']:
        await update.message.reply_text('Մոնիտորինգը արդեն միացված է:')
        return
    data['monitoring'] = True
    save_data(data)
    context.job_queue.run_repeating(check_news, interval=60, first=0)
    await update.message.reply_text('Մոնիտորինգը սկսված է: Ամեն րոպե կստուգի:')

async def stop_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not data['monitoring']:
        await update.message.reply_text('Մոնիտորինգը արդեն կանգնած է:')
        return
    data['monitoring'] = False
    save_data(data)
    current_jobs = context.job_queue.jobs()
    for job in current_jobs:
        job.schedule_removal()
    await update.message.reply_text('Մոնիտորինգը կանգնած է:')

async def check_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not data['monitoring']:
        return
    for source in data['sources']:
        feed = feedparser.parse(source)
        last_seen = data['last_seen'].get(source, {})
        new_last_seen = {}
        for entry in feed.entries:
            guid = entry.get('guid', entry.link)
            if guid in last_seen:
                continue
            title = entry.title.lower()
            desc = entry.get('description', '').lower()
            hashtags = [tag for tag in data['hashtags'] if tag in title or tag in desc]
            if hashtags:
                pubdate_str = entry.published if 'published' in entry else entry.updated
                pubdate = feedparser._parse_date(pubdate_str)
                utc_time = datetime(*pubdate[:6], tzinfo=pytz.utc)
                arm_time = utc_time.astimezone(pytz.timezone('Asia/Yerevan'))
                message = f"{entry.title}\n{entry.get('description', 'No desc')[:200]}...\n{entry.link}\n🇺🇸 {utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n🇦🇲 {arm_time.strftime('%Y-%m-%d %H:%M:%S Asia/Yerevan')}"
                await context.bot.send_message(chat_id=CHANNEL_ID, text=message)
                if data['user_id']:
                    await context.bot.send_message(chat_id=data['user_id'], text=message)
            new_last_seen[guid] = True
        data['last_seen'][source] = new_last_seen
    save_data(data)

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if text == "Ավելացնել աղբյուր":
        await update.message.reply_text("Գրիր /add_source <RSS URL>")
    elif text == "Ավելացնել հաշթագ":
        await update.message.reply_text("Գրիր /add_hashtag <բառ>")
    elif text == "Միացնել մոնիտորինգ":
        await start_monitor(update, context)
    elif text == "Անջատել մոնիտորինգ":
        await stop_monitor(update, context)
    elif text == "Ցուցադրել կարգավորումները":
        data = load_data()
        sources = "\n".join(data['sources']) or "Չկա"
        hashtags = ", ".join(data['hashtags']) or "Չկա"
        status = "միացված" if data['monitoring'] else "անջատված"
        msg = f"Աղբյուրներ:\n{sources}\n\nՀաշթագեր: {hashtags}\n\nՄոնիտորինգը: {status}"
        await update.message.reply_text(msg)

application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("add_source", add_source))
application.add_handler(CommandHandler("remove_source", remove_source))
application.add_handler(CommandHandler("add_hashtag", add_hashtag))
application.add_handler(CommandHandler("remove_hashtag", remove_hashtag))
application.add_handler(CommandHandler("start_monitor", start_monitor))
application.add_handler(CommandHandler("stop_monitor", stop_monitor))
application.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, handle_menu_buttons))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    await application.start()
    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if domain:
        url = f"https://{domain}/{TOKEN}"
        await application.bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET)
        logger.info(f"Webhook set to {url}")
    yield
    await application.stop()
    await application.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post(f"/{TOKEN}")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            raise HTTPException(403, "Forbidden")
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}
