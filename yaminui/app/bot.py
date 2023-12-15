import logging
import os

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

# bot states and everything else
from ..bot import READ_TIMEOUT, WRITE_TIMEOUT, BotState, on_bot_init, on_bot_stop

# bot query
from ..bot.answer_query import answer_query

# bot commands
from ..bot.commands import (
    command_cancel,
    command_channel,
    command_forward,
    command_generate_token,
    command_help,
    command_media,
    command_pixiv_style,
    command_reply,
    command_show_token,
    command_start,
    command_twitter_style,
)

# bot filters
from ..bot.filters import filter_out

# bot functions
from ..bot.functions import handle_post, universal

# bot helpers
from ..bot.helpers import channel_check

# get logger
log = logging.getLogger(__name__)


def create_bot_app() -> None:
    """Set up and run the bot"""
    # create application
    application = (
        ApplicationBuilder()
        .token(os.environ["TOKEN"])
        .read_timeout(READ_TIMEOUT)
        .write_timeout(WRITE_TIMEOUT)
        .post_init(on_bot_init)
        .post_stop(on_bot_stop)
        .build()
    )

    # filter out unwanted users & channels
    application.add_handler(
        TypeHandler(
            Update,
            callback=filter_out,
        ),
        group=-1,
    )

    # start the bot
    application.add_handler(
        CommandHandler(
            command="start",
            callback=command_start,
            block=False,
        )
    )

    # get help
    application.add_handler(
        CommandHandler(
            command="help",
            callback=command_help,
            block=False,
        )
    )

    # toggle forwarding mode
    application.add_handler(
        CommandHandler(
            command="forward",
            callback=command_forward,
        )
    )

    # toggle replying mode
    application.add_handler(
        CommandHandler(
            command="reply",
            callback=command_reply,
        )
    )

    # toggle media media
    application.add_handler(
        CommandHandler(
            command="media",
            callback=command_media,
        )
    )

    # cycle through pixiv styles
    application.add_handler(
        CommandHandler(
            command="pixiv_style",
            callback=command_pixiv_style,
        )
    )

    # cycle through twitter styles
    application.add_handler(
        CommandHandler(
            command="twitter_style",
            callback=command_twitter_style,
        )
    )

    # generate new token
    application.add_handler(
        CommandHandler(
            command="generate_token",
            callback=command_generate_token,
        )
    )

    # show old token
    application.add_handler(
        CommandHandler(
            command="show_token",
            callback=command_show_token,
        )
    )

    # check sent channel
    channel_handler = CommandHandler(
        command="channel",
        callback=command_channel,
    )

    # cancel current action
    cancel_handler = CommandHandler(
        command="cancel",
        callback=command_cancel,
    )

    # add your channel
    application.add_handler(
        ConversationHandler(
            entry_points=[
                channel_handler,
                cancel_handler,
            ],
            states={
                BotState.CHANNEL: [
                    MessageHandler(
                        filters=filters.ChatType.PRIVATE & ~filters.COMMAND,
                        callback=channel_check,
                    ),
                ]
            },
            fallbacks=[
                channel_handler,
                cancel_handler,
            ],
        )
    )

    # handle text messages
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE
            & ~filters.COMMAND
            & ~filters.UpdateType.EDITED,
            callback=universal,
            block=False,
        )
    )

    # handle channels posts
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.CHANNEL
            & ~filters.COMMAND
            & ~filters.UpdateType.EDITED,
            callback=handle_post,
            block=False,
        )
    )

    # handle force posting
    application.add_handler(
        CallbackQueryHandler(
            callback=answer_query,
            block=False,
        )
    )

    return application


bot_application = create_bot_app()
