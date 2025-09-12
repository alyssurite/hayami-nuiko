"""Senders module"""

import logging

from copy import deepcopy
from html import escape as escape_html
from typing import Callable, Optional

# telegram core bot api
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
    Message,
    Update,
)

# telegram constants
from telegram.constants import ParseMode as PM

# telegram errors
from telegram.error import RetryAfter, TimedOut

# telegram core bot api extension
from telegram.ext import ContextTypes

# hardcore retrying
from tenacity import AsyncRetrying, RetryCallState, before_sleep_log, stop_after_attempt

# pixiv & twitter styles, link types
from yaminui.api import LINKS, LinkType, PixivStyle, TwitterStyle

# link namedtuple
from yaminui.api.namedtuples import Link

# escape markdown, constants
from yaminui.bot import READ_MEDIA_TIMEOUT, WRITE_MEDIA_TIMEOUT, esc

# bot utils
from yaminui.bot.utils import get_post_link

# database getters
from yaminui.db.getters import get_other_links

# database models
from yaminui.db.models import Post

# downloading media
from yaminui.extra.download import download_media

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
async def send_error(update: Update, text: str, do_quote=True, **kwargs) -> Message:
    """Reply to current message with error

    Args:
        update (Update): current update
        text (str): text to send in markdown v2
        quote (bool): if message with error should be quoted. Defaults to True.

    Returns:
        Message: Telegram Message
    """
    return await send_reply(update, "\\[`ERROR`\\] " + text, do_quote=True, **kwargs)


@retry_sending
async def send_post_info(update: Update, post: Post, **kwargs) -> Message:
    """Reply to current message

    Args:
        update (Update): current update
        text (str): text to send in markdown v2

    Returns:
        Message: Telegram Message
    """
    channel_link = f"t\\.me/{esc(post.channel.link)}" if post.channel.link else "`None`"
    post_link = (
        f"{channel_link}/{post.post_id}"
        if post.channel.link
        else f"t\\.me/c/{post.channel.cid}/{post.post_id}"
    )
    info = []
    info.append(f"*DB Record ID*: `{post.id}`")

    # post
    info.append("*Post info*:")
    info.append(f"> *Post ID*: `{post.post_id}`")
    info.append(f"> *Post DateTime*: `{post.post_date}`")
    info.append(f"> *Original\\?*: `{post.is_original}`")
    info.append(f"> *Forwarded\\?*: `{post.is_forwarded}`")

    # channel
    info.append("*Channel info*:")
    info.append(f"> *Channel ID*: `{post.channel.cid}`")
    # info.append(f"> *Channel Bot API ID*: `{post.channel.id}`")
    info.append(f"> *Channel name*: {esc(post.channel.name)}")
    info.append(f"> *Channel link*: {channel_link}")
    info.append(f"> *Channel owner*: `{post.channel.admin_id}`")

    # artwork
    info.append("*Artwork info*:")
    info.append(f"> *Artwork ID*: `{post.artwork_id}`")
    info.append(f"> *Artwork type*: `{post.artwork.type}`")
    info.append(f"> *Artwork AID*: `{post.artwork.aid}`")
    if post.artwork.files:
        files = (
            f"{post.artwork.files[0]}\\_p"
            if post.artwork.type
            else "`\n> \t\t`".join(map(esc, post.artwork.files))
        )
        info.append(f"> *Artwork files*: \\[\n> \t\t`{files}`\n> \\]")

    # forward channel
    if post.is_forwarded and post.forwarded_channel_id:
        info.append("*Forwarded from channel*:")
        forwarded_channel_link = (
            f"t\\.me/{esc(post.forwarded_channel.link)}"
            if post.forwarded_channel.link
            else "`None`"
        )
        info.append(f"> *Channel ID*: `{post.forwarded_channel.cid}`")
        # info.append(f"> *Channel Bot API ID*: `{post.forwarded_channel.id}`")
        info.append(f"> *Channel name*: {esc(post.forwarded_channel.name)}")
        info.append(f"> *Channel link*: {forwarded_channel_link}")
        info.append(f"> *Channel owner*: `{post.forwarded_channel.admin_id}`")

    # links
    info.append("")
    info.append(f"*Universal link*: t\\.me/c/{post.channel.cid}/{post.post_id}")
    if channel_link:
        info.append(f"*Public link*: {post_link}")
    return await send_reply(
        update,
        "\n".join(info),
        link_preview_options=LinkPreviewOptions(
            url=f"https://{post_link}".replace("\\", ""),
            prefer_large_media=True,
            show_above_text=True,
        ),
    )


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
    url = (
        f"{link.link}"
        f"{'+' + link.illust if link.illust else ''}"
        f"{'!' if link.above else ''}"
    )
    return await send_reply(
        update,
        f"This [artwork]({esc(url)}) was already posted: {text}\\.\n\n"
        "`\\[` ⚠️ *POST IT ANYWAY\\?* ⚠️ `\\]`",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="♻️ Repost! ♻️",
                        callback_data="duplicate:repost",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🚩 Post!  🚩",
                        callback_data="duplicate:post",
                    ),
                ],
            ]
        ),
        do_quote=True,
        **kwargs,
    )


