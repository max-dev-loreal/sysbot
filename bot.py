import os

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config import ALLOWED_USERS
from db import db_init
from actions import COMMANDS
from handlers import handle, help_cmd, on_confirm, run_action


# ---  ENTRYPOINT  ---

def main() -> None:
    db_init()
    token = os.environ["TELEGRAM_TOKEN"]
    if not ALLOWED_USERS:
        raise SystemExit("ALLOWED_USER_IDS empty — refusing to start")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("help", help_cmd))
    for cmd in COMMANDS:
        app.add_handler(CommandHandler(cmd, run_action))
    app.add_handler(CallbackQueryHandler(on_confirm))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()


if __name__ == "__main__":
    main()
