from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

tool_module = importlib.import_module("tool.tool")
local_tools_module = importlib.import_module("tool.local_tools")


def configure_plugins(monkeypatch, servers, name="test-plugin"):
    monkeypatch.setattr(
        tool_module.plugin,
        "plugins",
        [{"name": name, "version": "1.0.0", "mcpServers": servers}],
    )
    monkeypatch.setattr(tool_module.plugin, "use_plugins", {name: True})


def test_plugin_discovery_loads_manifest_and_mcp_config(tmp_path):
    plugin_module = importlib.import_module("tool.plugin")
    version_dir = tmp_path / "sample-plugin" / "1.0.0"
    manifest_dir = version_dir / ".plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "sample-plugin",
                "version": "1.0.0",
                "mcpServers": "./.mcp.json",
            }
        ),
        encoding="utf-8",
    )
    (version_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sample": {
                        "transport": "streamable_http",
                        "url": "http://sample",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    plugins, use_plugins = plugin_module.discover_plugins(tmp_path)

    assert plugins == [
        {
            "name": "sample-plugin",
            "version": "1.0.0",
            "mcpServers": {
                "sample": {
                    "transport": "streamable_http",
                    "url": "http://sample",
                }
            },
        }
    ]
    assert use_plugins == {"sample-plugin": True}


def test_plugin_discovery_skips_invalid_and_outside_paths(tmp_path):
    plugin_module = importlib.import_module("tool.plugin")
    invalid_dir = tmp_path / "invalid" / "1.0.0" / ".plugin"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "plugin.json").write_text("{", encoding="utf-8")

    outside_dir = tmp_path / "outside" / "1.0.0" / ".plugin"
    outside_dir.mkdir(parents=True)
    (outside_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "outside",
                "version": "1.0.0",
                "mcpServers": "../../../outside.json",
            }
        ),
        encoding="utf-8",
    )

    assert plugin_module.discover_plugins(tmp_path) == ([], {})


def test_skill_discovery_loads_frontmatter_and_private_runtime_metadata(tmp_path):
    plugin_module = importlib.import_module("tool.plugin")
    version_dir = tmp_path / "sample-plugin" / "1.0.0"
    manifest_dir = version_dir / ".plugin"
    skill_dir = version_dir / "skills" / "sample-skill"
    manifest_dir.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "sample-plugin",
                "version": "1.0.0",
                "mcpServers": "./.mcp.json",
            }
        ),
        encoding="utf-8",
    )
    (version_dir / ".mcp.json").write_text(
        json.dumps({"mcpServers": {}}),
        encoding="utf-8",
    )
    skill_content = (
        "---\n"
        "name: sample-skill\n"
        "description: 处理中文任务。\n"
        "---\n\n"
        "# Workflow\n"
    )
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_content, encoding="utf-8")

    plugins, _ = plugin_module.discover_plugins(tmp_path)
    skills, records = plugin_module.discover_skills(plugins, tmp_path)

    assert skills == [{"name": "sample-skill", "description": "处理中文任务。"}]
    assert records["sample-skill"]["plugin_name"] == "sample-plugin"
    assert records["sample-skill"]["path"] == skill_path.resolve()
    assert records["sample-skill"]["skill_root_dir"] == skill_dir.resolve()


