import os
import json
import logging
from datetime import datetime
import pytz
import feedparser
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')  # Ավելացրու Railway variables-ում
DATA_FILE = 'data.json'

# Բեռնել data
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'sources': [], 'hashtags': [], 'monitoring': False, 'last_seen': {}, 'user_id': None}

# Պահպանել data
def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    data['user_id'] = update.message.from_user.id
    save_data(data)
    await update.message.reply_text('Բոտը սկսված է! Օգտագործիր /add_source <url>, /add_hashtag <tag>, /start_monitor, և այլն:')

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
                continue  # Already seen
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

def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_source", add_source))
    app.add_handler(CommandHandler("remove_source", remove_source))
    app.add_handler(CommandHandler("add_hashtag", add_hashtag))
    app.add_handler(CommandHandler("remove_hashtag", remove_hashtag))
    app.add_handler(CommandHandler("start_monitor", start_monitor))
    app.add_handler(CommandHandler("stop_monitor", stop_monitor))

    # Webhook setup
    webhook_url = os.getenv('WEBHOOK_URL')
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=TOKEN,
        webhook_url=webhook_url + TOKEN
    )

if __name__ == "__main__":
    main()
