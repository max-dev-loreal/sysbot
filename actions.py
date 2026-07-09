import asyncio
import subprocess
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from db import db_fresh, db_log


@dataclass
class Action:
    name: str
    description: str
    func: Callable[[], Awaitable[str]]
    tier: str = "safe"
    freshness: int = 60
    help: str = ""
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


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
    "disk_usage": Action(name="disk_usage", description="Filesystem usage ('df -h'). No parameters.", func=disk_usage, help="использование диска"),
    "memory": Action(name="memory", description="RAM and swap usage ('free -h'). No parameters.", func=memory, help="память и swap"),
    "uptime": Action(name="uptime", description="Uptime and load average. No parameters.", func=uptime, help="аптайм и нагрузка"),
    "docker_ps": Action(name="docker_ps", description="Running Docker containers. No parameters.", func=docker_ps, help="запущенные контейнеры"),
    "top_procs": Action(name="top_procs", description="Top processes by CPU. No parameters.", func=top_procs, help="топ процессов по CPU"),
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
