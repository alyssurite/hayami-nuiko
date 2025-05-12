"""Main module"""

import asyncio
import sys

# start bot
from yaminui.app.main import start_app

# settings
from yaminui.extra.loggers import root_log

if __name__ == "__main__":
    # start bot
    root_log.info("Starting the bot...")
    sys.exit(asyncio.run(start_app()))