@retry_sending
async def send_warn_delete(update: Update, post: Post, **kwargs) -> Message:
    """Reply to current message with warning

    Args:
        update (Update): current update
        link (Link): link to the artwork

    Returns:
        Message: Telegram Message
    """
    ...
    hard_link = f"t.me/c/{-(post.channel_id + 10**12)}/{post.post_id}"
    art_link = ""
    if post.artwork.type == LinkType.TWITTER:
        art_link = LINKS["twitter"]["link_id"].format(id=post.artwork.aid)
    elif post.artwork.type == LinkType.PIXIV:
        art_link = LINKS["pixiv"]["link"].format(id=post.artwork.aid)
    if post.channel.link:
        view_link = f"t.me/{post.channel.link}/{post.post_id}"
    else:
        view_link = hard_link
    return await send_reply(
        update,
        f"Are you sure you want to delete [*this post*]({view_link})\\? "
        f"[🔗]({hard_link}) \\| [🖼]({art_link})\n\n"
        "*Note*: This action will delete this post from database and your channel\\. "
        "If there're several pictures/videos, all of them will be deleted too\\!\n\n"
        "`\\[` ⚠️ *DELETE POST\\?* ⚠️ `\\]`",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="⭕ YES",
                        callback_data=f"delete:yes:{post.id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ NO!",
                        callback_data=f"delete:no:{post.id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⛔ CANCEL",
                        callback_data=f"delete:cancel:{post.id}",
                    )
                ],
            ]
        ),
        do_quote=True,
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
async def send_post(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    parse_mode: str = None,
    info: dict = None,
    text: str = None,
    **kwargs,
) -> Optional[Message]:
    """Send post to channel

    Args:
        context (ContextTypes.DEFAULT_TYPE): current context
        info (dict): art media dictionary
        text (str): text to send

    Returns:
        Optional[Message]: Telegram Message
    """
    if info:
        text = esc(info["link"])
    if text:
        return await context.bot.send_message(
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
    context: ContextTypes.DEFAULT_TYPE,
    info: dict,
    *,
    order: list[int] = None,
    style: int = None,
    above: bool = False,
    **kwargs,
) -> Optional[Message]:
    """Sends media as media group

    Args:
        context (ContextTypes.DEFAULT_TYPE): current context
        info (dict): art media dictionary
        order (list[int], optional): which artworks to upload. Defaults to None.
        style (int, optional): pixiv style. Defaults to None.
        above (bool, optional): show description above the image. Defaults to False.

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
                    context,
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
                    context,
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
                    show_caption_above_media=above,
                )
            )
        else:
            media.append(
                InputMediaVideo(
                    media=file,
                    filename=filename,
                    caption=caption if not idx else None,
                    parse_mode=parse_mode if not idx else None,
                    show_caption_above_media=above,
                )
            )
    # answer to pixiv artwork
    if "reply_to_message_id" in kwargs and "message_id" in info:
        kwargs["reply_to_message_id"] = info["message_id"]
    return await context.bot.send_media_group(
        media=media,
        read_timeout=READ_MEDIA_TIMEOUT,
        write_timeout=WRITE_MEDIA_TIMEOUT,
        **kwargs,
    )


@retry_sending
async def send_media_doc(
    context: ContextTypes.DEFAULT_TYPE,
    info: dict,
    *,
    media_filter: list[str] = None,
    channel_mode: bool = False,
    order: list[int] = None,
    **kwargs,
) -> Optional[Message]:
    """Send media as documents

    Args:
        context (ContextTypes.DEFAULT_TYPE): current context
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
    return await context.bot.send_media_group(
        media=documents,
        read_timeout=READ_MEDIA_TIMEOUT,
        write_timeout=WRITE_MEDIA_TIMEOUT,
        **kwargs,
    )
