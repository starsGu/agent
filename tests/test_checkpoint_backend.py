from __future__ import annotations

import asyncio

import pytest

import postgre


def test_checkpoint_backend_defaults_to_sqlite(monkeypatch):
    selected = []

    async def fake_sqlite_init():
        selected.append("sqlite")
        return object()

    async def fake_postgresql_init():
        selected.append("postgresql")
        return object()

    monkeypatch.delenv("CHECKPOINT_BACKEND", raising=False)
    monkeypatch.setattr(postgre, "sqliteInit", fake_sqlite_init)
    monkeypatch.setattr(postgre, "_postgresqlInit", fake_postgresql_init)

    asyncio.run(postgre.postgreInit())

    assert selected == ["sqlite"]


@pytest.mark.parametrize("backend", ["postgres", "postgresql", "postgre"])
def test_checkpoint_backend_can_select_postgresql(backend, monkeypatch):
    selected = []

    async def fake_sqlite_init():
        selected.append("sqlite")
        return object()

    async def fake_postgresql_init():
        selected.append("postgresql")
        return object()

    monkeypatch.setenv("CHECKPOINT_BACKEND", backend)
    monkeypatch.setattr(postgre, "sqliteInit", fake_sqlite_init)
    monkeypatch.setattr(postgre, "_postgresqlInit", fake_postgresql_init)

    asyncio.run(postgre.postgreInit())

    assert selected == ["postgresql"]


def test_checkpoint_backend_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_BACKEND", "redis")

    with pytest.raises(ValueError, match="CHECKPOINT_BACKEND"):
        asyncio.run(postgre.postgreInit())
