import os

from openai import AsyncOpenAI

# ---  CONFIG  ---
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DB_PATH = "/home/max/sysbot/data/sysbot.db"

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
