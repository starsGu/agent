from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import cli
from agent.agent import CustomAgent


class FakeMcpClient:
    pass


class FakeGraph:
    def __init__(self):
        self.payload = None

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": []})

    async def ainvoke(self, payload, config):
        self.payload = payload
        return {"messages": [SimpleNamespace(content="ok")]}


def test_achat_appends_the_exact_working_directory_context(tmp_path):
    async def scenario():
        custom_agent = CustomAgent(FakeMcpClient())
        graph = FakeGraph()
        custom_agent.agent = graph

        await custom_agent.achat("hello", "session-1", str(tmp_path))

        message = graph.payload["messages"][0]
        assert message.content == (
            f"hello\n####\n当前工作目录是 {tmp_path.resolve()}\n####"
        )

    asyncio.run(scenario())


def test_chat_request_defaults_and_validates_working_directory(tmp_path):
    request = cli.ChatRequest(human_message="hello", session_id="session-1")
    assert request.working_directory is None

    request = cli.ChatRequest(
        human_message="hello",
        session_id="session-1",
        working_directory=str(tmp_path),
    )
    assert request.working_directory == str(tmp_path.resolve())

    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")
    invalid_directories = [
        "relative/path",
        str(file_path),
        str(tmp_path / "missing"),
    ]
    for invalid_directory in invalid_directories:
        with pytest.raises(ValidationError):
            cli.ChatRequest(
                human_message="hello",
                session_id="session-1",
                working_directory=invalid_directory,
            )


def test_directory_selection_preserves_cancelled_directory(monkeypatch, tmp_path):
    selected_initial_directories = []

    def cancel(initial_directory):
        selected_initial_directories.append(initial_directory)
        return None

    monkeypatch.setattr(cli, "select_working_directory", cancel)
    response = asyncio.run(
        cli.selectWorkingDirectory(
            cli.WorkingDirectorySelectionRequest(
                initial_directory=str(tmp_path),
            )
        )
    )

    assert response.cancelled is True
    assert response.working_directory == str(tmp_path.resolve())
    assert selected_initial_directories == [str(tmp_path.resolve())]


def test_directory_selection_falls_back_from_a_stale_initial_path(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(cli, "get_default_working_directory", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli,
        "select_working_directory",
        lambda initial_directory: initial_directory,
    )

    response = asyncio.run(
        cli.selectWorkingDirectory(
            cli.WorkingDirectorySelectionRequest(
                initial_directory=str(tmp_path / "missing"),
            )
        )
    )

    assert response.cancelled is False
    assert response.working_directory == str(tmp_path)
