import os

# working with env
from dotenv import load_dotenv

# create engine
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# env variables
from yaminui.extra.settings import bot_settings

# load .env file
load_dotenv()

# database connection string
DB_URI = bot_settings.database_url

# engine settings
ENGINE = create_engine(DB_URI, pool_pre_ping=True)

# session factory
Session = sessionmaker(ENGINE, expire_on_commit=False)


# base class for declarative class definitions
class Base(DeclarativeBase):
    pass
