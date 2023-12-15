"""Getters module"""
import logging

from typing import Optional

# async caching
from aiocache import cached

# working with database
from sqlalchemy import select

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


@cached(ttl=None, key_builder=lambda fn, *a, **kw: a[0])
async def get_user(user_id: int) -> bool:
    """Checks if user in database.

    Args:
        user_id (int): user id.

    Returns:
        bool: user is already in database.
    """
    with Session() as session:
        return bool(session.get(User, user_id))


@cached(ttl=None, key_builder=lambda fn, *a, **kw: a[0])
async def get_token(user_id: int) -> Optional[str]:
    """Gets user's token from database.

    Args:
        user_id (int): user id.

    Returns:
        Optional[str]: user's token if exists.
    """
    with Session() as session:
        return session.get(User, user_id).token


@cached(ttl=None, key_builder=lambda fn, *a, **kw: a[0])
async def get_user_by_token(token: str) -> Optional[User]:
    """Checks if user's token in database.

    Args:
        token (str): user token.

    Returns:
        Optional[User]: holder of token, if exists.
    """
    with Session() as session:
        session.expire_on_commit = False
        return session.scalars(select(User).filter_by(token=token)).first()


@cached(ttl=None, key_builder=lambda fn, *a, **kw: a[0])
async def get_channel(channel_id: int) -> bool:
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
