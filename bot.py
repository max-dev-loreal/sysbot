import asyncio
import html
import sqlite3
import time
import os
import subprocess
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ---  CONFIG  ---
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DB_PATH = "/home/max/sysbot/data/sysbot.db"

@dataclass
class Action:
    name: str
    description: str
    func: Callable[[], Awaitable[str]]
    tier: str = "safe"
    freshness: int = 60
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
MODEL = "gemini-2.5-flash-lite"
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

ALLOWED_USERS = {
    int(uid) for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",") if uid.strip()
}

client = AsyncOpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url=BASE_URL,
)

# ---  DB (history + freshness)  ---

def db_init() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                action_name TEXT    NOT NULL,
                output      TEXT    NOT NULL,
                ts          INTEGER NOT NULL
            )
            """
        )

def db_log(action_name: str, output: str) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO history (action_name, output, ts) VALUES (?, ?, ?)",
            (action_name, output, int(time.time())),
        )

def db_fresh(action_name: str, freshness: int) -> str | None:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT output, ts FROM history "
            "WHERE action_name = ? ORDER BY ts DESC LIMIT 1",
            (action_name,),
        ).fetchone()

    if row is None:
        return None
    output, ts = row
    if int(time.time()) - ts <= freshness:
        return output
    return None


async def call_action(name: str, use_cache: bool) -> tuple[str, bool]:
    entry = REGISTRY.get(name)
    if entry is None:
        return f"unknown action: {name}", False

    if use_cache:
        cached = db_fresh(name, entry.freshness)
        if cached is not None:
            return cached, True   

    output = await entry.func()
    db_log(name, output)
    return output, False

# ---  ACTIONS (WHITELIST)  ---

def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return f"error: {e}"
    return proc.stdout if proc.returncode == 0 else f"error: {proc.stderr.strip()}"


async def disk_usage() -> str:
    return await asyncio.to_thread(_run, ["df", "-h"])

async def memory() -> str:
    return await asyncio.to_thread(_run, ["free", "-h"])

async def uptime() -> str:
    return await asyncio.to_thread(_run, ["uptime"])

async def docker_ps() -> str:
    return await asyncio.to_thread(_run, ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}"])

async def top_procs() -> str:
    out = await asyncio.to_thread(_run, ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"])
    return "\n".join(out.splitlines()[:16])


REGISTRY: dict[str, Action] = {
    "disk_usage": Action(name="disk_usage", description="Filesystem usage ('df -h'). No parameters.", func=disk_usage),
    "memory": Action(name="memory", description="RAM and swap usage ('free -h'). No parameters.", func=memory),
    "uptime": Action(name="uptime", description="Uptime and load average. No parameters.", func=uptime),
    "docker_ps": Action(name="docker_ps", description="Running Docker containers. No parameters.", func=docker_ps),
    "top_procs": Action(name="top_procs", description="Top processes by CPU. No parameters.", func=top_procs),
}

COMMANDS = {
    "disk": "disk_usage",
    "mem": "memory",
    "uptime": "uptime",
    "docker": "docker_ps",
    "top": "top_procs",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": a.name,
            "description": a.description,
            "parameters": a.parameters,
        },
    }
    for a in REGISTRY.values()
]

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
            entry = REGISTRY.get(tc.function.name)
            output, _ = await call_action(tc.function.name, use_cache=True)
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

# ---  ENTRYPOINT  ---

def main() -> None:
    db_init()
    token = os.environ["TELEGRAM_TOKEN"]
    if not ALLOWED_USERS:
        raise SystemExit("ALLOWED_USER_IDS empty — refusing to start")

    app = Application.builder().token(token).build()
    for cmd in COMMANDS:
        app.add_handler(CommandHandler(cmd, run_action))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()


if __name__ == "__main__":
    main()
