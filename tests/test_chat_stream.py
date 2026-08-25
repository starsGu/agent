from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)

import cli
from agent.agent import CustomAgent, MCPToolDisconnectedError


class FakeMcpClient:
    pass


class StreamingGraph:
    def __init__(self, events, failure=None):
        self.events = events
        self.failure = failure
        self.calls = []
        self.updated_state = None
        self.state_reads = 0

    async def aget_state(self, config):
        self.state_reads += 1
        messages = []
        if self.state_reads > 1:
            messages = [HumanMessage(content="new", id="new-message")]
        return SimpleNamespace(values={"messages": messages})

    async def astream(self, payload, config, **kwargs):
        self.calls.append((payload, config, kwargs))
        for event in self.events:
            yield event
        if self.failure is not None:
            raise self.failure

    async def aupdate_state(self, config, update):
        self.updated_state = (config, update)


def message_event(message):
    return {"type": "messages", "data": (message, {"langgraph_node": "model"})}


def test_custom_agent_streams_text_and_completes_tool_calls(tmp_path):
    async def scenario():
        graph = StreamingGraph([
            message_event(AIMessageChunk(content="我来")),
            message_event(AIMessageChunk(
                content="检查",
                tool_call_chunks=[{
                    "name": "run_",
                    "args": "{\"path\":",
                    "id": "call-1",
                    "index": 0,
                }],
            )),
            message_event(AIMessageChunk(
                content="",
                tool_call_chunks=[{
                    "name": "python",
                    "args": "\"a.pdf\"}",
                    "id": None,
                    "index": 0,
                }],
            )),
            message_event(AIMessageChunk(content="", chunk_position="last")),
            message_event(AIMessageChunk(content="处理完成")),
            message_event(AIMessageChunk(content="。", chunk_position="last")),
        ])
        agent = CustomAgent(FakeMcpClient())
        agent.agent = graph

        events = [
            event
            async for event in agent.astream_chat(
                "检查 PDF",
                "session-1",
                str(tmp_path),
            )
        ]

        assert events == [
            {"type": "chunk", "kind": "text", "text": "我来"},
            {"type": "chunk", "kind": "text", "text": "检查"},
            {
                "type": "chunk",
                "kind": "tool_call",
                "call_key": "generation-0:0",
                "name_delta": "run_",
                "arguments_delta": "{\"path\":",
            },
            {
                "type": "chunk",
                "kind": "tool_call",
                "call_key": "generation-0:0",
                "name_delta": "python",
                "arguments_delta": "\"a.pdf\"}",
            },
            {
                "type": "tool_call_done",
                "call_key": "generation-0:0",
                "tool_call_id": "call-1",
                "name": "run_python",
                "status": "complete",
            },
            {"type": "chunk", "kind": "text", "text": "处理完成"},
            {"type": "chunk", "kind": "text", "text": "。"},
        ]
        assert graph.calls[0][2] == {
            "stream_mode": "messages",
            "version": "v2",
        }

    asyncio.run(scenario())


def test_custom_agent_rolls_back_a_failed_stream(tmp_path):
    async def scenario():
        graph = StreamingGraph(
            [message_event(AIMessageChunk(content="partial"))],
            failure=MCPToolDisconnectedError("run_python"),
        )
        agent = CustomAgent(FakeMcpClient())
        agent.agent = graph

        try:
            async for _ in agent.astream_chat(
                "hello",
                "session-1",
                str(tmp_path),
            ):
                pass
        except MCPToolDisconnectedError:
            pass
        else:
            raise AssertionError("expected MCPToolDisconnectedError")

        _, update = graph.updated_state
        assert [message.id for message in update["messages"]] == ["new-message"]

    asyncio.run(scenario())


def test_custom_agent_rolls_back_when_stream_consumer_cancels(tmp_path):
    async def scenario():
        graph = StreamingGraph([
            message_event(AIMessageChunk(content="partial")),
            message_event(AIMessageChunk(content="unused", chunk_position="last")),
        ])
        agent = CustomAgent(FakeMcpClient())
        agent.agent = graph
        stream = agent.astream_chat(
            "hello",
            "session-1",
            str(tmp_path),
        )

        assert await anext(stream) == {
            "type": "chunk",
            "kind": "text",
            "text": "partial",
        }
        await stream.aclose()

        _, update = graph.updated_state
        assert [message.id for message in update["messages"]] == ["new-message"]

    asyncio.run(scenario())


class StructuredStreamAgent:
    async def astream_chat(self, *args):
        yield {"type": "chunk", "kind": "text", "text": "我来检查"}
        yield {
            "type": "chunk",
            "kind": "tool_call",
            "call_key": "generation-0:0",
            "name_delta": "run_python",
            "arguments_delta": "{\"path\":\"a.pdf\"}",
        }
        yield {
            "type": "tool_call_done",
            "call_key": "generation-0:0",
            "tool_call_id": "call-1",
            "name": "run_python",
            "status": "complete",
        }
        yield {"type": "chunk", "kind": "text", "text": "完成"}


