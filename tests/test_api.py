"""API-level tests: auth flow and endpoint contracts. The agent is mocked —
no LLM calls — so these verify the HTTP wiring, not the model behaviour."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import app.main as main
from app.booking.db import make_engine
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


class TestStatic:
    def test_index_served(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "RoomBooking" in res.text

    def test_health(self, client):
        assert client.get("/health").json() == {"status": "ok"}
