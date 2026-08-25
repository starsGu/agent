import os

from .postgresql import postgreInit as _postgresqlInit
from .sqlite import sqliteInit

__all__ = ["postgreInit", "sqliteInit"]


async def postgreInit():
    """按配置创建 LangGraph checkpointer，默认使用 SQLite。"""
    backend = os.getenv("CHECKPOINT_BACKEND", "sqlite").strip().lower()

    if backend == "sqlite":
        return await sqliteInit()

    if backend in {"postgres", "postgresql", "postgre"}:
        return await _postgresqlInit()

    raise ValueError(
        "不支持的 CHECKPOINT_BACKEND："
        f"{backend!r}；可选值为 sqlite 或 postgresql"
    )
