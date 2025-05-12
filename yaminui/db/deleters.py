"""Database deleters"""

import logging

from sqlalchemy import select

# database session
from . import Session

# database models
from .models import Post

# get logger
log = logging.getLogger(__name__)


async def delete_post_by_id(record_id: int):
    with Session.begin() as session:
        if not (post := session.get(Post, record_id)):
            log.error("Post #%d does not exist!", record_id)
            return False
        log.info("Deleting post #%d [%d|%d]...", record_id, post.channel_id, post.post_id)
        session.delete(post)
        log.info("Deleted post #%d.", record_id)
        return True


async def delete_post_by_uix_post(
    channel_id: int,
    channel_post_id: int,
):
    with Session.begin() as session:
        posts = session.scalars(
            select(Post).where(
                Post.post_id == channel_post_id,
                Post.channel_id == channel_id,
            )
        ).all()
        if len(posts) == 0:
            log.warning("No posts!")
            return
        if len(posts) > 1:
            log.critical("Impossible! More than one post found!")
            return
        return await delete_post_by_id(posts[0].id)
