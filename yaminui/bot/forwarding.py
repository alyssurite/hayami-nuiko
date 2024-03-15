"""Forwarding/No forwarding functions module"""
import asyncio
import logging

# working with timezone
from datetime import timezone as tz

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import CallbackContext

# link types
from ..api import LinkType

# namedtuples
from ..api.namedtuples import Link

# database session
from ..db import Session

# database getters
from ..db.getters import get_artwork, get_other_links

# database models
from ..db.models import ArtWork, Channel, Post

# uploading media
from ..extra.upload import upload_media

# bot constants, user data dataclass, etc.
from . import DELAY_START, JOB_SLEEP, MISFIRE_GRACE_TIME, UserData, esc, pyro_app

# bot helpers
from .helpers import normalize_order, pixiv_save

# bot loggers
from .loggers import notify

# bot senders
from .senders import (
    forward,
    send_error,
    send_media,
    send_media_doc,
    send_reply,
    send_reply_post,
)

# bot utils
from .utils import check_message_media, extract_media_ids, get_links

# get logger
log = logging.getLogger(__name__)


async def get_message_date(chat_id: int, message_id: int):
    return (await pyro_app.get_messages(chat_id, message_id)).date.astimezone(tz.utc)


async def media_group_sender(context: CallbackContext):
    notify(context.job.data["update"], group_sender=context.job.data)
    # get all the data
    data = context.job.data
    if not data["post_id"]:
        return
    posted = await context.bot.forward_messages(
        chat_id=data["channel_id"],
        from_chat_id=data["chat_id"],
        message_ids=sorted(data["post_id"]),
    )
    if posted:
        post_id = posted[0].message_id
        log.info("Group Sender: Successfully forwarded to channel: %d.", post_id)
        data["post_dict"].update(
            {
                "post_id": post_id,
                "post_date": await get_message_date(data["channel_id"], post_id),
            }
        )
        with Session.begin() as session:
            session.add(Post(**data["post_dict"], artwork=data["artwork"]))
        log.info("Group Sender: Inserted Post: %s.", data["post_dict"])
        if data["user_data"].reply:
            await send_reply_post(
                data["update"],
                "forwarded",
                data["channel_id"],
                post_id,
                data["link"],
            )


async def get_first_link(update: Update, links: list[Link]) -> Link:
    """Gets the first link from the list. Also warns user if there's more than 1 link.

    Args:
        update (Update): current update.
        links (list[Link]): link list.

    Returns:
        Link: the first link in the list.
    """
    if len(links) > 1:
        log.warning("Forward: More than 1 link.")
        for idx, link in enumerate(links, 1):
            log.warning("Forward: > Link #%d: %r.", idx, link)
        await send_reply(
            update,
            "\\[`WARNING`\\] There's more than *one link* in this post\\! "
            "The bot will automatically use the first one it parses, that is, "
            f"[this one]({links[0].link})\\.",
            quote=True,
        )
    return links[0]


async def get_posted(update: Update, data: UserData, link: Link) -> None:
    """Gets links to posts with current artwork in the same channel.

    Args:
        update (Update): current update.
        data (UserData): current user's data.
        link (Link): artwork link.
    """
    if posted := await get_other_links(link.id, link.type, data.chan):
        text = ", and ".join([f"[here]({esc(post)})" for post in posted])
        await send_reply(
            update,
            f"\\[`INFO`\\] Just so you know, you already posted this artwork {text}\\.",
            quote=True,
        )
        log.warning("Forward: Content is not original within channel: %r.", link.link)


async def just_forwarding_group(
    update: Update,
    context: CallbackContext,
    data: UserData,
    links: list[Link] = None,
) -> None:
    notify(update, function="just_forwarding_group")
    job_queue = context.job_queue
    media_group_id, message_id, chat_id, source_chat = (
        update.effective_message.media_group_id,  # used as job name
        update.effective_message.message_id,
        update.effective_chat.id,
        update.effective_message.forward_from_chat,
    )
    # check if there's links in message
    if not links:
        while True:
            if jobs := job_queue.get_jobs_by_name(media_group_id):
                jobs[0].data["post_id"].append(message_id)
                return
            await asyncio.sleep(JOB_SLEEP)
    await get_posted(update, data, link := await get_first_link(update, links))
    art_dict = {
        "aid": link.id,
        "type": link.type,
    }
    post_dict = {
        "channel_id": data.chan,
        "is_original": False,
        "is_forwarded": True,
    }
    # can be ignored for this one
    if art := await get_links(link):
        art = art._asdict()
        notify(update, art=art)
        art_dict["files"] = await extract_media_ids(art)
    else:
        log.warning("Forward Group: Couldn't get content: %r.", link.link)
    if not (artwork := await get_artwork(link.id, link.type)):
        artwork = ArtWork(**art_dict)
        log.info("Forward Group: ArtWork to insert: %s.", art_dict)
        post_dict["is_original"] = True
    else:
        log.info("Forward Group: Used ArtWork: %s.", art_dict)
    # check if it's forwarded from channel in database
    with Session() as session:
        if source_chat:
            if channel := session.get(Channel, source_chat.id):
                if channel.id == data.chan:
                    await send_error(update, "You shouldn't *self\\-forward*\\!")
                    log.error("Forward Group: Self-forwarding is not allowed.")
                    return
                post_dict["forwarded_channel_id"] = channel.id
                log.info("Forward Group: Source: <%d> %r.", channel.id, channel.name)
            else:
                log.info("Forward Group: Source: Unknown.")
        else:
            log.info("Forward Group: Source: Not a channel.")
    msg_dict = {
        "channel_id": data.chan,
        "artwork": artwork,
        "post_dict": post_dict,
        "user_data": data,
        "update": update,
        "link": art["link"] if art else link.link,
        "chat_id": chat_id,
        "post_id": [message_id],
    }
    # upload to cloud
    if art:
        if art["type"] == LinkType.PIXIV:
            log.info("Forward Group: Skipping uploading pixiv media...")
        else:
            await upload_media(art, chat_id)
    job_queue.run_once(
        callback=media_group_sender,
        when=DELAY_START,
        data=msg_dict,
        name=media_group_id,
        job_kwargs={"misfire_grace_time": MISFIRE_GRACE_TIME},
    )


