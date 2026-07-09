import html
import secrets
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ALLOWED_USERS
from actions import COMMANDS, REGISTRY, call_action
from llm import ask_llm


# ---  TELEGRAM  ---

def _allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ALLOWED_USERS


def _proc_name(pid_str: str) -> str:
    try:
        with open(f"/proc/{int(pid_str)}/comm") as f:
            return f.read().strip()
    except Exception:
        return "?"


TIER_LABELS = {
    "safe": "📊 Мониторинг",
    "dangerous": "⚠️ Управление",
    "destructive": "🔥 Опасные",
}

# token → (action_name, arg, user_id, created_at)   arg is None for no-arg actions
PENDING: dict[str, tuple[str, str | None, int, float]] = {}
CONFIRM_TTL = 60


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Access denied")
        return

    groups: dict[str, list[str]] = {"safe": [], "dangerous": [], "destructive": []}
    for cmd, action_name in COMMANDS.items():
        entry = REGISTRY.get(action_name)
        if entry is None:
            continue
        groups[entry.tier].append(f"/{cmd} — {entry.help}")

    lines = ["<b>Команды sysbot:</b>"]
    for tier in ("safe", "dangerous", "destructive"):
        if groups[tier]:
            lines.append(f"\n<b>{TIER_LABELS[tier]}</b>")
            lines.extend(groups[tier])
    lines.append("\n/help — этот список")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def run_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Access denied")
        return
    parts = update.message.text.lstrip("/").split()
    name = parts[0].split("@")[0]
    action_name = COMMANDS.get(name)
    entry = REGISTRY.get(action_name) if action_name else None
    if entry is None:
        await update.message.reply_text(f"❓ Unknown command: /{name}")
        return

    arg = None
    if entry.param:
        if len(parts) < 2:
            if action_name == "kill_proc":
                hint = "⚠️ Укажи PID, напр. /kill 12345"
            else:
                hint = "⚠️ Укажи имя контейнера, напр. /{cmd} hello-web".format(cmd=name)
            await update.message.reply_text(hint)
            return
        arg = parts[1]

    if entry.tier != "safe":
        token = secrets.token_hex(8)
        PENDING[token] = (action_name, arg, update.effective_user.id, time.time())
        if action_name == "kill_proc":
            text = f"⚠️ Убить процесс {arg} ({_proc_name(arg)})?"
        else:
            label = entry.help or action_name
            if arg:
                label = f"{label}: {arg}"
            text = f"⚠️ Подтверди действие: {label}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok:{token}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"no:{token}"),
        ]])
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
        )
        return

    try:
        output, _ = await call_action(action_name, use_cache=False, arg=arg)
    except Exception as e:
        output = f"⚠️ Error: {e}"
    await update.message.reply_text(
        f"<pre>{html.escape(output)}</pre>",
        parse_mode="HTML",
    )


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    decision, _, token = query.data.partition(":")
    pending = PENDING.pop(token, None)

    if pending is None:
        await query.edit_message_text("⏳ Запрос устарел")
        return
    action_name, arg, user_id, created = pending
    if query.from_user.id != user_id:
        await query.edit_message_text("⛔ Не твой запрос")
        return
    if time.time() - created > CONFIRM_TTL:
        await query.edit_message_text("⏳ Запрос устарел")
        return
    if decision == "no":
        await query.edit_message_text("❌ Отменено")
        return

    try:
        output, _ = await call_action(action_name, use_cache=False, arg=arg)
    except Exception as e:
        output = f"⚠️ Error: {e}"
    await query.edit_message_text(
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
