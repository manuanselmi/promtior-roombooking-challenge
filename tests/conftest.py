import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.booking.db import init_db, make_engine
from app.booking.models import User


@pytest.fixture()
def engine(tmp_path):
    # A temp file (not in-memory) so every session — including the per-tool-call
    # sessions build_tools opens — sees the same database, as in production.
    engine = make_engine(f"sqlite:///{tmp_path}/test.db")
    init_db(engine, users={"User1": "irrelevant-hash", "User2": "irrelevant-hash"})
    return engine


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def user1(session) -> User:
    return session.query(User).filter_by(username="User1").one()


@pytest.fixture()
def user2(session) -> User:
    return session.query(User).filter_by(username="User2").one()