def test_skill_discovery_skips_invalid_and_duplicate_skills(tmp_path):
    plugin_module = importlib.import_module("tool.plugin")

    for plugin_name in ("a-plugin", "b-plugin"):
        version_dir = tmp_path / plugin_name / "1.0.0"
        manifest_dir = version_dir / ".plugin"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "version": "1.0.0",
                    "mcpServers": "./.mcp.json",
                }
            ),
            encoding="utf-8",
        )
        (version_dir / ".mcp.json").write_text(
            json.dumps({"mcpServers": {}}),
            encoding="utf-8",
        )

    first_skill = tmp_path / "a-plugin" / "1.0.0" / "skills" / "duplicate"
    second_skill = tmp_path / "b-plugin" / "1.0.0" / "skills" / "duplicate"
    invalid_skill = tmp_path / "b-plugin" / "1.0.0" / "skills" / "invalid"
    missing_field_skill = (
        tmp_path / "b-plugin" / "1.0.0" / "skills" / "missing-field"
    )
    first_skill.mkdir(parents=True)
    second_skill.mkdir(parents=True)
    invalid_skill.mkdir(parents=True)
    missing_field_skill.mkdir(parents=True)
    (first_skill / "SKILL.md").write_text(
        "---\nname: duplicate\ndescription: first\n---\n",
        encoding="utf-8",
    )
    (second_skill / "SKILL.md").write_text(
        "---\nname: duplicate\ndescription: second\n---\n",
        encoding="utf-8",
    )
    (invalid_skill / "SKILL.md").write_text(
        "---\nname: invalid\ndescription: [\n---\n",
        encoding="utf-8",
    )
    (missing_field_skill / "SKILL.md").write_text(
        "---\nname: missing-field\n---\n",
        encoding="utf-8",
    )

    plugins, _ = plugin_module.discover_plugins(tmp_path)
    skills, records = plugin_module.discover_skills(plugins, tmp_path)

    assert skills == [{"name": "duplicate", "description": "first"}]
    assert records["duplicate"]["plugin_name"] == "a-plugin"


def test_skill_tool_loads_only_registered_skills_from_enabled_plugins(
    tmp_path,
    monkeypatch,
):
    skill_dir = tmp_path / "sample-skill"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    content = "---\nname: sample-skill\ndescription: sample description\n---\n"
    skill_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        local_tools_module.plugin,
        "skills",
        [{"name": "sample-skill", "description": "sample description"}],
    )
    monkeypatch.setattr(
        local_tools_module.plugin,
        "_skill_records",
        {
            "sample-skill": {
                "name": "sample-skill",
                "description": "sample description",
                "plugin_name": "sample-plugin",
                "path": skill_path.resolve(),
                "skill_root_dir": skill_dir.resolve(),
            }
        },
    )
    monkeypatch.setattr(
        local_tools_module.plugin,
        "use_plugins",
        {"sample-plugin": True},
    )

    dynamic_tool = local_tools_module.get_dynamic_skill_tool()
    result = local_tools_module.skill.invoke({"name": "sample-skill"})

    assert "sample-skill: sample description" in dynamic_tool.description
    assert result == {
        "ok": True,
        "name": "sample-skill",
        "plugin_name": "sample-plugin",
        "path": str(skill_path.resolve()),
        "skill_root_dir": str(skill_dir.resolve()),
        "content": skill_path.read_bytes().decode("utf-8"),
    }

    local_tools_module.plugin.use_plugins["sample-plugin"] = False
    dynamic_tool = local_tools_module.get_dynamic_skill_tool()
    result = local_tools_module.skill.invoke({"name": "sample-skill"})

    assert "sample-skill: sample description" not in dynamic_tool.description
    assert result["ok"] is False
    assert result["error_code"] == "plugin_disabled"


def test_skill_tool_returns_structured_file_errors(tmp_path, monkeypatch):
    skill_dir = tmp_path / "sample-skill"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("valid", encoding="utf-8")
    record = {
        "name": "sample-skill",
        "description": "sample",
        "plugin_name": "sample-plugin",
        "path": skill_path.resolve(),
        "skill_root_dir": skill_dir.resolve(),
    }
    monkeypatch.setattr(local_tools_module.plugin, "skills", [])
    monkeypatch.setattr(
        local_tools_module.plugin,
        "_skill_records",
        {"sample-skill": record},
    )
    monkeypatch.setattr(
        local_tools_module.plugin,
        "use_plugins",
        {"sample-plugin": True},
    )

    assert local_tools_module.skill.invoke({"name": "missing"})["error_code"] == (
        "skill_not_found"
    )

    skill_path.unlink()
    missing_result = local_tools_module.skill.invoke({"name": "sample-skill"})
    assert missing_result["error_code"] == "file_not_found"

    skill_path.write_bytes(b"x" * (local_tools_module.MAX_FILE_SIZE_BYTES + 1))
    oversized_result = local_tools_module.skill.invoke({"name": "sample-skill"})
    assert oversized_result["error_code"] == "file_too_large"


