"""Engine creation and idempotent seeding of rooms and users."""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from .models import Base, Room, User

# The challenge defines rooms A–E with a per-room maximum capacity but leaves the
# values open; these defaults are documented in doc/DECISIONS.md (D10).
ROOM_CAPACITIES = {"A": 2, "B": 4, "C": 6, "D": 8, "E": 10}


def make_engine(url: str = "sqlite:///data/roombooking.db") -> Engine:
    if url.startswith("sqlite:///"):
        db_path = url.removeprefix("sqlite:///")
        if db_path:  # not in-memory
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args={"check_same_thread": False})


def init_db(engine: Engine, users: dict[str, str] | None = None) -> None:
    """Create tables and seed rooms plus the given {username: password_hash} users."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for room_id, capacity in ROOM_CAPACITIES.items():
            if session.get(Room, room_id) is None:
                session.add(Room(id=room_id, capacity=capacity))
        for username, password_hash in (users or {}).items():
            existing = session.query(User).filter_by(username=username).one_or_none()
            if existing is None:
                session.add(User(username=username, password_hash=password_hash))
        session.commit()
