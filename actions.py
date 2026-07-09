import asyncio
import subprocess
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from db import db_fresh, db_log


@dataclass
class Action:
    name: str
    description: str
    func: Callable[..., Awaitable[str]]
    tier: str = "safe"
    freshness: int = 60
    help: str = ""
    param: bool = False  # func takes one str argument (e.g. container name)
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


async def call_action(name: str, use_cache: bool, arg: str | None = None) -> tuple[str, bool]:
    entry = REGISTRY.get(name)
    if entry is None:
        return f"unknown action: {name}", False
    if use_cache and not entry.param:
        cached = db_fresh(name, entry.freshness)
        if cached is not None:
            return cached, True
    output = await entry.func(arg) if entry.param else await entry.func()
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
    return await asyncio.to_thread(_run, ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}"])

async def top_procs() -> str:
    out = await asyncio.to_thread(_run, ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"])
    return "\n".join(out.splitlines()[:16])

async def restart_nginx() -> str:
    out = await asyncio.to_thread(_run, ["systemctl", "restart", "nginx"])
    if out.startswith("error:"):
        return out
    return "✅ nginx перезапущен"


# ---  PARAMETRIZED ACTIONS (container name from user, validated by whitelist)  ---

ALLOWED_CONTAINERS = {"hello-web"}


async def docker_start(name: str) -> str:
    if name not in ALLOWED_CONTAINERS:
        return f"error: контейнер '{name}' не в белом списке"
    out = await asyncio.to_thread(_run, ["docker", "start", name])
    return out if out.startswith("error:") else f"✅ {name} запущен"

async def docker_stop(name: str) -> str:
    if name not in ALLOWED_CONTAINERS:
        return f"error: контейнер '{name}' не в белом списке"
    out = await asyncio.to_thread(_run, ["docker", "stop", name])
    return out if out.startswith("error:") else f"✅ {name} остановлен"

async def docker_restart(name: str) -> str:
    if name not in ALLOWED_CONTAINERS:
        return f"error: контейнер '{name}' не в белом списке"
    out = await asyncio.to_thread(_run, ["docker", "restart", name])
    return out if out.startswith("error:") else f"✅ {name} перезапущен"


async def containers() -> str:
    lines = []
    for name in sorted(ALLOWED_CONTAINERS):
        out = await asyncio.to_thread(
            _run, ["docker", "inspect", "-f", "{{.State.Status}}", name]
        )
        status = out.strip()
        if status.startswith("error:") or not status:
            mark = "⚪ нет контейнера"
        elif status == "running":
            mark = "🟢 running"
        else:
            mark = f"🔴 {status}"
        lines.append(f"{name} — {mark}")
    return "\n".join(lines) if lines else "белый список пуст"


REGISTRY: dict[str, Action] = {
    "disk_usage": Action(name="disk_usage", description="Filesystem usage ('df -h'). No parameters.", func=disk_usage, help="использование диска"),
    "memory": Action(name="memory", description="RAM and swap usage ('free -h'). No parameters.", func=memory, help="память и swap"),
    "uptime": Action(name="uptime", description="Uptime and load average. No parameters.", func=uptime, help="аптайм и нагрузка"),
    "docker_ps": Action(name="docker_ps", description="Running Docker containers. No parameters.", func=docker_ps, help="запущенные контейнеры"),
    "containers": Action(name="containers", description="Whitelisted containers and their status. No parameters.", func=containers, help="доступные контейнеры и статус"),
    "top_procs": Action(name="top_procs", description="Top processes by CPU. No parameters.", func=top_procs, help="топ процессов по CPU"),
    "restart_nginx": Action(name="restart_nginx", description="Restart the nginx service.", func=restart_nginx, tier="dangerous", help="перезапустить nginx"),
    "docker_start": Action(name="docker_start", description="Start a whitelisted Docker container.", func=docker_start, tier="dangerous", param=True, help="запустить контейнер"),
    "docker_stop": Action(name="docker_stop", description="Stop a whitelisted Docker container.", func=docker_stop, tier="dangerous", param=True, help="остановить контейнер"),
    "docker_restart": Action(name="docker_restart", description="Restart a whitelisted Docker container.", func=docker_restart, tier="dangerous", param=True, help="перезапустить контейнер"),
}

COMMANDS = {
    "disk": "disk_usage",
    "mem": "memory",
    "uptime": "uptime",
    "docker": "docker_ps",
    "containers": "containers",
    "top": "top_procs",
    "restart_nginx": "restart_nginx",
    "docker_start": "docker_start",
    "docker_stop": "docker_stop",
    "docker_restart": "docker_restart",
}

# Param actions are excluded: the LLM path calls func() with no argument, and
# these ops require a validated container name — they go through /commands only.
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
    if not a.param
]
