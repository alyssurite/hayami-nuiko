"""Loggers module"""
import logging

from typing import Any

# telegram core bot api
from telegram import Update

# get logger
log = logging.getLogger(__name__)


def notify(
    update: Update,
    *,
    command: str = None,
    function: str = None,
    art: dict[str, Any] = None,
    toggle: tuple[str, bool] = None,
    group_sender: dict[str, Any] = None,
) -> None:
    """Log that something hapened

    Args:
        update (Update): current update
        command (str, optional): called command. Defaults to None.
        function (str, optional): called function. Defaults to None.
        art (ArtWorkMedia, optional): art object. Defaults to None.
        toggle (tuple[str, bool]m optional): toggler info. Defaults to None.
    """
    chat = update.effective_chat
    if command:
        log.info(
            "<%d> %r called command: %r.",
            chat.id,
            chat.full_name or chat.title,
            command,
        )
    if function:
        log.info(
            "<%d> %r called function: %r.",
            chat.id,
            chat.full_name or chat.title,
            function,
        )
    if art:
        log.info(
            "<%d> %r received content: [%02d|%d/%s] %r : %r by [%d/@%s] %r | %s.",
            chat.id,
            chat.full_name or chat.title,
            art["type"],
            art["id"],
            art["media"],
            art["title"] if art["title"] else "×",
            art["desc"],
            art["user_id"],
            art["username"],
            art["user"],
            art["date"],
        )
    if toggle:
        log.info(
            "<%d> %r called toggler: %r is now %s.",
            chat.id,
            chat.full_name or chat.title,
            toggle[0],
            "enabled" if toggle[1] else "disabled",
        )
    if group_sender:
        log.info(
            "<%d> %r forwards %r to channel <%d>.",
            chat.id,
            chat.full_name or chat.title,
            group_sender["link"],
            group_sender["channel_id"],
        )
