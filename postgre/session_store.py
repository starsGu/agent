"""Persistent metadata for browser-visible Agent conversations.

LangGraph remains the source of truth for message history.  This module owns
only the small, independent table used to decide which ``thread_id`` values
are Web sessions and how those sessions are presented in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .postgresql import get_database_url


DEFAULT_SESSION_TITLE = "新对话"


@dataclass(frozen=True, slots=True)
class WebSession:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class SessionStore(Protocol):
    """Interface consumed by the Agent API and implemented by test fakes."""

    async def create_session(self) -> WebSession: ...

    async def list_sessions(self) -> list[WebSession]: ...

    async def get_session(self, session_id: str) -> WebSession | None: ...

    async def touch_session(
        self,
        session_id: str,
        *,
        first_message_title: str,
    ) -> WebSession | None: ...

    async def aclose(self) -> None: ...


class PostgresSessionStore:
    """Store Web session metadata in the checkpoint database.

    A separate connection is intentional: LangGraph owns its checkpointer
    connection while this class owns the lifecycle of metadata operations.
    """

    def __init__(self, connection: psycopg.AsyncConnection) -> None:
        self._connection = connection

    @classmethod
    async def connect(cls, database_url: str | None = None) -> "PostgresSessionStore":
        connection = await psycopg.AsyncConnection.connect(
            database_url or get_database_url(),
            autocommit=True,
            connect_timeout=5,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        store = cls(connection)
        try:
            await store.setup()
        except Exception:
            await connection.close()
            raise
        return store

    async def setup(self) -> None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS frontier_web_sessions (
                    id TEXT PRIMARY KEY
                        CHECK (id ~ '^web:[0-9a-f]{32}$'),
                    title TEXT NOT NULL DEFAULT '新对话',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    frontier_web_sessions_updated_at_idx
                ON frontier_web_sessions (updated_at DESC, created_at DESC)
                """
            )

    async def create_session(self) -> WebSession:
        session_id = f"web:{uuid4().hex}"
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO frontier_web_sessions (id)
                VALUES (%s)
                RETURNING id, title, created_at, updated_at
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
        if row is None:  # pragma: no cover - PostgreSQL RETURNING is mandatory
            raise RuntimeError("session insert returned no row")
        return _session_from_row(row)

    async def list_sessions(self) -> list[WebSession]:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM frontier_web_sessions
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """
            )
            rows = await cursor.fetchall()
        return [_session_from_row(row) for row in rows]

    async def get_session(self, session_id: str) -> WebSession | None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM frontier_web_sessions
                WHERE id = %s
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else _session_from_row(row)

    async def touch_session(
        self,
        session_id: str,
        *,
        first_message_title: str,
    ) -> WebSession | None:
        """Touch an existing session and title it on its first chat turn."""

        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """
                UPDATE frontier_web_sessions
                SET
                    title = CASE
                        WHEN title = %s THEN %s
                        ELSE title
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, title, created_at, updated_at
                """,
                (DEFAULT_SESSION_TITLE, first_message_title, session_id),
            )
            row = await cursor.fetchone()
        return None if row is None else _session_from_row(row)

    async def aclose(self) -> None:
        if not self._connection.closed:
            await self._connection.close()


def _session_from_row(row: dict[str, object]) -> WebSession:
    return WebSession(
        id=str(row["id"]),
        title=str(row["title"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )
