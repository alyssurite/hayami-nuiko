"""Web Application"""
import logging
import os

# parse json
import orjson

# web application
from fastapi import FastAPI, HTTPException, Request

# send json response
from fastapi.responses import JSONResponse

# telegram core bot api
from telegram import Update

# get user by token
from ..db.getters import get_user_by_token

# the bot
from .bot import bot_application

# get logger
log = logging.getLogger(__name__)

api_application = FastAPI()

ok_response = {
    "status": "ok",
    "info": "I'm fine.",
}

telegram_response = {
    "status": "ok",
    "info": "Added the update to the queue.",
}


@api_application.get("/health_check")
async def health():
    return JSONResponse(ok_response)


@api_application.post(f'/{os.environ["TOKEN"]}')
async def telegram(request: Request):
    await bot_application.update_queue.put(
        Update.de_json(
            data=await request.json(),
            bot=bot_application.bot,
        )
    )
    return JSONResponse(telegram_response)


@api_application.post("/post")
async def telegram_api_posting(request: Request):
    try:
        body = await request.body()
        data = orjson.loads(body)
        if not isinstance(data, dict):
            raise TypeError
    except orjson.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Couldn't parse json.") from None
    except TypeError:
        raise HTTPException(status_code=400, detail="Bad data.") from None
    if "token" not in data:
        raise HTTPException(status_code=400, detail="No token provided.")
    if "link" not in data:
        raise HTTPException(status_code=422, detail="No link provided.")
    if not (user := await get_user_by_token(data["token"])):
        raise HTTPException(status_code=404, detail="No such user.")
    return JSONResponse({"success": {"user": user.id}})
