import os
import json
import logging
from datetime import datetime
import pytz
import feedparser
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')  # @channel կամ -100xxxxxxxxxx
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'my-secret-token')  # optional, բայց խորհուրդ է տրվում

app = FastAPI()
application = Application.builder().token(TOKEN).build()

# Քո data management ֆունկցիաները (load_data, save_data) մնում են նույնը
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

# Հրամանները (start, add_source և այլն) մնում են նույնը, միայն async
# ... (պատճենիր start, add_source, remove_source, add_hashtag, remove_hashtag, start_monitor, stop_monitor, check_news ֆունկցիաները այստեղ)

# Webhook endpoint
@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        auth = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if auth != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500)

# Startup-ում set webhook + job queue
@app.on_event("startup")
async def startup():
    data = load_data()
    await application.initialize()
    await application.start()

    # Set webhook
    webhook_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/{TOKEN}"
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
        allowed_updates=Update.ALL_TYPES
    )
    logger.info(f"Webhook set to {webhook_url}")

    # Եթե monitoring միացված էր — վերականգնել job-ը
    if data['monitoring']:
        application.job_queue.run_repeating(check_news, interval=60, first=10)

@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
