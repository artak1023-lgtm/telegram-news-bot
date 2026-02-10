from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from storage import get_user
from config import DEFAULT_SOURCES, DEFAULT_KEYWORDS

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📰 Աղբյուրներ", callback_data="sources")],
        [InlineKeyboardButton("🔑 Բանալի բառեր", callback_data="keywords")],
        [InlineKeyboardButton("⚙️ Միացնել / Անջատել", callback_data="toggle")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    user["sources"] = DEFAULT_SOURCES.copy()
    user["keywords"] = DEFAULT_KEYWORDS.copy()

    await update.message.reply_text(
        "🤖 <b>Նորությունների բոտ</b>\n"
        "Ավտոմատ թարմացում՝ ամեն 1 րոպե",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = get_user(q.from_user.id)

    if q.data == "sources":
        text = "\n".join(user["sources"].keys()) or "Դատարկ է"
        await q.edit_message_text(
            f"📰 <b>Աղբյուրներ</b>\n{text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Հետ", callback_data="back")]]),
            parse_mode="HTML"
        )

    elif q.data == "keywords":
        text = ", ".join(user["keywords"]) or "Դատարկ է"
        await q.edit_message_text(
            f"🔑 <b>Բանալի բառեր</b>\n{text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Հետ", callback_data="back")]]),
            parse_mode="HTML"
        )

    elif q.data == "toggle":
        user["active"] = not user["active"]
        state = "🟢 Միացված" if user["active"] else "🔴 Անջատված"
        await q.edit_message_text(
            f"⚙️ Կարգավիճակ՝ {state}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Հետ", callback_data="back")]])
        )

    elif q.data == "back":
        await q.edit_message_text(
            "Գլխավոր մենյու",
            reply_markup=main_keyboard()
        )
