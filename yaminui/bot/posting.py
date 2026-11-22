""" "Posting functions module"""

import time

import structlog

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
from yaminui.bot.helpers import pixiv_post, pixiv_save

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
log = structlog.get_logger(__name__)

# banned from posting on their own
ALERT_ID = int(bot_settings.alert_id)

# readable names for posting results, e.g. 0 -> "STATE_POSTED"
_RESULT_NAMES = {
    value: name
    for name, value in vars(PostingResult).items()
    if name.startswith("STATE_")
}


def _state_name(result) -> str:
    """Readable name of a posting result (for logs only)."""
    return _RESULT_NAMES.get(result, repr(result))


async def just_posting_twitter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    art: dict,
    link: Link,
) -> PostingResult:
    plog = log.bind(
        user_id=update.effective_user.id,
        art_id=link.id,
        art_type=str(link.type),
        channel_id=data.chan,
        links=len(art["links"]),
        style=str(data.twitter),
        above=link.above,
    )
    if link.illust:
        plog.info("Post: [twitter] specific selection requested.", illust=link.illust)
        data.info = art
        return await pixiv_post(update, context, data, link.illust, link.above)
    if len(art["links"]) == 1 or data.twitter == TwitterStyle.LINK:
        plog.info(
            "Post: [twitter] sending directly.",
            reason="single image" if len(art["links"]) == 1 else "link style",
        )
        if posts := await send_media(
            context=context,
            info=art,
            style=data.twitter,
            chat_id=data.chan,
            above=link.above,
        ):
            plog.info(
                "Post: Successfully forwarded to channel.",
                messages=len(posts),
            )
            posted = posts[0]
            art_dict = {
                "aid": link.id,
                "type": link.type,
                "files": await extract_media_ids(art),
            }
            if len(art_dict["files"]) != len(art["links"]):
                plog.warning(
                    "Post: Twitter files count mismatch.",
                    files=len(art_dict["files"]),
                    links=len(art["links"]),
                )
            post_dict = {
                "channel_id": data.chan,
                "is_original": True,
                "is_forwarded": False,
                "post_id": posted.message_id,
                "post_date": posted.date,
            }
            if not (artwork := await get_artwork(link.id, link.type)):
                artwork = ArtWork(**art_dict)
                post_dict["is_original"] = True
                plog.info("Post: [twitter] ArtWork to insert.", art_dict=art_dict)
            else:
                plog.info(
                    "Post: [twitter] Used existing ArtWork.",
                    artwork_id=artwork.id,
                    stored_files=len(artwork.files or []),
                    new_files=len(art_dict["files"]),
                )
                if not artwork.files or len(artwork.files) < len(art_dict["files"]):
                    plog.info("Post: [twitter] Updating ArtWork files.")
                    artwork.files = art_dict["files"]
            try:
                with Session.begin() as session:
                    session.add(
                        Post(
                            **post_dict,
                            artwork=session.merge(artwork) if artwork.id else artwork,
                        )
                    )
            except IntegrityError as exc:
                posts_id = [post.message_id for post in posts]
                plog.warning(
                    "Post: [twitter] Duplicate post detected!",
                    error=str(getattr(exc, "orig", exc)),
                )
                plog.info("Post: [twitter] Deleting duplicate.", posts_id=posts_id)
                deleted = [await post.delete() for post in posts]
                if all(deleted):
                    plog.info("Post: [twitter] Deleted duplicate successfully.")
                else:
                    plog.critical(
                        "Post: [twitter] Failed to delete duplicate.",
                        posts_id=posts_id,
                        deleted=deleted,
                    )
                    text = ", and ".join(
                        [
                            f"[here]({post.link})"
                            for post, is_deleted in zip(posts, deleted, strict=True)
                            if not is_deleted
                        ]
                    )
                    await send_error(
                        update,
                        f"Failed to delete double-post: {text}\\.",
                    )
                plog.info("Post: [twitter] Aborted after duplicate.")
                return PostingResult.STATE_ERROR
            plog.info("Post: Inserted ArtWork.", art_dict=art_dict)
            plog.info("Post: Inserted Post.", post_dict=post_dict)
            if data.reply:
                plog.debug("Post: [twitter] Sending reply.")
                await send_reply_post(
                    update,
                    "posted",
                    data.chan,
                    posted.message_id,
                    art["link"],
                )
            if data.media and data.twitter == TwitterStyle.LINK:
                plog.debug("Post: [twitter] Sending media docs to channel.")
                await send_media_doc(
                    context=context,
                    info=art,
                    media_filter=("video", "animated_gif", "ugoira"),
                    channel_mode=True,
                    chat_id=data.chan,
                    reply_to_message_id=posted.message_id,
                )
            plog.info("Post: [twitter] finished.")
            return PostingResult.STATE_POSTED
        plog.error("Post: [twitter] send_media returned nothing.")
        return PostingResult.STATE_ERROR
    elif len(art["links"]) > 1:
        plog.info("Post: There's more than 1 artwork.")
        data.info = art
        if len(art["links"]) > 10:
            plog.info(
                "Post: [twitter] more than 10 images, selection required.",
                max_auto=10,
            )
            await pixiv_save(update, art)
            return PostingResult.STATE_CONTINUE
        else:
            selection = f"1-{len(art['links'])}"
            plog.info(
                "Post: [twitter] 10 images or fewer, posting all.",
                selection=selection,
            )
            return await pixiv_post(update, context, data, selection, link.above)
    plog.error("Post: [twitter] no images to post.", links=len(art["links"]))
    return PostingResult.STATE_ERROR


