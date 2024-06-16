import os

# working with env
from dotenv import load_dotenv

# create engine
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# load .env file
load_dotenv()

# database connection string
DB_URI = os.environ["DATABASE_URL"]

# engine settings
ENGINE = create_engine(DB_URI, pool_pre_ping=True)

# session factory
Session = sessionmaker(ENGINE, expire_on_commit=False)


# base class for declarative class definitions
class Base(DeclarativeBase):
    pass
