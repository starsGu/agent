from __future__ import annotations

import os
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_CHECKPOINT_PATH = (
    PROJECT_ROOT / "data" / "memory" / "checkpoints.sqlite"
)


def get_sqlite_checkpoint_path(
    database_path: str | Path | None = None,
) -> Path:
    """解析 SQLite checkpoint 文件路径。"""
    configured_path = database_path or os.getenv("SQLITE_CHECKPOINT_PATH")
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_SQLITE_CHECKPOINT_PATH

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path.resolve()


async def sqliteInit(
    database_path: str | Path | None = None,
) -> AsyncSqliteSaver:
    """创建并初始化供异步 LangGraph agent 使用的 SQLite checkpointer。"""
    path = get_sqlite_checkpoint_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = await aiosqlite.connect(str(path))
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules=[("agent.StructureOutput", "WeatherInfo")],
    )
    checkpointer = AsyncSqliteSaver(connection, serde=serializer)

    try:
        await checkpointer.setup()
    except Exception:
        await connection.close()
        raise

    return checkpointer
