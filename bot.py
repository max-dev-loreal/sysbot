import asyncio
import os
import subprocess

from anthropic import AsyncAnthropic
from telegram import Update 
from telegram.ext import Application, ContextTypes, MessageHandler, filters

#CONFIG FOR A API CLAUDE
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

SYSTEM = (
        "You are a monitoring assistant for a bare-metal Arch Linux Host, "
        "operated by its owner via telegram.\n\n"
        "You can act ONLY through the provided tools. You have no shell access "
        "and cannot run arbitary commands. If a request needs an action that no "
        "tool covers, say to plainly instead of pretending to do it.\n\n"
        "Current capability:\n"
        "- disk_usage: report filesystem usage (runs 'df -h'). Call it when the "
        "user asks about disk space, free space, or how full the filesystem are.\n\n"
        "When a tool returns output, summarize ot briefly and point out anything "
        "notable (e.g a filesystem above ~90% used). Do not invent numbers that "
        "are not in the tool output.\n\n"
        "Reply in Russian. Be concise and practical."
)

TOOLS = [
    {
        "name": "disk_usage",
        "description": "Check usage disk on a host ( runs 'df -h').",
        "input_schema": {"type": "object", "properties": {}},
    }
]

ALLOWED_USERS = {
    int(uid) for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",") if uid.strip()
}

client = AsyncAnthropic() 


