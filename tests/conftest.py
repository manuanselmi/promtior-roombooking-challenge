import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.booking.db import init_db
from app.booking.models import User


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")  # in-memory
    init_db(engine, users={"User1": "irrelevant-hash", "User2": "irrelevant-hash"})
    with Session(engine) as s:
        yield s


@pytest.fixture()
def user1(session) -> User:
    return session.query(User).filter_by(username="User1").one()


@pytest.fixture()
def user2(session) -> User:
    return session.query(User).filter_by(username="User2").one()
