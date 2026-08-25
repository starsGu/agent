from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent.api import create_app


class FakeCustomAgent:
    def __init__(
        self,
        *,
        reply="agent reply",
        failure=None,
        delay=0.0,
        history=None,
    ):
        self.agent = object()
        self.reply = reply
        self.failure = failure
        self.delay = delay
        self.calls = []
        self.history_calls = []
        self.history = history or []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.closed = True

    async def ainvoke(self, message, thread_id):
        self.calls.append((message, thread_id))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure
        if self.reply is None:
            return {"messages": []}
        return {
            "messages": [
                SimpleNamespace(type="human", content=message),
                SimpleNamespace(type="ai", content=self.reply),
            ],
        }

    async def aget_state(self, thread_id):
        self.history_calls.append(thread_id)
        return SimpleNamespace(values={"messages": self.history})


def test_health_and_chat_reuse_the_requested_thread():
    fake = FakeCustomAgent()
    app = create_app(agent_factory=lambda: fake)

    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "service": "frontier-agent",
        }

        first = client.post("/v1/chat", json={"message": "hello"})
        assert first.status_code == 200
        thread_id = first.json()["thread_id"]
        assert len(thread_id) == 32

        second = client.post(
            "/v1/chat",
            json={"message": "next", "thread_id": thread_id},
        )
        assert second.status_code == 200
        assert second.json() == {"reply": "agent reply", "thread_id": thread_id}

    assert fake.calls == [("hello", thread_id), ("next", thread_id)]
    assert fake.closed is True


def test_message_whitespace_is_preserved_but_blank_input_is_rejected():
    fake = FakeCustomAgent()
    app = create_app(agent_factory=lambda: fake)

    with TestClient(app) as client:
        message = "  code\n    indented"
        response = client.post(
            "/v1/chat",
            json={"message": message, "thread_id": "test:spacing"},
        )
        assert response.status_code == 200
        assert fake.calls[0][0] == message

        blank = client.post("/v1/chat", json={"message": "   "})
        assert blank.status_code == 422


def test_content_blocks_are_combined_into_reply_text():
    fake = FakeCustomAgent(
        reply=[
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ],
    )
    app = create_app(agent_factory=lambda: fake)

    with TestClient(app) as client:
        response = client.post("/v1/chat", json={"message": "hello"})
        assert response.status_code == 200
        assert response.json()["reply"] == "first\nsecond"


def test_agent_failure_and_missing_reply_are_sanitized():
    failing = FakeCustomAgent(failure=RuntimeError("secret provider detail"))
    app = create_app(agent_factory=lambda: failing)

    with TestClient(app) as client:
        response = client.post("/v1/chat", json={"message": "hello"})
        assert response.status_code == 502
        assert response.json() == {"detail": "agent_invocation_failed"}
        assert "secret provider detail" not in response.text

    empty = FakeCustomAgent(reply=None)
    app = create_app(agent_factory=lambda: empty)
    with TestClient(app) as client:
        response = client.post("/v1/chat", json={"message": "hello"})
        assert response.status_code == 502
        assert response.json() == {"detail": "agent_returned_no_reply"}


def test_agent_timeout_returns_gateway_timeout(monkeypatch):
    monkeypatch.setenv("AGENT_REQUEST_TIMEOUT", "0.01")
    slow = FakeCustomAgent(delay=0.1)
    app = create_app(agent_factory=lambda: slow)

    with TestClient(app) as client:
        response = client.post("/v1/chat", json={"message": "hello"})
        assert response.status_code == 504
        assert response.json() == {"detail": "agent_invocation_timed_out"}


def test_history_returns_only_user_visible_turns():
    fake = FakeCustomAgent(
        history=[
            SimpleNamespace(type="human", content="weather"),
            SimpleNamespace(type="ai", content="checking", tool_calls=[{}]),
            SimpleNamespace(type="tool", content="tool result"),
            SimpleNamespace(type="ai", content="sunny"),
            SimpleNamespace(type="human", content="thanks"),
            SimpleNamespace(type="ai", content="you are welcome"),
        ],
    )
    app = create_app(agent_factory=lambda: fake)

    with TestClient(app) as client:
        response = client.get("/v1/threads/web%3Atest/messages")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "web:test",
        "messages": [
            {"role": "user", "content": "weather"},
            {"role": "assistant", "content": "sunny"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "you are welcome"},
        ],
    }
    assert fake.history_calls == ["web:test"]