def test_cli_stream_persists_structured_current_turn_only(tmp_path):
    async def scenario():
        service = cli.CLI()
        service.agent = StructuredStreamAgent()

        events = [
            event
            async for event in service.stream_chat(
                "检查 PDF",
                "session-1",
                str(tmp_path),
            )
        ]

        expected_segments = [
            {"type": "text", "text": "我来检查"},
            {
                "type": "tool_call",
                "tool_call_id": "call-1",
                "name": "run_python",
                "status": "complete",
            },
            {"type": "text", "text": "完成"},
        ]
        assert events[-1] == {
            "type": "done",
            "session_id": "session-1",
            "ai_message": expected_segments,
        }
        assert service.chatList == {
            "session-1": [{
                "human_message": "检查 PDF",
                "ai_message": expected_segments,
            }],
        }
        assert service.sessionList == ["session-1"]

    asyncio.run(scenario())


class InvokeAgent:
    async def achat(self, *args):
        return {
            "messages": [
                HumanMessage(content="检查 PDF"),
                AIMessage(
                    content="我来检查",
                    tool_calls=[{
                        "name": "run_python",
                        "args": {"path": "a.pdf"},
                        "id": "call-1",
                    }],
                ),
                ToolMessage(content="private result", tool_call_id="call-1"),
                AIMessage(content="处理完成"),
            ],
        }


def test_invoke_returns_final_text_but_saves_all_ai_segments(tmp_path):
    async def scenario():
        service = cli.CLI()
        service.agent = InvokeAgent()

        reply = await service.chat(
            "检查 PDF",
            "session-1",
            str(tmp_path),
        )

        assert reply == "处理完成"
        assert service.chatList["session-1"][0]["ai_message"] == [
            {"type": "text", "text": "我来检查"},
            {
                "type": "tool_call",
                "tool_call_id": "call-1",
                "name": "run_python",
                "status": "complete",
            },
            {"type": "text", "text": "处理完成"},
        ]

    asyncio.run(scenario())


def test_load_memory_rebuilds_text_and_tool_segments_without_tool_results():
    class Checkpointer:
        async def alist(self, config):
            yield SimpleNamespace(
                config={"configurable": {"thread_id": "session-1"}},
                checkpoint={
                    "channel_values": {
                        "messages": [
                            HumanMessage(content="检查 PDF"),
                            AIMessage(
                                content="我来检查",
                                tool_calls=[{
                                    "name": "run_python",
                                    "args": {"path": "a.pdf"},
                                    "id": "call-1",
                                }],
                            ),
                            ToolMessage(
                                content="private result",
                                tool_call_id="call-1",
                            ),
                            AIMessage(content="处理完成"),
                        ],
                    },
                },
            )

    async def scenario():
        service = cli.CLI()
        service.agent = SimpleNamespace(checkpointer=Checkpointer())

        await service.loadMemory()

        assert service.chatList == {
            "session-1": [{
                "human_message": "检查 PDF",
                "ai_message": [
                    {"type": "text", "text": "我来检查"},
                    {
                        "type": "tool_call",
                        "tool_call_id": "call-1",
                        "name": "run_python",
                        "status": "complete",
                    },
                    {"type": "text", "text": "处理完成"},
                ],
            }],
        }

    asyncio.run(scenario())


def test_streaming_response_is_ndjson_for_one_turn(monkeypatch, tmp_path):
    class FakeService:
        agent = object()

        async def stream_chat(self, **kwargs):
            yield {"type": "chunk", "kind": "text", "text": "hello"}
            yield {
                "type": "done",
                "session_id": kwargs["session_id"],
                "ai_message": [{"type": "text", "text": "hello"}],
            }

    async def scenario():
        monkeypatch.setattr(cli, "service", FakeService())
        response = await cli.chatStream(cli.ChatRequest(
            human_message="hello",
            session_id="session-1",
            working_directory=str(tmp_path),
        ))
        body = b"".join([chunk async for chunk in response.body_iterator])
        events = [json.loads(line) for line in body.decode().splitlines()]

        assert response.media_type == "application/x-ndjson"
        assert response.headers["x-accel-buffering"] == "no"
        assert events == [
            {"type": "start", "session_id": "session-1"},
            {"type": "chunk", "kind": "text", "text": "hello"},
            {
                "type": "done",
                "session_id": "session-1",
                "ai_message": [{"type": "text", "text": "hello"}],
            },
        ]

    asyncio.run(scenario())
