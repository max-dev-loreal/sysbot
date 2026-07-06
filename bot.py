import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ---  CONFIG  ---
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

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
            output = await entry.func() if entry else f"unknown action: {tc.function.name}"
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
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            answer = "⏳ Лимит запросов исчерпан, подожди минуту."
        else:
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
