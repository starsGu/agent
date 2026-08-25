import os

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or "postgresql://langchain:456789@localhost:5432/langchain_memory"
)

async def postgreInit() -> AsyncPostgresSaver:
    """创建并初始化供异步 LangGraph agent 使用的 PostgreSQL checkpointer。"""
    connection = await psycopg.AsyncConnection.connect(
        DATABASE_URL,
        autocommit=True,
        connect_timeout=5,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules=[("agent.StructureOutput", "WeatherInfo")],
    )
    checkpointer = AsyncPostgresSaver(connection, serde=serializer)

    try:
        await checkpointer.setup()
    except Exception:
        await connection.close()
        raise

    return checkpointer


def main() -> None:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        current_database(),
                        current_user,
                        inet_server_addr(),
                        inet_server_port()
                """)
                print("连接成功：", cursor.fetchone())

    except psycopg.OperationalError as exc:
        print("连接失败：", repr(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
