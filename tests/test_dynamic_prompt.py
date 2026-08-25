from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import SystemMessage

from agent.prompt import (
    DEFAULT_SYSTEM_PROMPT,
    dynamic_system_prompt,
    system_prompt_store,
)
from cli import app


class FakeModelRequest:
    def __init__(self, system_message=None):
        self.system_message = system_message

    def override(self, **changes):
        return FakeModelRequest(
            system_message=changes.get("system_message", self.system_message),
        )


@pytest.fixture(autouse=True)
def reset_system_prompt():
    system_prompt_store.update(DEFAULT_SYSTEM_PROMPT)
    yield
    system_prompt_store.update(DEFAULT_SYSTEM_PROMPT)


def test_dynamic_prompt_uses_latest_template_on_every_model_call():
    async def scenario():
        request = FakeModelRequest()

        async def capture(current_request):
            return current_request

        system_prompt_store.update("第一个提示词")
        first_result = await dynamic_system_prompt.awrap_model_call(
            request,
            capture,
        )

        system_prompt_store.update("第二个提示词")
        second_result = await dynamic_system_prompt.awrap_model_call(
            request,
            capture,
        )

        assert isinstance(first_result.system_message, SystemMessage)
        assert first_result.system_message.content == "第一个提示词"
        assert second_result.system_message.content == "第二个提示词"

    asyncio.run(scenario())


def test_system_prompt_get_and_consecutive_post_api():
    client = TestClient(app)

    initial = client.get("/system-prompt")
    assert initial.status_code == 200
    assert initial.json() == {"system_prompt": DEFAULT_SYSTEM_PROMPT}

    first = client.post(
        "/system-prompt",
        json={"system_prompt": "第一个提示词"},
    )
    assert first.status_code == 200
    assert first.json() == {"system_prompt": "第一个提示词"}

    second = client.post(
        "/system-prompt",
        json={"system_prompt": "第二个提示词"},
    )
    assert second.status_code == 200
    assert second.json() == {"system_prompt": "第二个提示词"}

    current = client.get("/system-prompt")
    assert current.status_code == 200
    assert current.json() == {"system_prompt": "第二个提示词"}


@pytest.mark.parametrize("invalid_prompt", ["", "   ", "\n\t"])
def test_blank_system_prompt_is_rejected_without_overwriting_current_value(
    invalid_prompt,
):
    client = TestClient(app)
    system_prompt_store.update("保留这个提示词")

    response = client.post(
        "/system-prompt",
        json={"system_prompt": invalid_prompt},
    )

    assert response.status_code == 422
    assert client.get("/system-prompt").json() == {
        "system_prompt": "保留这个提示词",
    }
