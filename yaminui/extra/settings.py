"""Settings module"""

import os
import uuid

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import AnyUrl, BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# current timestamp & app directory
DATE_RUN = datetime.now()
WORK_DIR = Path(os.getcwd())
UUID_RUN = uuid.uuid4().hex[:6].upper()


class BotSettings(BaseSettings):
    ##### main #####

    # telegram tokens
    api_id: int = Field(0)
    api_hash: str = Field("")
    token: str = Field("")

    local_server: str = Field("")

    # database URL
    database_url: str = Field("sqlite:///./db.sqlite3")

    ##### api #####

    # twitter [auth_token] (needed for gallery-dl's twitter API)
    tw_token: Optional[str] = Field("")

    # twitter [ct0] (needed for gallery-dl's twitter API)
    tw_cookie: Optional[str] = Field("")

    # twitter [username] (needed for gallery-dl's twitter API)
    tw_user: Optional[str] = Field("")

    # twitter [password] (needed for gallery-dl's twitter API)
    tw_pass: Optional[str] = Field("")

    # pixiv access token (needed for pixiv API)
    px_access: Optional[str] = Field("")

    # pixiv refresh token (needed for pixiv API)
    px_refresh: Optional[str] = Field("")

    # special user
    user_id: int = Field(0)

    ##### secret api #####

    # api url
    secret_api_url: str = Field("")

    # api key
    secret_api_key: str = Field("0" * 32, min_length=32)

    ##### webhook #####

    # host name
    hook_url: Optional[str] = Field("")

    # port
    port: int = Field(8443)

    ##### bot files #####

    # cache directory
    cache_dir: Path = Field(WORK_DIR / "cache")

    # help file
    help_file: Path = Field(WORK_DIR / "help.txt")

    # settings file
    log_settings_file: Path = Field(WORK_DIR / "settings.toml")

    ##### optional #####

    # local debug mode
    local_mode: bool = Field(False)

    # image resizer API to send requests to, if memory is limited
    resizer_api: Optional[str] = Field("")

    # logtail token
    logtail_token: Optional[str] = Field("")

    # google cloud logging
    gd_log: Optional[str] = Field("")

    # google cloud media
    gd_media: Optional[str] = Field("")

    # health check URL
    health_check_url: Optional[AnyUrl] = Field(None)

    @field_validator("health_check_url", mode="before")
    @classmethod
    def allow_empty_string_as_none(cls, value):
        if value == "":
            return None
        return value

    # special alert case
    alert_id: int = Field(0)


bot_settings = BotSettings()


class FileLog(BaseModel):
    enable: bool = Field(False)
    level: str = Field("DEBUG")
    form: str = Field("%(asctime)s [%(levelname)s] > %(name)s: %(message)s")
    date: str = Field("%Y-%m-%d.%H-%M-%S")
    path: Path = Field(WORK_DIR / "log")
    pref: str = Field("")


class BasicLog(BaseModel):
    enable: bool = Field(False)
    level: str = Field("DEBUG")
    form: str = Field("%(asctime)s [%(levelname)s] > %(name)s: %(message)s")


class ExcludeLog(BasicLog):
    name: str
    enable: bool = Field(False)
    level: str = Field("WARNING")


class LogSettings(BaseSettings):
    file: FileLog
    root: BasicLog
    bot: BasicLog
    tail: BasicLog

    lib: list[ExcludeLog]

    model_config: SettingsConfigDict = SettingsConfigDict(
        toml_file=bot_settings.log_settings_file
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        **kwargs,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (TomlConfigSettingsSource(settings_cls),)


log_settings = LogSettings()
