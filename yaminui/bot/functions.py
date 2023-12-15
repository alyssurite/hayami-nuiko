"""Functions module"""
import asyncio
import logging
import re

# telegram core bot api
from telegram import Chat, Update

# telegram core bot api extension
from telegram.ext import CallbackContext

# pixiv styles, link types
from ..api import LinkType, TwitterStyle

# get queue size
from ..bot import QUEUE_SIZE, ptb_app

# database session
from ..db import Session

# database getters
from ..db.getters import get_artwork, get_user_data

# database models
from ..db.models import ArtWork, Channel, Post, User

# database updaters
from ..db.updaters import update_chat
from ..extra.upload import upload_media

# bot forwarding
from .forwarding import just_forwarding, just_forwarding_group, no_forwarding

# normalize order
from .helpers import just_normalize_order

# bot loggers
from .loggers import notify

# bot posting
from .posting import just_posting, pixiv_post

# bot senders
from .senders import (
    send_api_reply_post,
    send_api_warn,
    send_error,
    send_media,
    send_media_doc,
)

# bot utils
from .utils import extract_media_ids, formatter, get_links, get_text

# get logger
log = logging.getLogger(__name__)

# pixiv regex
pixiv_regex = re.compile(r"^((?:\d+)(?:-\d+)?[.,\s]*){1,10}$")

# update queue limiter
queue = asyncio.Queue(QUEUE_SIZE)


async def universal(update: Update, context: CallbackContext) -> None:
    """Universal function for handling posting

    Args:
        update (Update): current update
        context (CallbackContext): current context
    """
    notify(update.effective_chat, command="universal")
    # update & get user data
    await update_chat(update.effective_chat)
    if not (data := await get_user_data(update)):
        await send_error(
            update,
            "You have no channel\\! Send /channel or /forward\\.",
        )
        log.error("Universal: No data: <%d>.", update.effective_chat.id)
        return
    # check for text
    if not (text := await get_text(update)):
        if media_group_id := update.effective_message.media_group_id:
            log.info("Universal: Part of the media group: %r.", media_group_id)
            return await just_forwarding_group(update, context, data)
        # no text found!
        log.error("Universal: No text.")
        log.info("Universal: Received update: %r.", update)
        return
    log.info("Universal: Received text: %r.", text)
    try:
        # put into limited queue
        await queue.put(update.update_id)
        # check for links
        if links := await formatter(text):
            if len(links) > 1:
                if any(link.type == LinkType.PIXIV for link in links):
                    await send_error(
                        update,
                        "Can't process pixiv links in *batch* mode\\.",
                    )
                    log.warning("Universal: Pixiv links are not allowed.")
                links = [link for link in links if link.type != LinkType.PIXIV]
            if not data.forward:
                log.info("Universal: no_forwarding.")
                await no_forwarding(update, context, data, links)
            else:
                if update.effective_message.forward_date and not (
                    update.effective_message.forward_from
                    and update.effective_message.forward_from.is_bot
                ):
                    if update.effective_message.media_group_id:
                        log.info("Universal: just_forwarding_group.")
                        await just_forwarding_group(update, context, data, links)
                    elif update.effective_message.effective_attachment:
                        log.info("Universal: just_forwarding.")
                        await just_forwarding(update, context, data, links)
                else:
                    log.info("Universal: just_posting.")
                    await just_posting(update, context, data, links)
        elif data.info and re.search(pixiv_regex, text):
            log.info("Universal: pixiv_post.")
            await pixiv_post(update, context, data, text)
        else:
            log.info("Universal: No idea what to do with message: %r.", text)
    finally:
        # mark done and remove from limited queue
        queue.task_done()
        await queue.get()


