"""Bot module"""

import os
import re

from dataclasses import dataclass
from functools import partial

# pyrogram client
from pyrogram import Client

# telegram core bot api extension
from telegram.ext import Application

# escaping special markdown characters
from telegram.helpers import escape_markdown

# uploading media
from ..extra.upload import upload_log

# escaping markdown v2
esc = partial(escape_markdown, version=2)

# read & write timeouts for bot
READ_TIMEOUT, WRITE_TIMEOUT = 5, 5

# read & write media timeouts for bot
READ_MEDIA_TIMEOUT, WRITE_MEDIA_TIMEOUT = 25, 50

# limited queue size
QUEUE_SIZE = 3

# delay in seconds for collecting all media group messages
DELAY_START = 0.1

# job sleep length for adding media group messages
JOB_SLEEP = 0.05

# allowed misfire time for a job
MISFIRE_GRACE_TIME = 30

pyro_app = Client(
    "yaminuibot",
    api_id=os.environ["API_ID"],
    api_hash=os.environ["API_HASH"],
    bot_token=os.environ["TOKEN"],
)


async def on_bot_init(_: Application) -> None:
    await pyro_app.start()


async def on_bot_stop(_: Application) -> None:
    await pyro_app.log_out()
    await upload_log()


async def unescape_html(text: str) -> str:
    """Unescape html escapes (mainly for markdown)

    Args:
        text (str): text with html escapes

    Returns:
        str: text wuthout escapes
    """
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


# user data dictionary
@dataclass
class UserData:
    forward: bool  # forward mode
    reply: bool  # reply mode
    media: bool  # media style (legacy)
    pixiv: int  # pixiv style
    twitter: int  # twitter style
    info: dict  # artwork info (if any)
    chan: int = 0  # channel id


# telegram bot modes
class BotMode:
    modes = (
        POLLING,
        WEBHOOK,
    ) = range(2)


# telegram bot states
class BotState:
    states = (CHANNEL,) = map(chr, range(1))

    @classmethod
    def validate(cls, value: chr):
        return value in cls.states


class PostingResult:
    states = (
        STATE_POSTED,
        STATE_CONTINUE,
        STATE_REPOSTED,
        STATE_NOT_POSTABLE,
        STATE_SELFREPOST,
        STATE_ERROR,
    ) = range(6)

    @classmethod
    def validate(cls, value: int):
        return value in cls.states


# twitter link id
tw_regex = r"(?:.*\/(?P<id>.+)(?:\.|\?f))"

# pixiv regex
pixiv_number = re.compile(r"((?P<n1>\d+)(?:-(?P<n2>\d+))?)")

# telegram internal post link
tg_post_link = "t.me/c/{cid}/{post_id}"

# callback query result for duplicate
duplicate_result = [
    "`\\[` *POST HAS BEEN POSTED\\.* `\\]`",
    "`\\[` *PLEASE, SPECIFY DATA\\.* `\\]`",
    "`\\[` *POST HAS BEEN REPOSTED\\.* `\\]`",
    "`\\[` *POST COULDN'T BE REPOSTED\\.* `\\]`",
    "`\\[` *POST COULDN'T BE SELF\\-REPOSTED\\.* `\\]`",
    "`\\[` *????????????????????\\.* `\\]`",
]

# callback query result for delete
delete_result = [
    "`\\[` *POST HAS BEEN DELETED\\.* `\\]`",
    "`\\[` *POST CAN'T BE FOUND\\.* `\\]`",
    "`\\[` *POST CAN'T BE DELETED\\.* `\\]`",
    "`\\[` *YOU CAN'T DELETE THIS POST\\.* `\\]`",
    "`\\[` *ACTION HAS BEEN CANCELLED\\.* `\\]`",
    "`\\[` *????????????????????\\.* `\\]`",
]
