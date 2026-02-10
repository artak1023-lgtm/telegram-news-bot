import os
import json
import logging
from datetime import datetime
import pytz
import feedparser
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN not set in Railway variables")

CHANNEL_ID = os.getenv('CHANNEL_ID')  # @channel կամ -100xxxxxxxxxx
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'supersecret123')  # ինքդ փոխիր, եթե ուզես

DATA_FILE = 'data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            'sources': [],
            'hashtags': [],
            'monitoring': False,
            'last_seen': {},
            'user_id': None
        }

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Telegram handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    data['user_id'] = update.effective_user.id
    save_data(data)
    await update.message.reply_text(
        'Բոտը պատրաստ է:\n'
        'Հրամաններ՝\n'
        '/add_source <RSS URL>\n'
        '/remove_source <URL>\n'
        '/add_hashtag <բառ>\n'
        '/remove_hashtag <բառ>\n'
        '/start_monitor\n'
        '/stop_monitor'
    )

async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օրինակ՝ /add_source https://news.am/rss.xml')
        return
    url = context.args[0]
    data = load_data()
    if url not in data['sources']:
        data['sources'].append(url)
        save_data(data)
        await update.message.reply_text(f'Ավելացվեց → {url}')
    else:
        await update.message.reply_text('Արդեն կա այդ աղբյուրը')

async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օրինակ՝ /remove_source https://news.am/rss.xml')
        return
    url = context.args[0]
    data = load_data()
    if url in data['sources']:
        data['sources'].remove(url)
        save_data(data)
        await update.message.reply_text(f'Հեռացվեց → {url}')
    else:
        await update.message.reply_text('Չգտա այդ աղբյուրը')

async def add_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օրինակ՝ /add_hashtag հայաստան')
        return
    tag = context.args[0].strip().lower()
    data = load_data()
    if tag not in data['hashtags']:
        data['hashtags'].append(tag)
        save_data(data)
        await update.message.reply_text(f'Ավելացվեց հաշթագ → #{tag}')
    else:
        await update.message.reply_text('Արդեն կա այդ հաշթագը')

async def remove_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օրինակ՝ /remove_hashtag հայաստան')
        return
    tag = context.args[0].strip().lower()
    data = load_data()
    if tag in data['hashtags']:
        data['hashtags'].remove(tag)
        save_data(data)
        await update.message.reply_text(f'Հեռացվեց → #{tag}')
    else:
        await update.message.reply_text('Չգտա այդ հաշթագը')

async def start_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if data['monitoring']:
        await update.message.reply_text('Մոնիտորինգը արդեն միացված է')
        return
    data['monitoring'] = True
    save_data(data)
    context.job_queue.run_repeating(check_news, interval=60, first=10)
    await update.message.reply_text('Մոնիտորինգը միացավ (ամեն 60 վայրկյան)')

async def stop_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not data['monitoring']:
        await update.message.reply_text('Մոնիտորինգը արդեն անջատված է')
        return
    data['monitoring'] = False
    save_data(data)
    for job in context.job_queue.jobs():
        job.schedule_removal()
    await update.message.reply_text('Մոնիտորինգը անջատվեց')

async def check_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not data['monitoring']:
        return
    for source in data['sources']:
        try:
            feed = feedparser.parse(source)
            if feed.bozo:
                logger.warning(f"RSS parse error for {source}: {feed.bozo_exception}")
                continue
            last_seen = data['last_seen'].get(source, {})
            new_last_seen = last_seen.copy()
            for entry in feed.entries:
                guid = entry.get('guid') or entry.get('link')
                if not guid or guid in last_seen:
                    continue
                title_lower = (entry.title or '').lower()
                desc_lower = (entry.get('description') or '').lower()
                matched = [t for t in data['hashtags'] if t in title_lower or t in desc_lower]
                if matched:
                    pub_str = entry.get('published') or entry.get('updated')
                    if pub_str:
                        parsed = feedparser._parse_date(pub_str)
                        if parsed:
                            utc_dt = datetime(*parsed[:6], tzinfo=pytz.utc)
                            arm_dt = utc_dt.astimezone(pytz.timezone('Asia/Yerevan'))
                            message = (
                                f"**{entry.title}**\n\n"
                                f"{(entry.get('description') or 'No description')[:400]}...\n\n"
                                f"🔗 {entry.link}\n\n"
                                f"🇺🇸 {utc_dt.strftime('%Y-%m-%d %H:%M UTC')}\n"
                                f"🇦🇲 {arm_dt.strftime('%Y-%m-%d %H:%M')}"
                            )
                            await context.bot.send_message(
                                chat_id=CHANNEL_ID,
                                text=message,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                            if data['user_id']:
                                await context.bot.send_message(
                                    chat_id=data['user_id'],
                                    text=message,
                                    parse_mode='Markdown',
                                    disable_web_page_preview=True
                                )
                new_last_seen[guid] = True
            data['last_seen'][source] = new_last_seen
        except Exception as e:
            logger.error(f"Error processing {source}: {e}")
    save_data(data)

# Application setup
application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("add_source", add_source))
application.add_handler(CommandHandler("remove_source", remove_source))
application.add_handler(CommandHandler("add_hashtag", add_hashtag))
application.add_handler(CommandHandler("remove_hashtag", remove_hashtag))
application.add_handler(CommandHandler("start_monitor", start_monitor))
application.add_handler(CommandHandler("stop_monitor", stop_monitor))

# FastAPI + lifespan (deprecation-ից խուսափելու համար)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await application.initialize()
    await application.start()

    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if domain:
        webhook_url = f"https://{domain}/{TOKEN}"
        await application.bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES
        )
        logger.info(f"Webhook հաջողությամբ set եղավ → {webhook_url}")
    else:
        logger.warning("RAILWAY_PUBLIC_DOMAIN չի գտնվել — webhook չի set եղել")

    yield

    # Shutdown
    await application.stop()
    await application.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post(f"/{TOKEN}")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        if update:
            await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500)

@app.get("/")
async def root():
    return {"status": "Telegram News Bot is running"}
