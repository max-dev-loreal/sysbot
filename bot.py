import asyncio
import os
import subprocess

from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ---  CONFIG  ---
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-2.5-flash"
MAX_TOKENS = 1024

SYSTEM = (
    "You are a monitoring assistant for a bare-metal Arch Linux host, "
    "operated by its owner via Telegram.\n\n"
    "You can act ONLY through the provided tools. You have no shell access "
    "and cannot run arbitrary commands. If a request needs an action that no "
    "tool covers, say so plainly instead of pretending to do it.\n\n"
    "Current capability:\n"
    "- disk_usage: report filesystem usage (runs 'df -h'). Call it when the "
    "user asks about disk space, free space, or how full the filesystems are.\n\n"
    "When a tool returns output, summarize it briefly and point out anything "
    "notable (e.g. a filesystem above ~90% used). Do not invent numbers that "
    "are not in the tool output.\n\n"
    "Reply in Russian. Be concise and practical."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "disk_usage",
            "description": "Report filesystem usage (runs 'df -h'). No parameters.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]

ALLOWED_USERS = {
    int(uid) for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",") if uid.strip()
}

client = AsyncOpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url=BASE_URL,
)

# ---  ACTIONS (WHITELIST)  ---

def _df() -> str:
    try:
        proc = subprocess.run(
            ["df", "-h"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return f"error: {e}"
    return proc.stdout if proc.returncode == 0 else f"error: {proc.stderr.strip()}"


async def disk_usage() -> str:
    return await asyncio.to_thread(_df)


ACTIONS = {"disk_usage": disk_usage}

# ---  LLM TOOL-USE LOOP  ---

async def ask_llm(user_text: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_text},
    ]

    resp = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        max_tokens=MAX_TOKENS,
    )
    msg = resp.choices[0].message

    while msg.tool_calls:
        messages.append(msg)
        for tc in msg.tool_calls:
            action = ACTIONS.get(tc.function.name)
            output = await action() if action else f"unknown action: {tc.function.name}"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                }
            )

        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            max_tokens=MAX_TOKENS,
        )
        msg = resp.choices[0].message

    return msg.content or "(empty)"

# ---  TELEGRAM  ---

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ Access denied")
        return

    try:
        answer = await ask_llm(update.message.text or "")
    except Exception as e:
        answer = f"⚠️ Error: {e}"
    await update.message.reply_text(answer)

# ---  ENTRYPOINT  ---

def main() -> None:
    token = os.environ["TELEGRAM_TOKEN"]
    if not ALLOWED_USERS:
        raise SystemExit("ALLOWED_USER_IDS empty — refusing to start")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()


if __name__ == "__main__":
    main()
