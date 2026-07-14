"""FastAPI app: login (JWT), chat endpoint and the static UI, in one process (D7).

The agent is rebuilt per request, bound to the authenticated user (D11).
Conversation memory is keyed by the JWT's session id (`jti`) used as the
LangGraph thread_id: a new login starts a fresh conversation (D12).
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.agent import build_agent
from app.auth import create_token, decode_token, hash_password, verify_password
from app.booking import service
from app.booking.db import init_db, make_engine
from app.booking.models import Booking, Room, User
from app.booking.service import BookingError
from app.config import settings

logger = logging.getLogger(__name__)

# Users mandated by the challenge statement.
SEED_USERS = ("User1", "User2")
SEED_PASSWORD = "TechnicalChallengePromtior"  # noqa: S105 — public demo credential

STATIC_DIR = Path(__file__).parent / "static"

engine = make_engine(settings.database_url)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set — /chat will return 503 until it is configured")
    init_db(engine, users={u: hash_password(SEED_PASSWORD) for u in SEED_USERS})
    yield


app = FastAPI(title="RoomBooking", lifespan=lifespan)

bearer = HTTPBearer(auto_error=False)


def get_session():
    with Session(engine) as session:
        yield session


def make_session() -> Session:
    """Session factory for the agent's tools: one fresh session per tool call,
    because parallel tool calls run on separate threads (D14). Resolves
    `engine` at call time so tests can swap it."""
    return Session(engine)


def get_current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> tuple[User, str]:
    """Resolve the Bearer token to (user, session_id), or fail with 401."""
    payload = decode_token(credentials.credentials) if credentials else None
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = session.scalar(select(User).where(User.username == payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user, payload["jti"]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.post("/login")
def login(body: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    user = session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return LoginResponse(token=create_token(user.username), username=user.username)


@app.post("/chat")
def chat(
    body: ChatRequest,
    auth: tuple[User, str] = Depends(get_current_auth),
) -> ChatResponse:
    user, session_id = auth
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503, detail="Server misconfigured: OPENAI_API_KEY is not set"
        )
    try:
        agent = build_agent(make_session, user)
        result = agent.invoke(
            {"messages": [HumanMessage(body.message)]},
            config={"configurable": {"thread_id": session_id}},
        )
    except Exception:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=502, detail="The assistant is temporarily unavailable")
    return ChatResponse(reply=_last_ai_text(result["messages"]))


def _last_ai_text(messages: list) -> str:
    content = messages[-1].content
    if isinstance(content, str):
        return content
    # Content blocks (rare with plain-text models): keep only the text parts.
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


# --- Backoffice: unauthenticated operator view over every booking (D16) --------
# Reached through a public link with no login by product decision: it exists to
# eyeball and correct the data (a room's week at a glance, cancel anything). It
# reuses the same service layer, so the booking rules stay in one place.


class RoomOut(BaseModel):
    id: str
    capacity: int


class BookingOut(BaseModel):
    id: int
    room_id: str
    title: str
    user: str
    attendees: int
    start: datetime
    end: datetime


def _booking_out(b: Booking) -> BookingOut:
    return BookingOut(
        id=b.id,
        room_id=b.room_id,
        title=b.title,
        user=b.user.username,
        attendees=b.attendees,
        start=b.start,
        end=b.end,
    )


def _naive(dt: datetime) -> datetime:
    """Drop any timezone offset: the app stores and compares naive local time (D10)."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


@app.get("/backoffice/api/rooms", response_model=list[RoomOut], include_in_schema=False)
def backoffice_rooms(session: Session = Depends(get_session)) -> list[Room]:
    return list(session.scalars(select(Room).order_by(Room.id)))


@app.get("/backoffice/api/bookings", response_model=list[BookingOut], include_in_schema=False)
def backoffice_bookings(
    start: datetime = Query(...),
    end: datetime = Query(...),
    session: Session = Depends(get_session),
) -> list[BookingOut]:
    """Every booking overlapping [start, end), across all users and rooms."""
    try:
        bookings = service.list_bookings_in_range(session, _naive(start), _naive(end))
    except BookingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_booking_out(b) for b in bookings]


@app.delete("/backoffice/api/bookings/{booking_id}", status_code=204, include_in_schema=False)
def backoffice_cancel(booking_id: int, session: Session = Depends(get_session)) -> None:
    try:
        service.admin_cancel_booking(session, booking_id=booking_id)
    except BookingError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/backoffice", include_in_schema=False)
def backoffice() -> FileResponse:
    return FileResponse(STATIC_DIR / "backoffice.html")


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
