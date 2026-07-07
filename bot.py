import os

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import ALLOWED_USERS
from db import db_init
from actions import COMMANDS
from handlers import handle, run_action

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
