import os
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler
)
from bot import start, buttons
from jobs import check_news
from config import CHECK_INTERVAL

TOKEN = os.getenv("BOT_TOKEN")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))

    app.job_queue.run_repeating(
        check_news,
        interval=CHECK_INTERVAL,
        first=10,
        data=None
    )

    PORT = int(os.getenv("PORT", 8080))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
