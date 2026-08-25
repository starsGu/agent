import asyncio
import logging
import os
from datetime import date

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_tavily import TavilySearch
from . import plugin


load_dotenv()  # 改动：读取项目目录下的 .env
logger = logging.getLogger(__name__)


@tool("get_weather", description="Get weather and temperature of a location")
def get_weather(location: str) -> str:
    """
    Get the weather in a given location.
    Args:
        location: city name or coordinates
    """
    if location == "杭州" or location == "HangZhou":
        return f"Current weather in {location} is sunny, temperature is 22 celsius"
    elif location == "北京" or location == "Beijing":
        return f"Current weather in {location} is rainy, temperature is 85 fahrenheit"

    return "invalid location"


@tool("get_date", description="Get date")
def get_date() -> str:
    """
    Get the date.
    """
    print("tool(get_date)")
    return "it is 2026/8/5 today"


# 初始化工具，并设置参数，具体参数设置参考官网
tavilyTool = TavilySearch(
    max_results=5,
    topic="general",
)
@tool(
    "tavily_search_online",
    description=(
            "Search the internet for information on any topic. "
            "Use this tool when online search is needed to find relevant information from web sources."
    )
)
def tavily_search_online(search_query: str):
    """Search the internet for information on any topic. """
    print(f"tool(tavily_search_online): {search_query}")
    return tavilyTool.invoke(search_query)


# 以上为本机tool，不需要修改，以下为McpClient协程


class McpClient:
    """加载 MCP 工具，并维护当前在线服务器的工具注册表。"""

    def __init__(
        self,
        retry_interval: float | None = None,
    ):
        self.retry_interval = retry_interval if retry_interval is not None else float(
            os.getenv("MCP_RETRY_INTERVAL_SECONDS", "30")
        )
        self.mcp_status = False
        self._tool_lock = asyncio.Lock()
        self.all_mcp: dict[str, dict] = {}
        self.pending_mcp: set[str] = set()
        self._tools_by_server = {}
        self.available_tools = []
        self._client = None

    def _refresh_available_tools(self) -> None:
        self.available_tools = [
            current_tool
            for server_name, server_tools in self._tools_by_server.items()
            if server_name in self.all_mcp and server_name not in self.pending_mcp
            for current_tool in server_tools
        ]

    async def get_all_mcp(self) -> dict[str, dict]:
        """Reconcile desired MCP servers from the enabled plugin registry."""
        desired: dict[str, dict] = {}
        owners: dict[str, str] = {}
        for plugin_config in plugin.plugins:
            plugin_name = plugin_config["name"]
            if not plugin.use_plugins.get(plugin_name, False):
                continue
            for server_name, server_config in plugin_config["mcpServers"].items():
                if server_name in desired:
                    logger.warning(
                        "Ignoring duplicate MCP server '%s' from plugin '%s'; "
                        "already provided by '%s'",
                        server_name,
                        plugin_name,
                        owners[server_name],
                    )
                    continue
                desired[server_name] = dict(server_config)
                owners[server_name] = plugin_name

        async with self._tool_lock:
            previous = self.all_mcp
            changed = {
                server_name
                for server_name, config in desired.items()
                if previous.get(server_name) != config
            }
            removed = set(previous) - set(desired)

            self.all_mcp = desired
            self.pending_mcp.intersection_update(desired)
            self.pending_mcp.update(changed)
            for server_name in removed | changed:
                self._tools_by_server.pop(server_name, None)

            if desired != previous:
                self._client = MultiServerMCPClient(dict(desired)) if desired else None
            self._refresh_available_tools()
            return dict(self.all_mcp)

    async def _publish_server_tools(self, server_name, tools, expected_client=None):
        async with self._tool_lock:
            if server_name not in self.all_mcp:
                return
            if expected_client is not None and expected_client is not self._client:
                return
            self._tools_by_server[server_name] = list(tools)
            self.pending_mcp.discard(server_name)
            self._refresh_available_tools()

    async def mark_server_offline(self, server_name):
        """服务器下线时移除工具，并重新加入连接重试队列。"""
        async with self._tool_lock:
            self._tools_by_server.pop(server_name, None)
            if server_name in self.all_mcp:
                self.pending_mcp.add(server_name)
            self._refresh_available_tools()

    async def snapshot_tools(self):
        async with self._tool_lock:
            return list(self.available_tools)

    async def resolve_tool(self, tool_name):
        async with self._tool_lock:
            for server_name, tools in self._tools_by_server.items():
                for current_tool in tools:
                    if current_tool.name == tool_name:
                        return server_name, current_tool
        return None

    async def run(self) -> None:
        """立即连接所有服务器，之后持续重试当前离线的服务器。"""
        await self.get_all_mcp()
        self.mcp_status = True
        try:
            while True:
                async with self._tool_lock:
                    pending_servers = list(self.pending_mcp)
                    current_client = self._client

                if current_client is not None:
                    for server_name in pending_servers:
                        try:
                            tools = await current_client.get_tools(server_name=server_name)
                        except Exception as exc:
                            logger.warning(
                                "Unable to connect to MCP server '%s': %s",
                                server_name,
                                exc,
                            )
                            continue
                        await self._publish_server_tools(
                            server_name,
                            tools,
                            expected_client=current_client,
                        )

                await asyncio.sleep(self.retry_interval)
        finally:
            self.mcp_status = False

    async def get_mcp_tools(self):
        return await self.snapshot_tools()


''' ai不能修改以下设计方案

from . import plugin

tool.py一运行需要有个 McpClient 协程，管理 mcp 连接，mcp 服务器参数放在 env 里，从 env 读取

    self.all_mcp
    self.pending_mcp

    __init__
        协程一启动，get_all_mcp, 尝试建立连接 all_mcp 中每个 mcp 服务器连接失败的加入 pending_mcp

    agent 调用时连接 mcp 失败，说明连接断线，及时更新列表 pending_mcp,

    get_all_mcp
        读取 全局plugins 中 use_plugin 为 true 的 要链接的mcp服务器列表(all_mcp)

    run:
        主循环：
            如果还有没建立的连接 pending_mcp ，每隔一段时间，尝试建立。

    暴露接 get_mcp_tools
        返回 all_mcp - pending_mcp = available_tools， 主要结合 agent 使用

'''
