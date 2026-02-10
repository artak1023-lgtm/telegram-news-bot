from rss import parse_feed
from storage import get_user, sent_cache

async def check_news(context):
    user_id = context.job.data
    user = get_user(user_id)

    if not user["active"]:
        return

    for name, url in user["sources"].items():
        items = parse_feed(url)

        for item in items:
            text = item["title"].lower()
            if not any(k in text for k in user["keywords"]):
                continue

            if item["id"] in sent_cache[user_id]:
                continue

            msg = (
                f"📰 <b>{name}</b>\n"
                f"{item['title']}\n\n"
                f"🇺🇸 {item['us_time']}\n"
                f"🇦🇲 {item['am_time']}\n\n"
                f"🔗 {item['link']}"
            )

            await context.bot.send_message(
                chat_id=user_id,
                text=msg,
                parse_mode="HTML",
                disable_web_page_preview=True
            )

            sent_cache[user_id].add(item["id"])
