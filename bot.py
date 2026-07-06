import asyncio
import os
import subprocess

from anthropic import AsyncAnthropic
from telegram import Update 
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ---  CONFIG FOR A API CLAUDE  ---
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

# ---  CONFIG FOR A API CLAUDE  ---

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
    return await  asyncio.to_thread(_df)


ACTIONS = {"disk_usage": disk_usage}

# ---  ACTIONS (WHITELIST)  ---

# --- CLAUDE TOOL-USE LOOP  ---

async def ask_claude(user_text: str) -> str:
    messages = [{"role": "user", "content": user_text}]

    resp = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
    )

    while resp.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": resp.content})
        result = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            action = ACTION.get(block.name)
            output = await action() if action else f"unknown action: {block.name}"
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                }

            )
        messages.append({"role": "user", "content": results})

        resp = await client.messages.create(
                model=MODEL,
                max_tokens=MAX+TOKENS,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
            )

    return "".join(b.text for b in resp.content if b.type == "text") or "(empty)"

# ---  CLAUDE TOOL-USE LOOP  ---
