from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from abandon.main import AgentAPIError, request_agent_reply


def run(coroutine):
    return asyncio.run(coroutine)


def test_cli_sends_turn_to_agent_api():
    forwarded = []

    def handler(request):
        forwarded.append(json.loads(request.content))
        return httpx.Response(200, json={"reply": "agent reply"})

    async def scenario():
        async with httpx.AsyncClient(
            base_url="http://agent.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await request_agent_reply(
                client,
                message="hello",
                thread_id="cli:test",
            )

    assert run(scenario()) == "agent reply"
    assert forwarded == [{"message": "hello", "thread_id": "cli:test"}]


def test_cli_rejects_failed_or_invalid_agent_responses():
    async def scenario(response):
        async with httpx.AsyncClient(
            base_url="http://agent.test",
            transport=httpx.MockTransport(lambda request: response),
        ) as client:
            return await request_agent_reply(
                client,
                message="hello",
                thread_id="cli:test",
            )

    with pytest.raises(AgentAPIError, match="HTTP 502"):
        run(scenario(httpx.Response(502)))

    with pytest.raises(AgentAPIError, match="无效响应"):
        run(scenario(httpx.Response(200, content=b"not json")))

    with pytest.raises(AgentAPIError, match="没有返回"):
        run(scenario(httpx.Response(200, json={"reply": ""})))
