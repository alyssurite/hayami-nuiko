"""Senders module"""
import logging

from copy import deepcopy
from html import escape as escape_html
from typing import Callable, Optional

# telegram core bot api
from telegram import (
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    Update,
)

# telegram constants
from telegram.constants import ParseMode as PM

# telegram errors
from telegram.error import RetryAfter, TimedOut

# hardcore retrying
from tenacity import AsyncRetrying, RetryCallState, before_sleep_log, stop_after_attempt

# pixiv & twitter styles, link types
from ..api import LinkType, PixivStyle, TwitterStyle

# link namedtuple
from ..api.namedtuples import Link

# get bot
from ..bot import ptb_app

# bot utils
from ..bot.utils import get_post_link

# database getters
from ..db.getters import get_other_links

# downloading media
from ..extra.download import download_media

# escape markdown, constants
from . import READ_MEDIA_TIMEOUT, WRITE_MEDIA_TIMEOUT, esc

# get logger
log = logging.getLogger(__name__)

# constants
MAX_TIMEOUT, MAX_TRIES = 15, 5


def wait_fixed_time(retry_state: RetryCallState) -> int:
    """Waits fixed time before next retry depending on exception

    Args:
        retry_state (RetryCallState): retry state

    Returns:
        int: time to wait
    """
    ex = retry_state.outcome.exception()
    if isinstance(ex, RetryAfter):
        return ex.retry_after + 1
    if isinstance(ex, TimedOut):
        return MAX_TIMEOUT
    return 5 * MAX_TIMEOUT


def retry_sending(func: Callable[..., Message]) -> Callable[..., Message]:
    """Decorator that retries telegram send function

    Args:
        func (Callable): telegram send function

    Returns:
        Callable: decorator
    """
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(MAX_TRIES),
        wait=wait_fixed_time,
        before_sleep=before_sleep_log(log, log_level=logging.WARNING),
    ).wraps(func)


@retry_sending
async def forward(update: Update, channel: int) -> Message:
    """Forward message to channel

    Args:
        update (Update): current update
        channel (int): a channel to forward to

    Returns:
        Message: Telegram Message
    """
    return await update.effective_message.forward(channel)


@retry_sending
async def send_reply(update: Update, text: str, **kwargs) -> Message:
    """Reply to current message

    Args:
        update (Update): current update
        text (str): text to send in markdown v2

    Returns:
        Message: Telegram Message
    """
    return await update.effective_message.reply_markdown_v2(text, **kwargs)


@retry_sending
async def send_error(update: Update, text: str, quote=True, **kwargs) -> Message:
    """Reply to current message with error

    Args:
        update (Update): current update
        text (str): text to send in markdown v2
        quote (bool): if message with error should be quoted. Defaults to True.

    Returns:
        Message: Telegram Message
    """
    return await send_reply(update, "\\[`ERROR`\\] " + text, quote=True, **kwargs)


@retry_sending
async def send_warn(update: Update, link: Link, **kwargs) -> Message:
    """Reply to current message with warning

    Args:
        update (Update): current update
        link (Link): link to the artwork

    Returns:
        Message: Telegram Message
    """
    posted = await get_other_links(link.id, link.type)
    text = ", and ".join([f"[here]({esc(post)})" for post in posted])
    url = f"{link.link}{'+' + link.illust if link.illust else ''}"
    return await send_reply(
        update,
        text=f"This [artwork]({esc(url)}) was already posted\\: {text}\\.\n\n"
        "`\\[` ⚠️ *POST IT ANYWAY\\?* ⚠️ `\\]`",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(text="♻️ Repost! ♻️", callback_data="repost")],
                [InlineKeyboardButton(text="🚩 Post!  🚩", callback_data="post")],
            ]
        ),
        quote=True,
        **kwargs,
    )


