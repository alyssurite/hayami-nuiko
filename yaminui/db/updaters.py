"""Updaters module"""

import logging

# telegram core bot api
from telegram import Chat

# pixiv & twiter styles
from yaminui.api import BaseStyle

# database session
from yaminui.db import Session

# database models
from yaminui.db.models import Channel, User

# get logger
log = logging.getLogger(__name__)


async def update_chat(chat: Chat) -> None:
    """Updates chat info.

    Args:
        chat (Chat): telegram chat.
    """
    with Session.begin() as session:
        if chat.type == Chat.CHANNEL:
            if not (channel := session.get(Channel, chat.id)):
                session.add(
                    channel := Channel(
                        id=chat.id,
                        name=chat.title,
                        link=chat.username,
                        is_admin=True,
                        is_deleted=False,
                    ),
                )
            else:
                channel.name, channel.link = chat.title, chat.username
        if chat.type == Chat.PRIVATE:
            if not (user := session.get(User, chat.id)):
                session.add(
                    user := User(
                        id=chat.id,
                        full_name=chat.full_name,
                        nick_name=chat.username,
                    ),
                )
            else:
                user.full_name, user.nick_name = chat.full_name, chat.username


async def toggle_field(user_id: int, field: str) -> bool:
    """Toggles field between True and False.

    Args:
        user_id (int): telegram user id.
        field (str): field name to toggle.

    Returns:
        bool: new field state.
    """
    with Session.begin() as session:
        user = session.get(User, user_id)
        state = not getattr(user, field)
        setattr(user, field, state)
        return state


async def switch_style(user_id: int, style: BaseStyle, value: int) -> int:
    """Switches style value to new style value.

    Args:
        user_id (int): telegram user id.
        style (BaseStyle): style class.
        value (int): new style value.

    Returns:
        int: normalized new style value.
    """
    with Session.begin() as session:
        user = session.get(User, user_id)
        new_style = style.get_style(value)
        setattr(user, style.field, new_style)
        return new_style


async def cycle_style(user_id: int, style: BaseStyle) -> int:
    """Cycles style value.

    Args:
        user_id (int): telegram user id.
        style (BaseStyle): style class.

    Returns:
        int: new style value.
    """
    with Session.begin() as session:
        user = session.get(User, user_id)
        new_style = style.get_next_style(getattr(user, style.field))
        setattr(user, style.field, new_style)
        return new_style
