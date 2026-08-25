from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

import postgre.sqlite as sqlite_module
from postgre import sqliteInit


def test_sqlite_checkpointer_persists_and_deletes_thread(tmp_path):
    database_path = tmp_path / "nested" / "checkpoints.sqlite"
    thread_config = {
        "configurable": {
            "thread_id": "sqlite:test",
            "checkpoint_ns": "",
        }
    }

    async def scenario():
        first = await sqliteInit(database_path)
        checkpoint = {
            "v": 4,
            "ts": datetime.now(UTC).isoformat(),
            "id": str(uuid4()),
            "channel_values": {"messages": ["persisted"]},
            "channel_versions": {"messages": "1"},
            "versions_seen": {},
            "updated_channels": ["messages"],
        }
        await first.aput(
            thread_config,
            checkpoint,
            {},
            {"messages": "1"},
        )
        await first.conn.close()

        second = await sqliteInit(database_path)
        restored = await second.aget_tuple(thread_config)
        assert restored is not None
        assert restored.checkpoint["channel_values"]["messages"] == ["persisted"]

        checkpoints = [item async for item in second.alist(None)]
        assert checkpoints

        await second.adelete_thread("sqlite:test")
        assert await second.aget_tuple(thread_config) is None
        await second.conn.close()

    asyncio.run(scenario())

    assert database_path.is_file()


def test_sqlite_init_uses_environment_path(tmp_path, monkeypatch):
    database_path = tmp_path / "from-env" / "memory.sqlite"
    monkeypatch.setenv("SQLITE_CHECKPOINT_PATH", str(database_path))

    async def scenario():
        checkpointer = await sqliteInit()
        await checkpointer.conn.close()

    asyncio.run(scenario())

    assert database_path.is_file()


def test_sqlite_init_argument_takes_priority_over_environment(tmp_path, monkeypatch):
    environment_path = tmp_path / "environment.sqlite"
    argument_path = tmp_path / "argument.sqlite"
    monkeypatch.setenv("SQLITE_CHECKPOINT_PATH", str(environment_path))

    async def scenario():
        checkpointer = await sqliteInit(argument_path)
        await checkpointer.conn.close()

    asyncio.run(scenario())

    assert argument_path.is_file()
    assert not environment_path.exists()


def test_sqlite_init_closes_connection_when_setup_fails(tmp_path, monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    class BrokenSaver:
        def __init__(self, connection, *, serde):
            self.conn = connection

        async def setup(self):
            raise RuntimeError("setup failed")

    connection = FakeConnection()

    async def fake_connect(_database_path):
        return connection

    monkeypatch.setattr(sqlite_module.aiosqlite, "connect", fake_connect)
    monkeypatch.setattr(sqlite_module, "AsyncSqliteSaver", BrokenSaver)

    async def scenario():
        with pytest.raises(RuntimeError, match="setup failed"):
            await sqlite_module.sqliteInit(tmp_path / "broken.sqlite")

    asyncio.run(scenario())

    assert connection.closed is True
