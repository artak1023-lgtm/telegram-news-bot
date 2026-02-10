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

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN not set!")

CHANNEL_ID = os.getenv('CHANNEL_ID')  # պետք է լինի -100xxxxxxxxxx
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'supersecret123')

DATA_FILE = 'data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info("data.json չգտնվեց → նոր է ստեղծվում")
        return {'sources': [], 'hashtags': [], 'monitoring': False, 'last_seen': {}, 'user_id': None}
    except Exception as e:
        logger.error(f"data.json բացելու սխալ: {e}")
        return {'sources': [], 'hashtags': [], 'monitoring': False, 'last_seen': {}, 'user_id': None}

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"data.json պահպանելու սխալ: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    data['user_id'] = update.effective_user.id
    save_data(data)
    await update.message.reply_text(
        'Բոտը աշխատում է!\n'
        'Հրամաններ:\n'
        '/add_source <RSS URL>\n'
        '/remove_source <URL>\n'
        '/add_hashtag <բառ>\n'
        '/remove_hashtag <բառ>\n'
        '/start_monitor\n'
        '/stop_monitor'
    )

async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /add_source <RSS URL>')
        return
    url = context.args[0].strip()
    data = load_data()
    if url not in data['sources']:
        data['sources'].append(url)
        save_data(data)
        await update.message.reply_text(f'Ավելացվեց: {url}')
    else:
        await update.message.reply_text('Արդեն կա')

async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /remove_source <URL>')
        return
    url = context.args[0].strip()
    data = load_data()
    if url in data['sources']:
        data['sources'].remove(url)
        save_data(data)
        await update.message.reply_text(f'Հեռացվեց: {url}')
    else:
        await update.message.reply_text('Չգտա այդ աղբյուրը')

async def add_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /add_hashtag <բառ>')
        return
    tag = context.args[0].lower().strip()
    data = load_data()
    if tag not in data['hashtags']:
        data['hashtags'].append(tag)
        save_data(data)
        await update.message.reply_text(f'Ավելացվեց: {tag}')
    else:
        await update.message.reply_text('Արդեն կա')

async def remove_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Օգտագործիր /remove_hashtag <բառ>')
        return
    tag = context.args[0].lower().strip()
    data = load_data()
    if tag in data['hashtags']:
        data['hashtags'].remove(tag)
        save_data(data)
        await update.message.reply_text(f'Հեռացվեց: {tag}')
    else:
        await update.message.reply_text('Չգտա այդ հաշթագը')

async def start_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if data['monitoring']:
        await update.message.reply_text('Արդեն միացված է')
        return
    data['monitoring'] = True
    save_data(data)
    # Անունով job գրանցում՝ հետո հեշտ հեռացնելու համար
    context.job_queue.run_repeating(
        check_news,
        interval=300,      # 5 րոպե՝ Railway-ի անվճար տարբերակում ավելի կայուն
        first=5,
        name="news_monitor_job"
    )
    logger.info("news_monitor_job գրանցվեց (interval=300 վայրկյան)")
    await update.message.reply_text('Մոնիտորինգը միացավ (ամեն 5 րոպե)')

async def stop_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not data['monitoring']:
        await update.message.reply_text('Արդեն անջատված է')
        return
    data['monitoring'] = False
    save_data(data)
    
    # Հեռացնել job-ը անունով
    jobs = context.job_queue.get_jobs_by_name("news_monitor_job")
    for job in jobs:
        job.schedule_removal()
        logger.info("news_monitor_job-ը հեռացվեց")
    await update.message.reply_text('Մոնիտորինգը անջատվեց')

async def check_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("check_news սկսվեց")
    data = load_data()
    if not data['monitoring']:
        logger.info("Մոնիտորինգը անջատված է → դադարեցնում եմ")
        return
    
    logger.info(f"Ստուգվում է {len(data['sources'])} աղբյուր")
    for source in data['sources']:
        try:
            feed = feedparser.parse(source)
            if feed.bozo:
                logger.warning(f"RSS parse error {source}: {feed.bozo_exception}")
                continue
            
            last_seen = data['last_seen'].get(source, {})
            new_last_seen = last_seen.copy()
            
            for entry in feed.entries:
                guid = entry.get('guid') or entry.get('link')
                if not guid or guid in last_seen:
                    continue
                
                title = (entry.title or '').lower()
                desc = (entry.get('description') or '').lower()
                matched = [t for t in data['hashtags'] if t in title or t in desc]
                
                if matched:
                    pub_str = entry.get('published') or entry.get('updated')
                    if pub_str:
                        dt = feedparser._parse_date(pub_str)
                        if dt:
                            utc = datetime(*dt[:6], tzinfo=pytz.utc)
                            arm = utc.astimezone(pytz.timezone('Asia/Yerevan'))
                            msg = (
                                f"**{entry.title}**\n"
                                f"{(entry.get('description') or 'No desc')[:400]}...\n\n"
                                f"🔗 {entry.link}\n\n"
                                f"🇺🇸 {utc.strftime('%Y-%m-%d %H:%M UTC')}\n"
                                f"🇦🇲 {arm.strftime('%Y-%m-%d %H:%M')}"
                            )
                            try:
                                await context.bot.send_message(
                                    chat_id=CHANNEL_ID,
                                    text=msg,
                                    parse_mode='Markdown',
                                    disable_web_page_preview=True
                                )
                                logger.info(f"Ուղարկվեց channel-ին: {entry.title[:50]}...")
                                
                                if data['user_id']:
                                    await context.bot.send_message(
                                        chat_id=data['user_id'],
                                        text=msg,
                                        parse_mode='Markdown',
                                        disable_web_page_preview=True
                                    )
                                    logger.info(f"Ուղարկվեց user-ին: {entry.title[:50]}...")
                            except Exception as send_err:
                                logger.error(f"send_message սխալ: {send_err}")
                
                new_last_seen[guid] = True
            
            data['last_seen'][source] = new_last_seen
        
        except Exception as e:
            logger.error(f"check_news սխալ {source}-ում: {e}")
    
    save_data(data)
    logger.info("check_news ավարտվեց")

application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("add_source", add_source))
application.add_handler(CommandHandler("remove_source", remove_source))
application.add_handler(CommandHandler("add_hashtag", add_hashtag))
application.add_handler(CommandHandler("remove_hashtag", remove_hashtag))
application.add_handler(CommandHandler("start_monitor", start_monitor))
application.add_handler(CommandHandler("stop_monitor", stop_monitor))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    await application.start()
    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if domain:
        url = f"https://{domain}/{TOKEN}"
        try:
            await application.bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET)
            logger.info(f"Webhook set to {url}")
        except Exception as e:
            logger.error(f"Webhook set սխալ: {e}")
    yield
    await application.stop()
    await application.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post(f"/{TOKEN}")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            raise HTTPException(403, "Forbidden")
    try:
        update = Update.de_json(await request.json(), application.bot)
        if update:
            await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(500)
