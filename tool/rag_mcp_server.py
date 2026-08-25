import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from HybridRetriever import Retriever, RetrieverConfig


load_dotenv(Path(__file__).with_name(".env"))

retriever = Retriever(
    RetrieverConfig(
        corpus_db_path=Path(os.environ["RAG_CORPUS_DB_PATH"]),
        vector_db_path=Path(os.environ["RAG_VECTOR_DB_PATH"]),
        model_path=os.environ["RAG_MODEL_PATH"],
    )
)

mcp = FastMCP(
    "rag-knowledge-base",
    host="127.0.0.1",
    port=8001,
    streamable_http_path="/mcp",
    stateless_http=True,
)


@mcp.tool()
def get_RAG_result(command: str) -> str:
    """
    Search the private knowledge base for information relevant to the user's question.

    Use this tool for questions involving internal documents, policies, products,
    procedures, or other private knowledge.

    Args:
        command: A complete and specific search query.

    Returns:
        The five most relevant knowledge-base passages.
    """
    results = retriever.retrieve(command.strip(), 5)

    if not results:
        return "No relevant content was found in the knowledge base."

    return "\n\n".join(
        f"[{index}]\n{result.content}"
        for index, result in enumerate(results, start=1)
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")