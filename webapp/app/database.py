from typing import Annotated

from fastapi import Depends
from sqlmodel import create_engine, SQLModel, Session

from webapp.app.config import settings

connect_args = {"check_same_thread": False}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

def get_session_enginge() -> Session:
    return Session(engine)

SessionDep = Annotated[Session, Depends(get_session)]