def test_standard_mcp_tools_preserve_description_and_invoke(tmp_path, monkeypatch):
    server_path = tmp_path / "test_mcp_server.py"
    server_path.write_text(
        '''
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
'''.strip(),
        encoding="utf-8",
    )

    configure_plugins(
        monkeypatch,
        {
            "rag": {
                "command": sys.executable,
                "args": [str(server_path.resolve())],
                "transport": "stdio",
            }
        },
    )

    async def scenario():
        client = tool_module.McpClient(
            retry_interval=0.01,
        )
        service_task = asyncio.create_task(client.run())
        try:
            deadline = asyncio.get_running_loop().time() + 5
            tools = []
            while not tools and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
                tools = await client.get_mcp_tools()
            rag_tool = next(tool for tool in tools if tool.name == "get_RAG_result")

            assert "Search the private knowledge base" in rag_tool.description
            assert "internal documents and private knowledge" in rag_tool.description

            result = await rag_tool.ainvoke({"command": "异步调用"})
            assert "知识库：异步调用" in str(result)
        finally:
            service_task.cancel()
            await asyncio.gather(service_task, return_exceptions=True)

    asyncio.run(scenario())


def test_get_mcp_tools_does_not_wait_for_run(monkeypatch):
    monkeypatch.setattr(tool_module.plugin, "plugins", [])
    monkeypatch.setattr(tool_module.plugin, "use_plugins", {})

    async def scenario():
        client = tool_module.McpClient()
        assert client.mcp_status is False
        assert await client.get_mcp_tools() == []

        service_task = asyncio.create_task(client.run())
        try:
            await asyncio.sleep(0)
            assert client.mcp_status is True
        finally:
            service_task.cancel()
            await asyncio.gather(service_task, return_exceptions=True)

    asyncio.run(scenario())


