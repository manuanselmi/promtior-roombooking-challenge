"""API-level tests: auth flow and endpoint contracts. The agent is mocked —
no LLM calls — so these verify the HTTP wiring, not the model behaviour."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.booking import service
from app.booking.db import make_engine
from app.booking.models import User
from app.config import settings

CREDS = {"username": "User1", "password": "TechnicalChallengePromtior"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "engine", make_engine(f"sqlite:///{tmp_path}/api.db"))
    monkeypatch.setattr(settings, "openai_api_key", "test-key")  # the agent is mocked anyway
    with TestClient(main.app) as client:
        yield client


@pytest.fixture()
def fake_agent(monkeypatch):
    """Replace build_agent with a stub; captures who the agent was built for."""
    captured = {}

    class FakeAgent:
        def invoke(self, payload, config=None):
            captured["message"] = payload["messages"][0].content
            captured["thread_id"] = config["configurable"]["thread_id"]
            return {"messages": [AIMessage("fake reply")]}

    def fake_build(session_factory, user, now=None):
        captured["username"] = user.username
        return FakeAgent()

    monkeypatch.setattr(main, "build_agent", fake_build)
    return captured


def login(client) -> str:
    return client.post("/login", json=CREDS).json()["token"]


class TestLogin:
    def test_valid_credentials_return_token(self, client):
        res = client.post("/login", json=CREDS)
        assert res.status_code == 200
        assert res.json()["username"] == "User1"
        assert res.json()["token"]

    def test_wrong_password_rejected(self, client):
        res = client.post("/login", json={**CREDS, "password": "nope"})
        assert res.status_code == 401

    def test_unknown_user_rejected(self, client):
        res = client.post("/login", json={**CREDS, "username": "Mallory"})
        assert res.status_code == 401


class TestChat:
    def test_requires_token(self, client):
        assert client.post("/chat", json={"message": "hi"}).status_code == 401

    def test_rejects_garbage_token(self, client):
        res = client.post(
            "/chat", json={"message": "hi"}, headers={"Authorization": "Bearer garbage"}
        )
        assert res.status_code == 401

    def test_round_trip_binds_agent_to_logged_in_user(self, client, fake_agent):
        token = login(client)
        res = client.post(
            "/chat", json={"message": "hello"}, headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        assert res.json() == {"reply": "fake reply"}
        assert fake_agent["username"] == "User1"
        assert fake_agent["message"] == "hello"

    def test_missing_api_key_yields_clear_503(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        token = login(client)
        res = client.post(
            "/chat", json={"message": "hi"}, headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 503
        assert "OPENAI_API_KEY" in res.json()["detail"]

    def test_each_login_gets_its_own_thread(self, client, fake_agent):
        headers1 = {"Authorization": f"Bearer {login(client)}"}
        client.post("/chat", json={"message": "a"}, headers=headers1)
        thread1 = fake_agent["thread_id"]
        headers2 = {"Authorization": f"Bearer {login(client)}"}
        client.post("/chat", json={"message": "b"}, headers=headers2)
        assert fake_agent["thread_id"] != thread1


def seed_booking(username="User1", *, room="B", day=15, start_h=10, end_h=11, title="Team sync"):
    """Create a booking directly through the service, on the app's live engine."""
    with Session(main.engine) as s:
        user = s.scalar(select(User).where(User.username == username))
        b = service.create_booking(
            s,
            user=user,
            room_id=room,
            start=datetime(2030, 6, day, start_h),
            end=datetime(2030, 6, day, end_h),
            title=title,
            attendees=2,
        )
        return b.id


class TestBackoffice:
    """Public (no-auth) operator endpoints powering the calendar view."""

    def test_rooms_lists_a_to_e(self, client):
        res = client.get("/backoffice/api/rooms")
        assert res.status_code == 200
        assert [r["id"] for r in res.json()] == ["A", "B", "C", "D", "E"]

    def test_needs_no_auth(self, client):
        # No Authorization header at all — the backoffice is a public link (D16).
        assert client.get("/backoffice/api/rooms").status_code == 200

    def test_bookings_empty_range(self, client):
        res = client.get(
            "/backoffice/api/bookings",
            params={"start": "2030-06-15T00:00:00", "end": "2030-06-16T00:00:00"},
        )
        assert res.status_code == 200
        assert res.json() == []

    def test_bookings_returns_seeded_with_organizer(self, client):
        seed_booking(title="Design review")
        res = client.get(
            "/backoffice/api/bookings",
            params={"start": "2030-06-15T00:00:00", "end": "2030-06-16T00:00:00"},
        )
        assert res.status_code == 200
        [b] = res.json()
        assert b["room_id"] == "B"
        assert b["title"] == "Design review"
        assert b["user"] == "User1"
        assert b["attendees"] == 2

    def test_bookings_outside_range_excluded(self, client):
        seed_booking(day=20)
        res = client.get(
            "/backoffice/api/bookings",
            params={"start": "2030-06-15T00:00:00", "end": "2030-06-16T00:00:00"},
        )
        assert res.json() == []

    def test_bookings_accepts_tz_aware_input(self, client):
        # The frontend sends naive local time, but an offset must not 500 (D10/D16).
        seed_booking()
        res = client.get(
            "/backoffice/api/bookings",
            params={"start": "2030-06-15T00:00:00-03:00", "end": "2030-06-16T00:00:00-03:00"},
        )
        assert res.status_code == 200
        assert len(res.json()) == 1

    def test_bookings_requires_range(self, client):
        assert client.get("/backoffice/api/bookings").status_code == 422

    def test_cancel_removes_any_booking(self, client):
        booking_id = seed_booking()
        assert client.delete(f"/backoffice/api/bookings/{booking_id}").status_code == 204
        res = client.get(
            "/backoffice/api/bookings",
            params={"start": "2030-06-15T00:00:00", "end": "2030-06-16T00:00:00"},
        )
        assert res.json() == []

    def test_cancel_unknown_is_404(self, client):
        assert client.delete("/backoffice/api/bookings/999").status_code == 404

    def test_page_served(self, client):
        res = client.get("/backoffice")
        assert res.status_code == 200
        assert "Backoffice" in res.text


class TestStatic:
    def test_index_served(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "RoomBooking" in res.text

    def test_health(self, client):
        assert client.get("/health").json() == {"status": "ok"}