@retry_sending
async def send_api_warn(chat: Chat, link: Link, **kwargs) -> Message:
    """Send message with warning to the chat

    Args:
        chat (Chat): current chat
        link (Link): link to the artwork

    Returns:
        Message: Telegram Message
    """
    posted = await get_other_links(link.id, link.type)
    text = ", and ".join([f"[here]({esc(post)})" for post in posted])
    url = f"{link.link}{'+' + link.illust if link.illust else ''}"
    return await chat.send_message(
        text=f"This [artwork]({esc(url)}) was already posted\\: {text}\\.\n\n"
        "`\\[` ⚠️ *POST IT ANYWAY\\?* ⚠️ `\\]`",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(text="♻️ Repost! ♻️", callback_data="repost")],
                [InlineKeyboardButton(text="🚩 Post!  🚩", callback_data="post")],
            ]
        ),
        parse_mode=PM.MARKDOWN_V2,
        **kwargs,
    )


@retry_sending
async def send_reply_post(
    update: Update,
    text: str,
    channel_id: int,
    post_id: int,
    link: str,
) -> Message:
    """Reply to current message with link to posted content

    Args:
        update (Update): current update
        text (str): description of action
        channel_id (int): channel id
        post_id (int): channel post id
        link (str): content original link

    Returns:
        Message: Telegram Message
    """
    link, post = esc(link), esc(get_post_link(channel_id, post_id))
    return await send_reply(
        update,
        f"*[Artwork]({link})* was *[{text}]({post})*\\!",
    )


@retry_sending
async def send_api_reply_post(
    chat: Chat,
    text: str,
    channel_id: int,
    post_id: int,
    link: str,
) -> Message:
    """Reply to current message with link to posted content

    Args:
        update (Update): current update
        text (str): description of action
        channel_id (int): channel id
        post_id (int): channel post id
        link (str): content original link

    Returns:
        Message: Telegram Message
    """
    link, post = esc(link), esc(get_post_link(channel_id, post_id))
    return await chat.send_message(
        text=f"*[Artwork]({link})* was *[{text}]({post})*\\!",
        parse_mode=PM.MARKDOWN_V2,
    )


@retry_sending
async def send_post(
    info: dict = None,
    text: str = None,
    parse_mode: str = None,
    **kwargs,
) -> Optional[Message]:
    """Send post to channel

    Args:
        info (dict): art media dictionary
        text (str): text to send

    Returns:
        Optional[Message]: Telegram Message
    """
    if info:
        text = esc(info["link"])
    if text:
        return await ptb_app.send_message(
            text=text,
            parse_mode=parse_mode,
            **kwargs,
        )
    log.error("Send Post: No text or info supplied.")


async def escape_all(post: dict[str], kind: str):
    if kind == "html":
        for key, item in post.items():
            if key != "desc":
                post[key] = escape_html(item)
            else:
                post[key] = item.replace("<br />", "\n")
    else:
        for key, item in post.items():
            post[key] = esc(item)


@retry_sending
async def send_media(
    info: dict,
    *,
    order: list[int] = None,
    style: int = None,
    **kwargs,
) -> Optional[Message]:
    """Sends media as media group

    Args:
        info (dict): art media dictionary
        order (list[int], optional): which artworks to upload. Defaults to None.
        style (int, optional): pixiv style. Defaults to None.

    Returns:
        Optional[Message]: Telegram Message
    """
    if not info:
        log.error("Send Media: No info supplied.")
        return
    log.debug("Info: %r.", info)
    post = {
        "user": info["user"],
        "username": info["username"],
        "link": info["link"],
        "title": info["title"],
        "desc": info["desc"],
    }
    match info["type"]:
        case LinkType.PIXIV:
            parse_mode = PM.HTML
            await escape_all(post, "html")
            caption = PixivStyle.get_format(style, **post)
            if style in (PixivStyle.INFO_EMBED_LINK, PixivStyle.INFO_LINK):
                return await send_post(
                    text=caption,
                    parse_mode=parse_mode,
                    **kwargs,
                )
        case LinkType.TWITTER:
            parse_mode = PM.MARKDOWN_V2
            await escape_all(post, "mdv2")
            caption = TwitterStyle.get_format(style, **post)
            if style == TwitterStyle.LINK:
                return await send_post(
                    text=caption,
                    parse_mode=parse_mode,
                    **kwargs,
                )
    idx, media = -1, []
    async for filename, file in download_media(info, full=False, order=order):
        idx += 1
        if (
            info["type"] == LinkType.PIXIV
            and info["media"] in ("illust", "manga")
            or info["type"] == LinkType.TWITTER
            and info["media"][idx] == "photo"
        ):
            media.append(
                InputMediaPhoto(
                    media=file,
                    filename=filename,
                    caption=caption if not idx else None,
                    parse_mode=parse_mode if not idx else None,
                )
            )
        else:
            media.append(
                InputMediaVideo(
                    media=file,
                    filename=filename,
                    caption=caption if not idx else None,
                    parse_mode=parse_mode if not idx else None,
                )
            )
    # answer to pixiv artwork
    if "reply_to_message_id" in kwargs and "message_id" in info:
        kwargs["reply_to_message_id"] = info["message_id"]
    return await ptb_app.send_media_group(
        media=media,
        read_timeout=READ_MEDIA_TIMEOUT,
        write_timeout=WRITE_MEDIA_TIMEOUT,
        **kwargs,
    )