async def handle_post(update: Update, _: CallbackContext) -> None:
    """Handles posts in channel"""
    notify(update.effective_chat, command="handle_post")
    # update channel
    await update_chat(update.effective_chat)
    # check for text
    if not (text := await get_text(update)):
        log.info("Handle Post: Received update: %r.", update)
        log.error("Handle Post: No text.")
        return
    log.info("Handle Post: Received text: %r.", text)
    # get links
    if not (links := await formatter(text)):
        log.warning("Handle Post: No links found.")
        return
    if len(links) > 1:
        log.warning("Handle Post: %d links found:", len(links))
        for index, link in enumerate(links):
            log.warning("Handle Post: %d: %r.", index, link.link)
        log.warning("Handle Post: Only the first one will be processed.")
    # process link
    link = links[0]
    log.info("Handle Post: Processing link: %r.", link.link)
    post_dict = {
        "channel_id": update.effective_chat.id,
        "is_original": False,
        "is_forwarded": bool(update.effective_message.forward_date),
        "post_id": update.effective_message.message_id,
        "post_date": update.effective_message.date,
    }
    art_dict = {"aid": link.id, "type": link.type}
    # can be ignored for this one
    if art := await get_links(link):
        art = art._asdict()
        notify(update.effective_chat, art=art)
        art_dict["files"] = await extract_media_ids(art)
    else:
        log.warning("Handle Post: Couldn't get content: %r.", link.link)
    # get artwork if already in database
    if not (artwork := await get_artwork(art_dict["aid"], art_dict["type"])):
        # otherwise create a new one
        artwork = ArtWork(**art_dict)
        log.info("Handle Post: ArtWork to insert: %s.", art_dict)
        post_dict["is_original"] = True
    with Session.begin() as session:
        # check if post is already processed
        if (
            session.query(Post)
            .filter_by(channel_id=update.effective_chat.id)
            .filter_by(post_id=update.effective_message.message_id)
            .first()
        ):
            log.info("Handle Post: Already in database. Skipping...")
            return
        # check for source channel
        if source := update.effective_message.forward_from_chat:
            if channel := session.get(Channel, source.id):
                post_dict["forwarded_channel_id"] = channel.id
                log.info("Handle Post: Source: <%d> %r..", channel.id, channel.name)
            else:
                log.info("Handle Post: Source: Unknown.")
        else:
            log.info("Handle Post: Source: Not a channel.")
        # insert in database
        session.add(Post(**post_dict, artwork=artwork))
    log.info("Handle Post: Inserted ArtWork: %s.", art_dict)
    log.info("Handle Post: Inserted Post: %s.", post_dict)


async def api_post(user: User, text: str) -> None:
    """Handles api posting to channel"""
    chat: Chat = await ptb_app.get_chat(user.id)
    notify(chat, command="api_post")
    # check for text
    if not text:
        log.error("API Post: No text.")
        return {"code": 400, "error": "No text."}
    log.info("API Post: Received link: %r.", text)
    # get links
    if not (links := await formatter(text)):
        log.warning("API Post: No links found.")
        return {
            "code": 400,
            "error": "No valid links.",
        }
    # process link
    link = links[0]
    log.info("API Post: Processing link: %r.", link.link)
    post_dict = {
        "channel_id": user.channel.id,
        "is_original": False,
        "is_forwarded": False,
    }
    art_dict = {"aid": link.id, "type": link.type}
    # can be ignored for this one
    if art := await get_links(link):
        art = art._asdict()
        notify(chat, art=art)
        art_dict["files"] = await extract_media_ids(art)
    else:
        log.warning("API Post: Couldn't get content: %r.", link.link)
        return {
            "code": 404,
            "error": "No content.",
        }
    # get artwork if already in database
    if await get_artwork(art_dict["aid"], art_dict["type"]):
        await send_api_warn(chat, link)
        return {
            "code": 409,
            "error": "Already posted. Choose an action in the chat.",
        }
    # otherwise create a new one
    post_dict["artwork"] = ArtWork(**art_dict)
    log.info("API Post: ArtWork to insert: %s.", art_dict)
    post_dict["is_original"] = True
    # twitter only for now
    match art["type"]:
        case LinkType.PIXIV:
            return {
                "code": 501,
                "error": "Currently, pixiv is not supported.",
            }
        # case LinkType.TWITTER:
    if posted := await send_media(
        info=art,
        style=user.twitter_style,
        chat_id=user.channel.id,
        order=(await just_normalize_order(link.illust, len(art["links"])))[2],
    ):
        log.info("API Post Twitter: Successfully posted to channel.")
        if user.twitter_style != TwitterStyle.LINK:
            posted = posted[0]
        post_dict.update(
            {
                "post_id": posted.message_id,
                "post_date": posted.date,
            }
        )
        with Session.begin() as session:
            session.add(Post(**post_dict))
        log.info("API Post Twitter: Inserted Post: %s.", post_dict)
        if user.reply_mode:
            await send_api_reply_post(
                chat,
                "posted",
                user.channel.id,
                posted.message_id,
                art["link"],
            )
        if user.media_mode and user.twitter_style == TwitterStyle.LINK:
            await send_media_doc(
                info=art,
                media_filter=("video", "animated_gif", "ugoira"),
                channel_mode=True,
                chat_id=user.channel.id,
                reply_to_message_id=posted.message_id,
            )
        await upload_media(art, user.id)
        post_dict["artwork"] = art_dict
        return {
            "code": 200,
            "post": post_dict,
        }