async def just_posting_pixiv(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    art: dict,
    link: Link,
) -> PostingResult:
    plog = log.bind(
        user_id=update.effective_user.id,
        art_id=link.id,
        art_type=str(link.type),
        channel_id=data.chan,
        links=len(art["links"]),
        style=str(data.pixiv),
        above=link.above,
    )
    if link.illust:
        plog.info("Post: [pixiv] specific selection requested.", illust=link.illust)
        data.info = art
        return await pixiv_post(update, context, data, link.illust, link.above)
    if len(art["links"]) == 1 or data.pixiv in (
        PixivStyle.INFO_LINK,
        PixivStyle.INFO_EMBED_LINK,
    ):
        plog.info(
            "Post: [pixiv] sending directly.",
            reason="single image" if len(art["links"]) == 1 else "link style",
        )
        if posts := await send_media(
            context=context,
            info=art,
            style=data.pixiv,
            chat_id=data.chan,
            above=link.above,
        ):
            plog.info(
                "Post: Successfully forwarded to channel.",
                messages=len(posts),
            )
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
            except IntegrityError as exc:
                posts_id = [post.message_id for post in posts]
                plog.warning(
                    "Post: [pixiv] Duplicate post detected!",
                    error=str(getattr(exc, "orig", exc)),
                )
                plog.info("Post: [pixiv] Deleting duplicate.", posts_id=posts_id)
                deleted = [await post.delete() for post in posts]
                if all(deleted):
                    plog.info("Post: [pixiv] Deleted duplicate successfully.")
                else:
                    plog.critical(
                        "Post: [pixiv] Failed to delete duplicate.",
                        posts_id=posts_id,
                        deleted=deleted,
                    )
                    text = ", and ".join(
                        [
                            f"[here]({post.link})"
                            for post, is_deleted in zip(posts, deleted, strict=True)
                            if not is_deleted
                        ]
                    )
                    await send_error(
                        update,
                        f"Failed to delete double-post: {text}\\.",
                    )
                plog.info("Post: [pixiv] Aborted after duplicate.")
                return PostingResult.STATE_ERROR
            plog.info("Post: Inserted ArtWork.", art_dict=art_dict)
            plog.info("Post: Inserted Post.", post_dict=post_dict)
            if data.reply:
                plog.debug("Post: [pixiv] Sending reply.")
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
            plog.info("Post: [pixiv] finished.")
            return PostingResult.STATE_POSTED
        plog.error("Post: [pixiv] send_media returned nothing.")
        return PostingResult.STATE_ERROR
    plog.info("Post: [pixiv] multiple images, selection required.")
    await pixiv_save(update, art)
    return PostingResult.STATE_CONTINUE


async def just_posting(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    links: list[Link],
) -> None:
    notify(update, function="just_posting")
    jlog = log.bind(user_id=update.effective_user.id, channel_id=data.chan)
    jlog.info("Posting: started.", total_links=len(links))
    # process links
    for index, link in enumerate(links, start=1):
        started = time.perf_counter()
        llog = jlog.bind(
            link=link.link,
            link_id=link.id,
            link_type=str(link.type),
            position=f"{index}/{len(links)}",
        )
        llog.debug("Post: processing link.", illust=link.illust, above=link.above)
        if await get_artwork(link.id, link.type):
            llog.info("Post: ArtWork already exists in database.")
            if update.effective_user.id == ALERT_ID:
                llog.warning("Post: [ALERT] Content is not original.")
                try_reposting = await answer_query_repost(update, context, data, link)
                llog.debug(
                    "Post: [ALERT] Repost attempt finished.",
                    result=_state_name(try_reposting),
                )
                if try_reposting == PostingResult.STATE_REPOSTED:
                    llog.warning("Post: [ALERT] Reposted.")
                elif try_reposting == PostingResult.STATE_SELFREPOST:
                    llog.warning("Post: [ALERT] Can't self-repost.")
                else:
                    try_posting = await answer_query_post(update, context, data, link)
                    if try_posting == PostingResult.STATE_POSTED:
                        llog.warning("Post: [ALERT] Posted.")
                    else:
                        llog.warning(
                            "Post: [ALERT] Unsuccessful.",
                            result=_state_name(try_posting),
                        )
            else:
                await send_warn(update, link)
                llog.warning("Post: Content is not original, skipped.")
            continue
        if not (art := await get_links(link)):
            await send_error(
                update,
                f"[This content]({link.link}) can't be found or "
                "downloaded\\. If this seems to be wrong, try again later\\.",
            )
            llog.error("Post: Couldn't get content.")
            continue
        art = art._asdict()
        notify(update, art=art)
        llog.debug(
            "Post: content fetched.",
            images=len(art["links"]),
            art_link=art.get("link"),
        )
        match link.type:
            # twitter links
            case LinkType.TWITTER:
                result = await just_posting_twitter(update, context, data, art, link)
            # pixiv links
            case LinkType.PIXIV:
                result = await just_posting_pixiv(update, context, data, art, link)
            case _:
                llog.error("Post: unsupported link type, skipped.")
                continue
        llog.info(
            "Post: link processed.",
            result=_state_name(result),
            elapsed=round(time.perf_counter() - started, 3),
        )
        # upload to cloud
        if result == PostingResult.STATE_POSTED:
            llog.debug("Post: uploading media to cloud.")
            await upload_media(art, update.effective_chat.id)
            llog.debug("Post: media uploaded to cloud.")