def test_custom_agent_registers_loaded_mcp_tools(monkeypatch):
    agent_module = importlib.import_module("agent.agent")
    captured = {}
    rag_tool = SimpleNamespace(name="get_RAG_result")

    class FakeConnection:
        async def close(self):
            pass

    class FakeMcpClient:
        async def get_mcp_tools(self):
            raise AssertionError("create_agent must not wait for MCP tools")

        async def snapshot_tools(self):
            return [rag_tool]

        async def resolve_tool(self, tool_name):
            return None

    async def fake_postgre_init():
        return SimpleNamespace(conn=FakeConnection())

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setenv("DEEPSEEK_MODEL_NAME", "test-model")
    monkeypatch.setattr(agent_module, "postgreInit", fake_postgre_init)
    monkeypatch.setattr(agent_module, "init_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(agent_module, "create_agent", fake_create_agent)

    asyncio.run(agent_module.CustomAgent(FakeMcpClient()).create_agent())

    assert rag_tool not in captured["tools"]
    assert {current_tool.name for current_tool in captured["tools"]} == {
        "run_skill_script",
        "run_python",
        "run_node",
        "run_program",
        "read_skill_resource",
        "skill",
    }
    assert len(captured["middleware"]) == 2
    assert captured["middleware"][0] is agent_module.dynamic_system_prompt
    assert isinstance(
        captured["middleware"][1],
        agent_module.DynamicMCPToolsMiddleware,
    )


def test_run_connects_all_servers_and_keeps_failures_pending(monkeypatch):
    configure_plugins(
        monkeypatch,
        {
            "online": {"transport": "streamable_http", "url": "http://online"},
            "offline": {"transport": "streamable_http", "url": "http://offline"},
        },
    )

    async def scenario():
        client = tool_module.McpClient(retry_interval=60)
        online_tool = SimpleNamespace(name="online_tool")
        first_round_done = asyncio.Event()
        attempted = set()

        class FakeAdapterClient:
            async def get_tools(self, server_name):
                attempted.add(server_name)
                if attempted == {"online", "offline"}:
                    first_round_done.set()
                if server_name == "offline":
                    raise ConnectionError("offline")
                return [online_tool]

        await client.get_all_mcp()
        client._client = FakeAdapterClient()
        service_task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(first_round_done.wait(), timeout=1)
            await asyncio.sleep(0)
            assert attempted == {"online", "offline"}
            assert client.pending_mcp == {"offline"}
            assert await client.get_mcp_tools() == [online_tool]
        finally:
            service_task.cancel()
            await asyncio.gather(service_task, return_exceptions=True)

    asyncio.run(scenario())


def test_offline_server_is_retried_and_restored(monkeypatch):
    configure_plugins(
        monkeypatch,
        {"rag": {"transport": "streamable_http", "url": "http://rag"}},
    )

    async def scenario():
        client = tool_module.McpClient(retry_interval=60)
        old_tool = SimpleNamespace(name="old_rag_tool")
        new_tool = SimpleNamespace(name="new_rag_tool")
        reconnected = asyncio.Event()

        class FakeAdapterClient:
            async def get_tools(self, server_name):
                assert server_name == "rag"
                reconnected.set()
                return [new_tool]

        await client.get_all_mcp()
        await client._publish_server_tools("rag", [old_tool])
        await client.mark_server_offline("rag")
        assert await client.get_mcp_tools() == []
        assert client.pending_mcp == {"rag"}

        client._client = FakeAdapterClient()
        service_task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(reconnected.wait(), timeout=1)
            await asyncio.sleep(0)
            assert await client.get_mcp_tools() == [new_tool]
            assert client.pending_mcp == set()
        finally:
            service_task.cancel()
            await asyncio.gather(service_task, return_exceptions=True)

    asyncio.run(scenario())


def test_get_all_mcp_reconciles_runtime_plugin_toggles(monkeypatch):
    monkeypatch.setattr(
        tool_module.plugin,
        "plugins",
        [
            {
                "name": "rag-plugin",
                "version": "1.0.0",
                "mcpServers": {
                    "rag": {"transport": "streamable_http", "url": "http://rag"}
                },
            },
            {
                "name": "fetch-plugin",
                "version": "1.0.0",
                "mcpServers": {
                    "fetch": {
                        "transport": "streamable_http",
                        "url": "http://fetch",
                    }
                },
            },
        ],
    )
    monkeypatch.setattr(
        tool_module.plugin,
        "use_plugins",
        {"rag-plugin": True, "fetch-plugin": False},
    )

    async def scenario():
        client = tool_module.McpClient()
        await client.get_all_mcp()
        assert set(client.all_mcp) == {"rag"}
        assert client.pending_mcp == {"rag"}

        rag_tool = SimpleNamespace(name="rag_search")
        await client._publish_server_tools("rag", [rag_tool])
        assert await client.get_mcp_tools() == [rag_tool]

        tool_module.plugin.use_plugins["rag-plugin"] = False
        tool_module.plugin.use_plugins["fetch-plugin"] = True
        await client.get_all_mcp()

        assert set(client.all_mcp) == {"fetch"}
        assert client.pending_mcp == {"fetch"}
        assert await client.get_mcp_tools() == []

    asyncio.run(scenario())


def test_plugin_fastapi_endpoints(monkeypatch):
    cli_module = importlib.import_module("cli")
    monkeypatch.setattr(
        cli_module.plugin_registry,
        "plugins",
        [
            {
                "name": "rag-plugin",
                "version": "1.0.0",
                "mcpServers": {"rag": {}},
            }
        ],
    )
    monkeypatch.setattr(
        cli_module.plugin_registry,
        "use_plugins",
        {"rag-plugin": True},
    )

    reconciliations = []
    class FakeMcpClient:
        async def get_all_mcp(self):
            reconciliations.append(dict(cli_module.plugin_registry.use_plugins))

    monkeypatch.setattr(cli_module.service, "mcp_client", FakeMcpClient())
    client = TestClient(cli_module.app)

    response = client.get("/plugins")
    assert response.status_code == 200
    assert response.json()["use_plugins"] == {"rag-plugin": True}

    response = client.post("/plugins/disable", json={"name": "rag-plugin"})
    assert response.status_code == 200
    assert response.json() == {"name": "rag-plugin", "enabled": False}
    assert reconciliations[-1] == {"rag-plugin": False}

    response = client.post("/plugins/enable", json={"name": "rag-plugin"})
    assert response.status_code == 200
    assert response.json() == {"name": "rag-plugin", "enabled": True}
    assert reconciliations[-1] == {"rag-plugin": True}

    assert client.post("/plugins/enable", json={"name": "missing"}).status_code == 404
    assert client.post("/plugins/enable", json={"name": " "}).status_code == 422


def test_dynamic_mcp_tools_follow_registry_without_recreating_agent(monkeypatch):
    agent_module = importlib.import_module("agent.agent")
    configure_plugins(
        monkeypatch,
        {"rag": {"transport": "streamable_http", "url": "http://rag"}},
    )

    class FakeModelRequest:
        def __init__(self, tools):
            self.tools = tools

        def override(self, **changes):
            return FakeModelRequest(changes.get("tools", self.tools))

    async def scenario():
        client = tool_module.McpClient()
        middleware = agent_module.DynamicMCPToolsMiddleware(client)
        rag_tool = SimpleNamespace(name="rag_search")
        local_tool = tool_module.get_date

        await client.get_all_mcp()
        await client._publish_server_tools("rag", [rag_tool])

        async def capture(request):
            return request

        online_request = await middleware.awrap_model_call(
            FakeModelRequest([local_tool]),
            capture,
        )
        assert online_request.tools == [local_tool, rag_tool]

        await client.mark_server_offline("rag")
        offline_request = await middleware.awrap_model_call(
            FakeModelRequest([local_tool]),
            capture,
        )
        assert offline_request.tools == [local_tool]

    asyncio.run(scenario())


def test_dynamic_tool_call_rechecks_online_status(monkeypatch):
    agent_module = importlib.import_module("agent.agent")
    configure_plugins(
        monkeypatch,
        {"rag": {"transport": "streamable_http", "url": "http://rag"}},
    )

    class FakeToolRequest:
        def __init__(self, tool=None):
            self.tool = tool
            self.tool_call = {"name": "rag_search", "id": "call-1", "args": {}}

        def override(self, **changes):
            return FakeToolRequest(tool=changes.get("tool", self.tool))

    async def scenario():
        client = tool_module.McpClient()
        middleware = agent_module.DynamicMCPToolsMiddleware(client)
        request = FakeToolRequest()

        async def execute(current_request):
            return ToolMessage(
                content="ok",
                tool_call_id=current_request.tool_call["id"],
            )

        with pytest.raises(agent_module.MCPToolDisconnectedError):
            await middleware.awrap_tool_call(request, execute)

        rag_tool = SimpleNamespace(name="rag_search")
        await client.get_all_mcp()
        await client._publish_server_tools("rag", [rag_tool])
        online_result = await middleware.awrap_tool_call(request, execute)
        assert online_result.status == "success"

        async def disconnect(current_request):
            raise ConnectionError("connection closed")

        with pytest.raises(agent_module.MCPToolDisconnectedError):
            await middleware.awrap_tool_call(request, disconnect)
        assert await client.get_mcp_tools() == []
        assert client.pending_mcp == {"rag"}

    asyncio.run(scenario())


def test_disconnected_tool_rolls_back_current_turn(monkeypatch):
    agent_module = importlib.import_module("agent.agent")

    class FakeMcpClient:
        pass

    class FakeGraph:
        def __init__(self):
            self.messages = [
                HumanMessage(content="previous", id="human-old"),
                AIMessage(content="answer", id="ai-old"),
            ]

        async def aget_state(self, config):
            return SimpleNamespace(values={"messages": list(self.messages)})

        async def ainvoke(self, payload, config):
            current_human = payload["messages"][0]
            self.messages.extend(
                [
                    current_human,
                    AIMessage(
                        content="",
                        id="ai-disconnected",
                        tool_calls=[
                            {
                                "name": "rag_search",
                                "args": {},
                                "id": "call-disconnected",
                                "type": "tool_call",
                            }
                        ],
                    ),
                ]
            )
            raise agent_module.MCPToolDisconnectedError("rag_search", "rag")

        async def aupdate_state(self, config, values):
            removed_ids = {message.id for message in values["messages"]}
            self.messages = [
                message for message in self.messages if message.id not in removed_ids
            ]

    async def scenario():
        custom_agent = agent_module.CustomAgent(FakeMcpClient())
        graph = FakeGraph()
        custom_agent.agent = graph

        with pytest.raises(agent_module.MCPToolDisconnectedError):
            await custom_agent.achat("current", "session-1")

        assert [message.id for message in graph.messages] == ["human-old", "ai-old"]

    asyncio.run(scenario())


def test_model_call_replaces_skill_schema_from_live_plugin_switches(monkeypatch):
    agent_module = importlib.import_module("agent.agent")
    monkeypatch.setattr(
        local_tools_module.plugin,
        "skills",
        [
            {"name": "alpha-skill", "description": "Alpha description"},
            {"name": "beta-skill", "description": "Beta description"},
        ],
    )
    monkeypatch.setattr(
        local_tools_module.plugin,
        "_skill_records",
        {
            "alpha-skill": {"plugin_name": "alpha-plugin"},
            "beta-skill": {"plugin_name": "beta-plugin"},
        },
    )
    monkeypatch.setattr(
        local_tools_module.plugin,
        "use_plugins",
        {"alpha-plugin": True, "beta-plugin": False},
    )

    class FakeMcpClient:
        def __init__(self):
            self.snapshot_calls = 0

        async def snapshot_tools(self):
            self.snapshot_calls += 1
            return []

        async def get_all_mcp(self):
            raise AssertionError("model calls must not reconcile or connect MCP servers")

    class FakeModelRequest:
        def __init__(self, tools):
            self.tools = tools

        def override(self, **changes):
            return FakeModelRequest(changes.get("tools", self.tools))

    async def scenario():
        client = FakeMcpClient()
        middleware = agent_module.DynamicMCPToolsMiddleware(client)
        request = FakeModelRequest([local_tools_module.skill])

        async def capture(current_request):
            return current_request

        first = await middleware.awrap_model_call(request, capture)
        local_tools_module.plugin.use_plugins["alpha-plugin"] = False
        second = await middleware.awrap_model_call(request, capture)
        local_tools_module.plugin.use_plugins["beta-plugin"] = True
        third = await middleware.awrap_model_call(request, capture)
        local_tools_module.plugin.use_plugins["alpha-plugin"] = True
        fourth = await middleware.awrap_model_call(request, capture)
        return client, first, second, third, fourth

    client, first, second, third, fourth = asyncio.run(scenario())
    descriptions = [request.tools[0].description for request in (first, second, third, fourth)]

    assert "alpha-skill: Alpha description" in descriptions[0]
    assert "beta-skill: Beta description" not in descriptions[0]
    assert "alpha-skill" not in descriptions[1]
    assert "beta-skill" not in descriptions[1]
    assert "No enabled skills" in descriptions[1]
    assert "alpha-skill" not in descriptions[2]
    assert "beta-skill: Beta description" in descriptions[2]
    assert "alpha-skill: Alpha description" in descriptions[3]
    assert "beta-skill: Beta description" in descriptions[3]
    assert all(request.tools[0] is not local_tools_module.skill for request in (first, second, third, fourth))
    assert client.snapshot_calls == 4


def test_rag_server_does_not_print_to_stdout():
    source = Path(tool_module.__file__).with_name("rag_mcp_server.py").read_text(encoding="utf-8")

    assert "print(" not in source
