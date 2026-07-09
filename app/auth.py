"""Authentication: bcrypt password hashing + JWT session tokens (D6).

Login happens outside the chat, so credentials never reach the LLM. The JWT
carries the username (`sub`) and a random session id (`jti`); the `jti`
doubles as the conversation thread_id, so every login starts a fresh
conversation (D11/D12).
"""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "jti": uuid.uuid4().hex,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Return the token payload, or None if the token is invalid or expired."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
