""" "Posting functions module"""

import logging

# sqlalchemy exceptions
from sqlalchemy.exc import IntegrityError

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import ContextTypes

# pixiv & twitter styles, link types
from yaminui.api import LinkType, PixivStyle, TwitterStyle

# namedtuples
from yaminui.api.namedtuples import Link

# user data dataclass, posting results
from yaminui.bot import PostingResult, UserData

# bot auto-(re)posting
from yaminui.bot.answer_query import answer_query_post, answer_query_repost

# bot helpers
from yaminui.bot.helpers import normalize_order, pixiv_post, pixiv_save

# bot loggers
from yaminui.bot.loggers import notify

# bot senders
from yaminui.bot.senders import (
    send_error,
    send_media,
    send_media_doc,
    send_reply_post,
    send_warn,
)

# bot utils
from yaminui.bot.utils import extract_media_ids, get_links

# database session
from yaminui.db import Session

# database getters
from yaminui.db.getters import get_artwork

# database models
from yaminui.db.models import ArtWork, Post

# env variables
from yaminui.extra.settings import bot_settings

# uploading media
from yaminui.extra.upload import upload_media

# get logger
log = logging.getLogger(__name__)

# banned from posting on their own
ALERT_ID = int(bot_settings.alert_id)


async def just_posting_twitter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    art: dict,
    link: Link,
) -> PostingResult:
    if posts := await send_media(
        context=context,
        info=art,
        style=data.twitter,
        chat_id=data.chan,
        order=(
            await normalize_order(update, link.illust, len(art["links"]))
            if link.illust
            else None
        ),
        above=link.above,
    ):
        log.info("Post: Successfully forwarded to channel.")
        if data.twitter != TwitterStyle.LINK:
            posted = posts[0]
        art_dict = {
            "aid": link.id,
            "type": link.type,
            "files": await extract_media_ids(art),
        }
        post_dict = {
            "channel_id": data.chan,
            "is_original": True,
            "is_forwarded": False,
            "post_id": posted.message_id,
            "post_date": posted.date,
        }
        try:
            with Session.begin() as session:
                session.add(Post(**post_dict, artwork=ArtWork(**art_dict)))
        except IntegrityError:
            posts_id = [post.message_id for post in posts]
            log.info("Dublicate post detected!")
            log.info("Deleting: <%d> %s...", data.chan, posts_id)
            deleted = [await post.delete() for post in posts]
            if all(deleted):
                log.info("Deleted successfully.")
            else:
                log.critical("Failed to delete.")
                text = ", and ".join(
                    [
                        f"[here]({post.link})"
                        for post, is_deleted in zip(posts, deleted, strict=True)
                        if not is_deleted
                    ]
                )
                await send_error(f"Failed to delete double-post: {text}\\.")
            return
        log.info("Post: Inserted ArtWork: %s.", art_dict)
        log.info("Post: Inserted Post: %s.", post_dict)
        if data.reply:
            await send_reply_post(
                update,
                "posted",
                data.chan,
                posted.message_id,
                art["link"],
            )
        if data.media and data.twitter == TwitterStyle.LINK:
            await send_media_doc(
                context=context,
                info=art,
                media_filter=("video", "animated_gif", "ugoira"),
                channel_mode=True,
                chat_id=data.chan,
                reply_to_message_id=posted.message_id,
            )
        return PostingResult.STATE_POSTED
    return PostingResult.STATE_ERROR


async def just_posting_pixiv(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    art: dict,
    link: Link,
) -> PostingResult:
    if link.illust:
        data.info = art
        return await pixiv_post(update, context, data, link.illust, link.above)
    if len(art["links"]) == 1 or data.pixiv in (
        PixivStyle.INFO_LINK,
        PixivStyle.INFO_EMBED_LINK,
    ):
        if posts := await send_media(
            context=context,
            info=art,
            style=data.pixiv,
            chat_id=data.chan,
            above=link.above,
        ):
            log.info("Post: Successfully forwarded to channel.")
            if data.pixiv not in (
                PixivStyle.INFO_LINK,
                PixivStyle.INFO_EMBED_LINK,
            ):
                posted = posts[0]
            art_dict = {
                "aid": link.id,
                "type": link.type,
                "files": await extract_media_ids(art),
            }
            post_dict = {
                "channel_id": data.chan,
                "is_original": True,
                "is_forwarded": False,
                "post_id": posted.message_id,
                "post_date": posted.date,
            }
            try:
                with Session.begin() as session:
                    session.add(Post(**post_dict, artwork=ArtWork(**art_dict)))
            except IntegrityError:
                posts_id = [post.message_id for post in posts]
                log.info("Dublicate post detected!")
                log.info("Deleting: <%d> [%s]...", data.chan, posts_id)
                deleted = [post.delete() for post in posts]
                if all(deleted):
                    log.info("Deleted successfully.")
                else:
                    log.critical("Failed to delete.")
                    text = ", and ".join(
                        [
                            f"[here]({post.link})"
                            for post, is_deleted in zip(posts, deleted, strict=True)
                            if not is_deleted
                        ]
                    )
                    await send_error(f"Failed to delete double-post: {text}\\.")
            log.info("Post: Inserted ArtWork: %s.", art_dict)
            log.info("Post: Inserted Post: %s.", post_dict)
            if data.reply:
                await send_media(
                    context=context,
                    info=art,
                    style=data.pixiv,
                    chat_id=update.effective_chat.id,
                    reply_to_message_id=update.effective_message.message_id,
                )
                await send_reply_post(
                    update,
                    "posted",
                    data.chan,
                    posted.message_id,
                    art["link"],
                )
            return PostingResult.STATE_POSTED
        return PostingResult.STATE_ERROR
    await pixiv_save(update, art)
    return PostingResult.STATE_CONTINUE


async def just_posting(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    links: list[Link],
) -> None:
    notify(update, function="just_posting")
    # process links
    for link in links:
        if await get_artwork(link.id, link.type):
            if update.effective_user.id == ALERT_ID:
                log.warning("Post: [ALERT] Content is not original: %r.", link.link)
                try_reposting = await answer_query_repost(update, context, data, link)
                if try_reposting == PostingResult.STATE_REPOSTED:
                    log.warning("Post: [ALERT] Reposted.")
                elif try_reposting == PostingResult.STATE_SELFREPOST:
                    log.warning("Post: [ALERT] Can't self-repost.")
                else:
                    try_posting = await answer_query_post(update, context, data, link)
                    if try_posting == PostingResult.STATE_POSTED:
                        log.warning("Post: [ALERT] Posted.")
                    else:
                        log.warning("Post: [ALERT] Unsuccessful.")
            else:
                await send_warn(update, link)
                log.warning("Post: Content is not original: %r.", link.link)
            continue
        if not (art := await get_links(link)):
            await send_error(
                update,
                f"[This content]({link.link}) can't be found or "
                "downloaded\\. If this seems to be wrong, try again later\\.",
            )
            log.error("Post: Couldn't get content: %r.", link.link)
            continue
        art = art._asdict()
        notify(update, art=art)
        match link.type:
            # twitter links
            case LinkType.TWITTER:
                result = await just_posting_twitter(update, context, data, art, link)
            # pixiv links
            case LinkType.PIXIV:
                result = await just_posting_pixiv(update, context, data, art, link)
        # upload to cloud
        if result == PostingResult.STATE_POSTED:
            await upload_media(art, update.effective_chat.id)
