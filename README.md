# sysbot

A Telegram bot that lets me monitor and control my bare-metal Arch Linux box from my phone — using an LLM to turn plain language into safe, whitelisted actions. No free-form shell, ever.

Ask it *"how much disk do I have?"* and it runs `df -h`, reads the output, and answers in plain language. Type `/restart_nginx` and it asks for confirmation before touching anything. That's the whole idea: a small, opinionated, **production-shaped** toy I built to actually learn systemd, Linux internals, and the security patterns that separate "a script that works" from "a service you'd trust on a real machine."

It is deliberately small. Most of the interesting work is in what it *refuses* to do.

---

## Why I built it

I'd been digging into systemd and Linux administration and wanted a project that would force me to touch the real thing — unit hardening, signals, `/proc`, privilege boundaries — instead of reading about them. A chat bot that runs system commands turned out to be a perfect excuse: every feature drags in a real security question you can't hand-wave.

The rule I set on day one and never broke: **the bot can only do things I explicitly allowed, and it can never be talked into doing anything else.** Everything below is downstream of that one rule.

---

## What it does

**Monitoring (read-only, no confirmation):**
- `/disk` — filesystem usage
- `/mem` — RAM and swap
- `/uptime` — uptime and load
- `/top` — top processes by CPU
- `/docker` — all containers (running and stopped)
- `/containers` — containers the bot is allowed to manage, with status

**Control (requires confirmation):**
- `/restart_nginx` — restart nginx
- `/docker_start|stop|restart <name>` — manage whitelisted containers
- `/kill <pid>` — terminate a process (graceful: SIGTERM, then SIGKILL)

**Two ways to talk to it:**
- **Plain language** → the LLM (Gemini via an OpenAI-compatible endpoint) reads intent and calls the right read-only tool.
- **Slash commands** → run the action directly, bypassing the LLM entirely. Faster, free, and they still work when the LLM is rate-limited or down.

---

## Architecture, and the decisions behind it

The interesting part isn't the feature list — it's the choices. A few I'm glad I made:

### It runs as a systemd service on the host, not in Docker

My first instinct was "containerize it." Then I realized: a program whose *job* is to read the host sees nothing useful from inside a container — `df` reports the container's overlay filesystem, not my disks. The usual fix is to hand the container `privileged` + `pid: host` + `nsenter` to break back out into the host's namespaces.

That's building a wall and then knocking holes in it — and the holes are exactly the biggest risk in the whole project (a privileged container running `nsenter -t 1` is basically root-over-Telegram). So I dropped Docker for the bot. A plain systemd service sees the host natively, with **zero** namespace escapes, and lets me lock it down with hardening directives instead.

### Defense lives in the code, not in the model's good behavior

The LLM is not trusted. It can be wrong, and it can be manipulated (prompt injection). So the model never touches anything dangerous:

- Every action is a **whitelisted** function with a fixed `argv` list — `["df", "-h"]`, never a shell string. There is no code path that runs arbitrary commands.
- Control actions (`/kill`, docker, nginx) are **command-only** — the LLM literally cannot invoke them; they're filtered out of the tool list it sees.
- Validation lives **inside the action**, not in the handler. The handler is one door; the scheduler, the LLM, a future agent are others. Put the check at the *value*, not at the *door*, and no path can skip it.

### `NoNewPrivileges=true` vs. sudo → polkit

The bot needs to restart nginx, which needs root. But my hardened unit has `NoNewPrivileges=true`, which by design makes `sudo` (and any setuid privilege escalation) impossible. Two bad options: rip out the hardening, or hack around it.

The clean answer was **polkit**. `systemctl restart nginx` over D-Bus doesn't escalate the bot's privileges — it asks the (already-root) system manager to do the work, and a polkit rule authorizes *only* `nginx.service` for *only* my user. `NoNewPrivileges` stays on. The hardening is intact and the bot can do exactly one privileged thing and nothing else.

