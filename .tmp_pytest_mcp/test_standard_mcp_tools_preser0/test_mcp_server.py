from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-rag")

@mcp.tool()
def get_RAG_result(command: str) -> str:
    """Search the private knowledge base for information relevant to the user's question.

    Use this tool for questions involving internal documents and private knowledge.

    Args:
        command: A complete and specific search query.

    Returns:
        The most relevant knowledge-base passages.
    """
    return f"知识库：{command}"

if __name__ == "__main__":
    mcp.run(transport="stdio")