async def just_forwarding(
    update: Update,
    context: CallbackContext,
    data: UserData,
    links: list[Link],
) -> None:
    notify(update, function="just_forwarding")
    await get_posted(update, data, link := await get_first_link(update, links))
    art_dict = {
        "aid": link.id,
        "type": link.type,
    }
    post_dict = {
        "channel_id": data.chan,
        "is_original": False,
        "is_forwarded": True,
    }
    # can be ignored for this one
    if art := await get_links(link):
        art = art._asdict()
        notify(update, art=art)
        art_dict["files"] = await extract_media_ids(art)
    else:
        log.warning("Forward: Couldn't get content: %r.", link.link)
    if not (artwork := await get_artwork(link.id, link.type)):
        artwork = ArtWork(**art_dict)
        log.info("Forward: ArtWork to insert: %s.", art_dict)
        post_dict["is_original"] = True
    else:
        log.info("Forward: Used ArtWork: %s.", art_dict)
    # check if it's forwarded from channel in database
    with Session() as session:
        if source := update.effective_message.forward_from_chat:
            if channel := session.get(Channel, source.id):
                if channel.id == data.chan:
                    await send_error(update, "You shouldn't *self\\-forward*\\!")
                    log.error("Forward: Self-forwarding is not allowed.")
                    return
                post_dict["forwarded_channel_id"] = channel.id
                log.info("Forward: Source: <%d> %r.", channel.id, channel.name)
            else:
                log.info("Forward: Source: Unknown.")
        else:
            log.info("Forward: Source: Not a channel.")
    # just forward it
    if posted := await forward(update, data.chan):
        log.info("Forward: Successfully forwarded to channel.")
        post_dict.update(
            {
                "post_id": posted.message_id,
                "post_date": posted.date,
            }
        )
        with Session.begin() as session:
            session.add(Post(**post_dict, artwork=artwork))
        log.info("Forward: Inserted Post: %s.", post_dict)
        if data.reply:
            await send_reply_post(
                update,
                "forwarded",
                data.chan,
                posted.message_id,
                art["link"] if art else link.link,
            )
        if data.media and not await check_message_media(update):
            if art:
                if await send_media_doc(
                    context=context,
                    info=art,
                    media_filter=("video", "animated_gif", "ugoira"),
                    channel_mode=True,
                    chat_id=data.chan,
                    reply_to_message_id=posted.message_id,
                ):
                    log.info("Forward: Successfully replied with media.")
            else:
                await send_error(
                    update,
                    "*Media mode*\\: Couldn't get this content\\!",
                )
                log.warning("Forward: Couldn't reply with media.")
    # upload to cloud
    if art:
        if link.type == LinkType.PIXIV and len(art["links"]) > 1:
            log.info("Forward: Skipping uploading pixiv media...")
        else:
            await upload_media(art, update.effective_chat.id)


async def no_forwarding(
    update: Update,
    context: CallbackContext,
    data: UserData,
    links: list[Link],
) -> None:
    notify(update, function="no_forwarding")
    # process links
    for link in links:
        if not (art := await get_links(link)):
            await send_error(
                update,
                f"[This content]({link.link}) can\\'t be found or "
                "downloaded\\. If this seems to be wrong, try again later\\.",
            )
            log.error("No Forward: Couldn't get content: %r.", link.link)
            continue
        art = art._asdict()
        notify(update, art=art)
        com = {
            "context": context,
            "info": art,
            "chat_id": update.effective_chat.id,
            "reply_to_message_id": update.effective_message.message_id,
            "order": (
                await normalize_order(update, link.illust, len(art["links"]))
                if link.illust
                else None
            ),
        }
        match link.type:
            # twitter links
            case LinkType.TWITTER:
                if data.reply:
                    await send_media(**com, style=data.twitter)
                await send_media_doc(**com)
            # one pixiv link
            case LinkType.PIXIV:
                if len(art["links"]) > 1 and not com["order"]:
                    log.info("No Forward: There's more than 1 artwork.")
                    await pixiv_save(update, art)
                    return
                if com["order"]:
                    log.info("No Forward: Illustrations provided: %s.", com["order"])
                else:
                    log.info("No Forward: There's only 1 artwork.")
                if data.reply:
                    await send_media(**com, style=data.pixiv)
                await send_media_doc(**com)
        # upload to cloud
        await upload_media(art, update.effective_chat.id)