### Confirmation you can't fat-finger

Dangerous actions send inline `✅ / ❌` buttons, but the mechanics matter:
- the confirmation token is **single-use** (consumed on tap — a second tap says "expired"),
- it has a **60-second TTL** (an old button scrolled up in history is dead),
- it's **bound to the requesting user**,
- the target argument lives **server-side**, never in the button's callback data (so a tampered callback can't swap which container gets touched).

### Killing processes like an adult

`/kill` doesn't `kill -9`. It sends **SIGTERM**, waits, and only then **SIGKILL**s if the process is still alive — the same graceful shutdown systemd itself does, so processes get a chance to clean up. It refuses any PID below 100 (you are not killing init through a chat message), checks existence with `os.kill(pid, 0)` (signal 0 sends nothing, just probes), and can only touch processes my own user owns — an OS boundary I chose not to widen.

---

## The build, level by level

I built this in strict levels to avoid scope creep — each one self-contained, nothing reaching ahead:

- **Level 0** — bare bot: one action, prove the whole chain works (systemd → Telegram → LLM → tool call → answer).
- **Level 1** — a real action set behind a single **registry** (the LLM's tool list is generated from it — add an action in one place, not two), plus slash-command fallback that skips the LLM.
- **Level 2** — **SQLite** history + a freshness cache: ask the same thing twice within a threshold and it serves the cached result instead of re-running the command. Different actions get different freshness windows.
- **Level 3** — the **dangerous tier**: safe/dangerous/destructive split, confirmation flow, polkit, whitelisted docker control, and process killing. Built in sub-steps (3a confirm mechanics, 3b docker, 3c kill) so the risky machinery was debugged on the safest action first.

Somewhere in the middle I split the growing single file into six flat modules (`config`, `db`, `actions`, `llm`, `handlers`, `bot`) with strictly one-directional imports — refactored while the code was in a known-good state, which is the only sane time to do it.

---

## Things I deliberately did *not* build

This section exists on purpose. Cutting features is a decision too:

- **File editing over Telegram** — I have SSH. Building a "write any file" feature would quietly turn a monitoring bot into arbitrary code execution on my server (write to `authorized_keys`, `.bashrc`, a systemd unit... game over). The whole point was *no* free-form access. SSH already solves this, safely.
- **`docker rm` from my phone** — deleting a container is a calm, deliberate thing you do at a keyboard, not a panic-from-the-couch action. Adding a "type the name to confirm" flow for it would've been effort spent on a problem I don't have.
- **An auto-fixing agent** — the original grand plan had a "fixer" that would repair problems on its own. I cut it down to an *investigator* that would only diagnose and report, leaving the human in the loop. An LLM autonomously running destructive commands on my prod is exactly the thing I don't want, no matter how clever the plan it writes.

None of these are "I couldn't." They're "I shouldn't, for this."

---

## Where it stops

The original roadmap went further — a scheduler, a background watcher that alerts on its own, an investigator agent over Redis pub/sub. I mapped all of it out, then stopped at Level 3, because for what this actually is — a personal box I check on from my phone — the monitoring-and-control set is complete. The later levels solve problems a single-user home toy doesn't have.

---

## Stack

- **Python** — `python-telegram-bot` (async), `openai` SDK pointed at Gemini's OpenAI-compatible endpoint
- **systemd** — hardened unit (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths` scoped to the DB dir, and friends)
- **polkit** — scoped privilege for the one thing that needs root
- **SQLite** — history + freshness cache
- **Arch Linux** — rolling release, so I'm testing against current systemd/Docker/kernel rather than something two years stale

## Notes

Secrets (`.env`) and runtime data (`data/`) are gitignored. Access is restricted to a single Telegram user ID; the service refuses to start with an empty allowlist. The bot only works while the host is up — which is fine, since a monitor for a powered-off machine wouldn't have much to say.
