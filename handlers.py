import html

from telegram import Update
from telegram.ext import ContextTypes

from config import ALLOWED_USERS
from actions import COMMANDS, REGISTRY, call_action
from llm import ask_llm

# ---  TELEGRAM  ---
def _allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ALLOWED_USERS


async def run_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Access denied")
        return

    name = update.message.text.lstrip("/").split("@")[0].split()[0]
    action_name = COMMANDS.get(name)
    entry = REGISTRY.get(action_name) if action_name else None
    if entry is None:
        await update.message.reply_text(f"❓ Unknown command: /{name}")
        return

    try:
        output, _ = await call_action(action_name, use_cache=False)
    except Exception as e:
        output = f"⚠️ Error: {e}"
    await update.message.reply_text(
        f"<pre>{html.escape(output)}</pre>",
        parse_mode="HTML",
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ Access denied")
        return

    try:
        answer = await ask_llm(update.message.text or "")
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            answer = "⏳ Лимит запросов исчерпан, подожди минуту."
        else:
            answer = f"⚠️ Error: {e}"
    await update.message.reply_text(answer)
