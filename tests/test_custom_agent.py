from __future__ import annotations

import asyncio

from agent.agent import CustomAgent


class FakeGraph:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        return {"messages": []}

    async def aget_state(self, config):
        self.calls.append(("state", config))
        return {"persisted": True}


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1
        self.closed = True


def test_custom_agent_exposes_shared_invoke_contract():
    async def scenario():
        custom_agent = CustomAgent()
        graph = FakeGraph()
        custom_agent.agent = graph

        await custom_agent.ainvoke("hello", "cli:test")

        payload, config = graph.calls[0]
        assert payload["messages"][0].content == "hello"
        assert config == {"configurable": {"thread_id": "cli:test"}}

    asyncio.run(scenario())


def test_custom_agent_close_is_idempotent():
    async def scenario():
        custom_agent = CustomAgent()
        connection = FakeConnection()
        custom_agent.checkpointer = type(
            "FakeCheckpointer",
            (),
            {"conn": connection},
        )()

        await custom_agent.aclose()
        await custom_agent.aclose()

        assert connection.close_calls == 1
        assert custom_agent.checkpointer is None

    asyncio.run(scenario())


def test_custom_agent_loads_state_by_thread_id():
    async def scenario():
        custom_agent = CustomAgent()
        graph = FakeGraph()
        custom_agent.agent = graph

        state = await custom_agent.aget_state("web:test")

        assert state == {"persisted": True}
        assert graph.calls == [
            ("state", {"configurable": {"thread_id": "web:test"}}),
        ]

    asyncio.run(scenario())
