from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from webui.backend import create_app


SESSION_ID = f"web:{'a' * 32}"
OTHER_SESSION_ID = f"web:{'b' * 32}"
SESSION = {
    "id": SESSION_ID,
    "title": "New conversation",
    "created_at": "2026-08-02T00:00:00Z",
    "updated_at": "2026-08-02T00:00:00Z",
}


def make_agent_client(handler):
    return httpx.AsyncClient(
        base_url="http://agent.test",
        transport=httpx.MockTransport(handler),
    )


def test_health_is_pure_and_chat_uses_the_explicit_session_id():
    forwarded = []

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "service": "frontier-agent"},
            )
        if request.url.path == "/v1/chat":
            payload = json.loads(request.content)
            forwarded.append(payload)
            return httpx.Response(
                200,
                json={"reply": "proxied reply", "thread_id": SESSION_ID},
            )
        return httpx.Response(404)

    app = create_app(agent_client=make_agent_client(handler))
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert "set-cookie" not in health.headers

        missing_session = client.post("/api/chat", json={"message": "hello"})
        assert missing_session.status_code == 422

        chat = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": SESSION_ID},
        )
        assert chat.status_code == 200
        assert chat.json() == {"reply": "proxied reply"}
        assert "set-cookie" not in chat.headers

    assert forwarded == [
        {"message": "hello", "thread_id": SESSION_ID},
    ]


def test_backend_preserves_message_whitespace_and_rejects_extra_input():
    forwarded = []

    def handler(request):
        payload = json.loads(request.content)
        forwarded.append(payload)
        return httpx.Response(
            200,
            json={"reply": "ok", "thread_id": SESSION_ID},
        )

    app = create_app(agent_client=make_agent_client(handler))
    with TestClient(app) as client:
        message = "  code\n    indented"
        response = client.post(
            "/api/chat",
            json={"message": message, "session_id": SESSION_ID},
        )
        assert response.status_code == 200
        assert forwarded[0]["message"] == message

        extra = client.post(
            "/api/chat",
            json={
                "message": "hello",
                "session_id": SESSION_ID,
                "unexpected": True,
            },
        )
        assert extra.status_code == 422


def test_session_collection_and_history_are_strictly_proxied():
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path, request.content))
        if request.method == "POST" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json=SESSION)
        if request.method == "GET" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"sessions": [SESSION]})
        if request.url.path == f"/v1/sessions/{SESSION_ID}/messages":
            return httpx.Response(
                200,
                json={
                    "thread_id": SESSION_ID,
                    "messages": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi"},
                    ],
                },
            )
        return httpx.Response(404)

    app = create_app(agent_client=make_agent_client(handler))
    with TestClient(app) as client:
        created = client.post("/api/sessions")
        assert created.status_code == 200
        assert created.json() == SESSION

        listed = client.get("/api/sessions")
        assert listed.status_code == 200
        assert listed.json() == {"sessions": [SESSION]}

        history = client.get(f"/api/sessions/{SESSION_ID}/messages")
        assert history.status_code == 200
        assert history.json() == {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        }

        invalid = client.get("/api/sessions/not-a-web-session/messages")
        assert invalid.status_code == 422

    assert requests == [
        ("POST", "/v1/sessions", b""),
        ("GET", "/v1/sessions", b""),
        ("GET", f"/v1/sessions/{SESSION_ID}/messages", b""),
    ]


def test_backend_rejects_mismatched_or_malformed_agent_payloads():
    def mismatched_chat(request):
        return httpx.Response(
            200,
            json={"reply": "wrong thread", "thread_id": OTHER_SESSION_ID},
        )

    app = create_app(agent_client=make_agent_client(mismatched_chat))
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": SESSION_ID},
        )
        assert response.status_code == 502
        assert response.json() == {"detail": "invalid_agent_response"}

    def invalid_session_list(request):
        return httpx.Response(
            200,
            json={"sessions": [{**SESSION, "id": "cli:not-web"}]},
        )

    app = create_app(agent_client=make_agent_client(invalid_session_list))
    with TestClient(app) as client:
        response = client.get("/api/sessions")
        assert response.status_code == 502
        assert response.json() == {"detail": "invalid_agent_response"}

    def invalid_history(request):
        return httpx.Response(
            200,
            json={
                "thread_id": SESSION_ID,
                "messages": [{"role": "tool", "content": "private"}],
            },
        )

    app = create_app(agent_client=make_agent_client(invalid_history))
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{SESSION_ID}/messages")
        assert response.status_code == 502
        assert response.json() == {"detail": "invalid_agent_response"}


def test_backend_maps_agent_transport_failures():
    def connect_failure(request):
        raise httpx.ConnectError("offline", request=request)

    app = create_app(agent_client=make_agent_client(connect_failure))
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": SESSION_ID},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "agent_service_unavailable"}

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    app = create_app(agent_client=make_agent_client(timeout))
    with TestClient(app) as client:
        response = client.get("/api/sessions")
        assert response.status_code == 504
        assert response.json() == {"detail": "agent_service_timed_out"}


def test_backend_sanitizes_upstream_failures_and_preserves_session_404():
    def upstream_failure(request):
        return httpx.Response(500, json={"detail": "private upstream error"})

    app = create_app(agent_client=make_agent_client(upstream_failure))
    with TestClient(app) as client:
        response = client.get("/api/sessions")
        assert response.status_code == 502
        assert response.json() == {"detail": "agent_service_failed"}
        assert "private upstream error" not in response.text

    def missing_session(request):
        return httpx.Response(404, json={"detail": "private identifier"})

    app = create_app(agent_client=make_agent_client(missing_session))
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{SESSION_ID}/messages")
        assert response.status_code == 404
        assert response.json() == {"detail": "session_not_found"}
        assert "private identifier" not in response.text


def test_backend_rejects_invalid_health_and_extra_upstream_fields():
    def invalid_health(request):
        return httpx.Response(200, content=b"not json")

    app = create_app(agent_client=make_agent_client(invalid_health))
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 502
        assert response.json() == {"detail": "invalid_agent_response"}

    def extra_field(request):
        return httpx.Response(200, json={**SESSION, "private": "value"})

    app = create_app(agent_client=make_agent_client(extra_field))
    with TestClient(app) as client:
        response = client.post("/api/sessions")
        assert response.status_code == 502
        assert response.json() == {"detail": "invalid_agent_response"}


def test_backend_serves_react_build_and_keeps_unknown_api_as_json_404(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><body>Frontier build</body></html>",
        encoding="utf-8",
    )
    app = create_app(
        agent_client=make_agent_client(lambda request: httpx.Response(200)),
        build_dir=tmp_path,
    )

    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "Frontier build" in root.text

        route = client.get("/conversation/example")
        assert route.status_code == 200
        assert "Frontier build" in route.text

        missing_api = client.get("/api/does-not-exist")
        assert missing_api.status_code == 404
        assert missing_api.headers["content-type"].startswith("application/json")