@retry_sending
async def send_media_doc(
    info: dict,
    *,
    media_filter: list[str] = None,
    channel_mode: bool = False,
    order: list[int] = None,
    **kwargs,
) -> Optional[Message]:
    """Send media as documents

    Args:
        info (dict): art media dictionary
        media_filter (list[str], optional): types to send. Defaults to None.
        channel_mode (bool, optional): don't send document, send media.
        Defaults to False.
        order (list[int], optional): which artworks to upload. Defaults to None.

    Returns:
        Optional[Message]: Telegram Message
    """
    if not info:
        log.error("Send Media Doc: No info supplied.")
        return
    log.debug("Info: %r.", info)
    filtered_info = deepcopy(info)

    if media_filter:
        if info["type"] == LinkType.TWITTER:
            filtered_media, filtered_links, filtered_sizes = [], [], []
            for media_type, media_link, media_size in zip(
                info["media"],
                info["links"],
                info["sizes"],
                strict=False,
            ):
                if media_type in media_filter:
                    filtered_media.append(media_type)
                    filtered_links.append(media_link)
                    filtered_sizes.append(media_size)
            if not filtered_media:
                log.debug("Send Media Doc: Didn't pass media filter.")
                return
            filtered_info["media"] = tuple(filtered_media)
            filtered_info["links"] = tuple(filtered_links)
            filtered_info["sizes"] = tuple(filtered_sizes)
        elif info["type"] == LinkType.PIXIV:
            if info["media"] not in media_filter:
                log.debug("Send Media Doc: Didn't pass media filter.")
                return
    log.debug("Send Media Doc: Passed media filter.")
    idx, documents = -1, []
    async for filename, file in download_media(filtered_info, order=order):
        if channel_mode:
            idx += 1
            if (
                filtered_info["type"] == LinkType.PIXIV
                and filtered_info["media"] in ("illust", "manga")
                or filtered_info["type"] == LinkType.TWITTER
                and filtered_info["media"][idx] == "photo"
            ):
                documents.append(
                    InputMediaPhoto(
                        media=file,
                        filename=filename,
                    )
                )
            else:
                documents.append(
                    InputMediaVideo(
                        media=file,
                        filename=filename,
                    )
                )
        else:
            documents.append(
                InputMediaDocument(
                    media=file,
                    filename=filename,
                    disable_content_type_detection=True,
                )
            )
    # answer to pixiv artwork
    if "reply_to_message_id" in kwargs and "message_id" in filtered_info:
        kwargs["reply_to_message_id"] = filtered_info["message_id"]
    return await ptb_app.send_media_group(
        media=documents,
        read_timeout=READ_MEDIA_TIMEOUT,
        write_timeout=WRITE_MEDIA_TIMEOUT,
        **kwargs,
    )
