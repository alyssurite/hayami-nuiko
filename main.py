"""Main module"""
import sys

# start bot
from yaminui.app import start_bot

# settings
from yaminui.extra.loggers import root_log

if __name__ == "__main__":
    # start bot
    root_log.info("Starting the bot...")
    sys.exit(start_bot())
