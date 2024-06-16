"""Getters module"""
import logging

from typing import Optional

# async caching
from aiocache import cached

# working with database
from sqlalchemy import select

# loading strategies
from sqlalchemy.orm import joinedload

# telegram core bot api
from telegram import Update

# user data dataclass
from ..bot import UserData

# bot utils
from ..bot.utils import tg_post_link

# database session
from . import Session

# database models
from .models import ArtWork, Channel, Post, User

# get logger
log = logging.getLogger(__name__)


@cached(ttl=None, key_builder=lambda *args: args[1])
async def check_user(user_id: int) -> bool:
    """Checks if user in database.

    Args:
        user_id (int): user id.

    Returns:
        bool: user is already in database.
    """
    with Session() as session:
        return bool(session.get(User, user_id))


@cached(ttl=None, key_builder=lambda *args: args[1])
async def check_channel(channel_id: int) -> bool:
    """Checks if channel in database.

    Args:
        channel_id (int): channel id.

    Returns:
        bool: channel is already in database.
    """
    with Session() as session:
        return bool(session.get(Channel, channel_id))


async def get_artwork(art_id: int, art_type: int) -> Optional[ArtWork]:
    """Gets artwork if it is already in database.

    Args:
        art_id (int): artwork id.
        art_type (int): artwork type.

    Returns:
        Optional[ArtWork]: found artwork.
    """
    with Session() as session:
        return session.scalars(
            select(ArtWork).filter_by(
                aid=art_id,
                type=art_type,
            )
        ).first()


async def get_other_links(
    art_id: int,
    art_type: int,
    channel_id: int = None,
) -> list[str]:
    """Gets already posted instances of artwork.

    Args:
        art_id (int): artwork id.
        art_type (int): artwork type.
        channel_id (int, optional): channel id to search in. Defaults to None.

    Returns:
        list[str]: list of links to posts.
    """
    if channel_id:
        channel_filter = Post.channel_id == channel_id
    else:
        channel_filter = True
    with Session() as session:
        return [
            tg_post_link.format(**item)
            for item in (
                session.execute(
                    select(Post.post_id, Channel.cid)
                    .join(
                        Channel,
                        (Channel.id == Post.channel_id) & channel_filter,
                    )
                    .join(
                        ArtWork,
                        (ArtWork.id == Post.artwork_id)
                        & (ArtWork.aid == art_id)
                        & (ArtWork.type == art_type),
                    )
                    .order_by(Post.post_date.asc())
                ).mappings()
            )
        ]


async def get_user(user_id: int) -> Optional[User]:
    with Session() as session:
        return session.get(User, user_id)


async def get_user_data(update: Update) -> Optional[UserData]:
    """Get current user's current data.

    Args:
        update (Update): current update.

    Returns:
        Optional[UserData]: current user's current data.
    """
    with Session() as session:
        user = session.get(User, update.effective_user.id)
        if user.forward_mode and not user.channel:
            return
        return UserData(
            user.forward_mode,
            user.reply_mode,
            user.media_mode,
            user.pixiv_style,
            user.twitter_style,
            user.last_info,
            user.channel.id if user.channel else 0,
        )


async def get_user_channel(user_id: int) -> Optional[Channel]:
    with Session() as session:
        if not (user := session.get(User, user_id)):
            log.error("User #%d is not found.", user_id)
            return
        if not (channel := user.channel):
            log.info("User #%d has no channel attached!", user_id)
            return
        log.info("User #%d has attached channel #%d.", user_id, channel.id)
        return channel


async def get_channel_by_link(channel_link: str) -> Optional[Channel]:
    with Session.begin() as session:
        if channel_link.isnumeric():
            # it's an id: 1183548293
            # https://t.me/c/1183548293/60913
            query = select(Channel).where(Channel.cid == int(channel_link))
        else:
            # it's a name: denkou
            # https://t.me/denkou/60932
            query = select(Channel).where(Channel.link == channel_link)
        if not (channel := session.scalars(query).one_or_none()):
            log.error("Couldn't find channel!")
            return
        log.info(
            "Found channel: %s [%d]: %s.",
            channel.name,
            channel.id,
            channel.link or "no link",
        )
        return channel


async def get_post(record_id: int) -> Optional[Post]:
    with Session() as session:
        return session.get(Post, record_id)


async def get_post_by_uix_post(channel_id: int, channel_post_id: int) -> Optional[Post]:
    with Session.begin() as session:
        if not (channel := session.get(Channel, channel_id)):
            log.error("Couldn't get post from unknown channel!")
            return
        posts = session.scalars(
            select(Post)
            .where(
                Post.post_id == channel_post_id,
                Post.channel_id == channel.id,
            )
            .options(joinedload(Post.channel))
            .options(joinedload(Post.artwork))
        ).all()
        if len(posts) == 0:
            log.error("No posts!")
            return
        if len(posts) > 1:
            log.critical("Impossible! More than one post found!")
            return
        post = posts[0]
        log.info(
            "Found post: #%d [ %d | %d ] %s.",
            post.id,
            post.channel_id,
            post.post_id,
            post.post_date,
        )
        return post
