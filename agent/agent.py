from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ToolCallRequest
from langchain.chat_models import init_chat_model
import json
import logging
import os
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, RemoveMessage
from tool import (
    get_date,
    get_dynamic_skill_tool,
    read_file,
    read_skill_resource,
    run_node,
    run_program,
    run_python,
    run_skill_script,
    skill,
    tavily_search_online,
)
from postgre import postgreInit
from .StructureOutput import WeatherInfo
from .prompt import dynamic_system_prompt


logger = logging.getLogger(__name__)


class MCPToolDisconnectedError(ConnectionError):
    """MCP 工具断线；当前 Agent 调用必须从会话中回滚。"""

    def __init__(self, tool_name, server_name=None):
        self.tool_name = tool_name
        self.server_name = server_name
        super().__init__(f"MCP tool '{tool_name}' is currently offline")


class AgentReturnedNoReplyError(RuntimeError):
    """Agent 完成了一轮调用，但没有产生可展示的文本。"""


def text_content(content) -> str:
    """Extract user-visible text from a LangChain message content value."""

    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    text_parts = []
    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
            continue

        if not isinstance(block, dict):
            continue

        block_text = block.get("text")
        if isinstance(block_text, str) and block.get("type") in {
            None,
            "text",
            "output_text",
        }:
            text_parts.append(block_text)

    return "".join(text_parts)


class DynamicMCPToolsMiddleware(AgentMiddleware):
    """每次模型和工具调用都读取最新的 MCP 工具列表。"""

    def __init__(self, mcp_client):
        self.mcp_client = mcp_client

    async def awrap_model_call(self, request: ModelRequest, handler):
        '''把当前 MCP 工具告诉模型。'''
        mcp_tools = await self.mcp_client.snapshot_tools()
        model_tools = [
            get_dynamic_skill_tool()
            if getattr(current_tool, "name", None) == "skill"
            else current_tool
            for current_tool in request.tools
        ]
        return await handler(
            request.override(tools=[*model_tools, *mcp_tools])
        )

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        '''模型选择工具后，找到真正的工具并执行。'''
        '''执行时发现断线：MCPToolDisconnectedError'''
        # Statically registered local tools already have a concrete tool instance.
        if request.tool is not None:
            return await handler(request)

        tool_name = request.tool_call["name"]
        resolved = await self.mcp_client.resolve_tool(tool_name)
        if resolved is None:
            raise MCPToolDisconnectedError(tool_name)

        server_name, current_tool = resolved
        try:
            return await handler(request.override(tool=current_tool))
        except Exception as exc:
            await self.mcp_client.mark_server_offline(server_name)
            raise MCPToolDisconnectedError(tool_name, server_name) from exc

class CustomAgent():
    def __init__(self, mcp_client):
        self.model = None
        self.checkpointer = None
        self.agent = None
        self.mcp_client = mcp_client

    async def __aenter__(self):
        await self.create_agent()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.checkpointer.conn.close()

    @staticmethod
    def _config(session_id):
        return {"configurable": {"thread_id": session_id}}

    async def _message_ids(self, config):
        state = await self.agent.aget_state(config)
        return {
            message.id
            for message in state.values.get("messages", [])
            if message.id is not None
        }

    async def _rollback_messages(self, config, old_message_ids):
        state = await self.agent.aget_state(config)
        new_messages = [
            RemoveMessage(id=message.id)
            for message in state.values.get("messages", [])
            if message.id is not None and message.id not in old_message_ids
        ]
        if new_messages:
            await self.agent.aupdate_state(config, {"messages": new_messages})

    @staticmethod
    def _human_message(user_input, working_directory):
        resolved_working_directory = os.path.abspath(
            os.path.expanduser(working_directory or "~")
        )
        return HumanMessage(
            content=(
                f"{user_input}\n"
                "####\n"
                f"当前工作目录是 {resolved_working_directory}\n"
                "####"
            ),
            id=str(uuid4()),
        )

    @staticmethod
    def _stream_message(event):
        if not isinstance(event, dict) or event.get("type") != "messages":
            return None

        data = event.get("data")
        if not isinstance(data, (tuple, list)) or not data:
            return None

        message = data[0]
        if not isinstance(message, (AIMessage, AIMessageChunk)):
            return None
        return message

    @staticmethod
    def _tool_call_delta(call):
        if not isinstance(call, dict):
            return None

        name = call.get("name")
        arguments = call.get("args")
        call_id = call.get("id")
        index = call.get("index")
        if isinstance(arguments, dict):
            arguments = json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        return {
            "index": index if isinstance(index, int) else 0,
            "name": name if isinstance(name, str) else "",
            "arguments": arguments if isinstance(arguments, str) else "",
            "id": call_id if isinstance(call_id, str) else "",
        }

    async def achat(self, user_input, session_id, working_directory=None):
        config = self._config(session_id)
        old_message_ids = await self._message_ids(config)
        human_message = self._human_message(user_input, working_directory)
        try:
            response = await self.agent.ainvoke(
                {"messages": [human_message]},
                config,
            )
            messages = response.get("messages", [])
            if not messages or not text_content(messages[-1].content):
                raise AgentReturnedNoReplyError("agent_returned_no_reply")
        except BaseException:
            try:
                await self._rollback_messages(config, old_message_ids)
            except Exception:
                logger.exception("Unable to roll back failed agent invocation")
            raise
        print(response)
        return response

    async def astream_chat(
        self,
        user_input,
        session_id,
        working_directory=None,
    ):
        """Yield structured events for only the current agent turn."""

        config = self._config(session_id)
        old_message_ids = await self._message_ids(config)
        human_message = self._human_message(user_input, working_directory)
        produced_content = False
        generation_number = 0
        pending_tool_calls = {}

        try:
            async for event in self.agent.astream(
                {"messages": [human_message]},
                config,
                stream_mode="messages",
                version="v2",
            ):
                message = self._stream_message(event)
                if message is None:
                    continue

                chunk = text_content(message.content)
                if chunk:
                    produced_content = True
                    yield {
                        "type": "chunk",
                        "kind": "text",
                        "text": chunk,
                    }

                tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
                for raw_call in tool_call_chunks:
                    call = self._tool_call_delta(raw_call)
                    if call is None:
                        continue

                    call_key = f"generation-{generation_number}:{call['index']}"
                    pending = pending_tool_calls.setdefault(
                        call_key,
                        {
                            "index": call["index"],
                            "name": "",
                            "arguments": "",
                            "id": "",
                        },
                    )
                    pending["name"] += call["name"]
                    pending["arguments"] += call["arguments"]
                    if call["id"] and not pending["id"]:
                        pending["id"] = call["id"]
                    produced_content = True
                    yield {
                        "type": "chunk",
                        "kind": "tool_call",
                        "call_key": call_key,
                        "name_delta": call["name"],
                        "arguments_delta": call["arguments"],
                    }

                generation_finished = (
                    not isinstance(message, AIMessageChunk)
                    or getattr(message, "chunk_position", None) == "last"
                )
                if not generation_finished:
                    continue

                # Some non-streaming model adapters expose only complete
                # tool_calls rather than tool_call_chunks.
                for index, raw_call in enumerate(
                    getattr(message, "tool_calls", None) or []
                ):
                    call = self._tool_call_delta({**raw_call, "index": index})
                    if call is None:
                        continue
                    call_key = f"generation-{generation_number}:{call['index']}"
                    if call_key not in pending_tool_calls:
                        pending_tool_calls[call_key] = call
                        produced_content = True
                        yield {
                            "type": "chunk",
                            "kind": "tool_call",
                            "call_key": call_key,
                            "name_delta": call["name"],
                            "arguments_delta": call["arguments"],
                        }
                    else:
                        pending = pending_tool_calls[call_key]
                        if not pending["name"]:
                            pending["name"] = call["name"]
                        if not pending["id"]:
                            pending["id"] = call["id"]

                generation_prefix = f"generation-{generation_number}:"
                completed_calls = [
                    (call_key, call)
                    for call_key, call in pending_tool_calls.items()
                    if call_key.startswith(generation_prefix)
                ]
                completed_calls.sort(key=lambda item: item[1]["index"])
                for call_key, call in completed_calls:
                    yield {
                        "type": "tool_call_done",
                        "call_key": call_key,
                        "tool_call_id": call["id"] or call_key,
                        "name": call["name"] or "unknown_tool",
                        "status": "complete",
                    }
                    del pending_tool_calls[call_key]

                generation_number += 1

            # Fall back safely for adapters that omit chunk_position="last".
            for call_key, call in sorted(
                pending_tool_calls.items(),
                key=lambda item: (item[1]["index"], item[0]),
            ):
                yield {
                    "type": "tool_call_done",
                    "call_key": call_key,
                    "tool_call_id": call["id"] or call_key,
                    "name": call["name"] or "unknown_tool",
                    "status": "complete",
                }

            if not produced_content:
                raise AgentReturnedNoReplyError("agent_returned_no_reply")
        except BaseException:
            try:
                await self._rollback_messages(config, old_message_ids)
            except Exception:
                logger.exception("Unable to roll back failed agent stream")
            raise

    async def clearSession(self, session_id: str):
        if self.checkpointer is None:
            raise RuntimeError("Checkpointer 尚未初始化")

        await self.checkpointer.adelete_thread(session_id)

    async def clearAllSessions(self):
        if self.checkpointer is None:
            raise RuntimeError("Checkpointer 尚未初始化")

        thread_ids = set()

        async for saved_checkpoint in self.checkpointer.alist(None):
            thread_id = saved_checkpoint.config["configurable"]["thread_id"]
            thread_ids.add(thread_id)

        for thread_id in thread_ids:
            await self.checkpointer.adelete_thread(thread_id)

        return len(thread_ids)

    async def create_agent(self):
        base_url = os.environ.get("DEEPSEEK_BASE_URL")
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        model_name = os.environ["DEEPSEEK_MODEL_NAME"]

        # 创建模型
        self.model = init_chat_model(
            model=model_name,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
            # extra_body={"thinking": {"type": "disabled"}},
        ) # 使用的是openai的api: base_url + /chat/completions

        # self.model = ChatOllama(
        #     model="llama-3.1:latest",
        #     base_url="http://127.0.0.1:11434",
        # ) # 使用的是ollama的api: base_url + /api/chat

        # 创建checkpoint
        self.checkpointer = await postgreInit()

        # 创建agent
        try:
            self.agent = create_agent(
                model=self.model,
                tools=[
                    run_skill_script,
                    run_python,
                    run_node,
                    run_program,
                    read_skill_resource,
                    skill,
                    tavily_search_online
                ],
                middleware=[
                    dynamic_system_prompt,
                    DynamicMCPToolsMiddleware(self.mcp_client),
                ],
                checkpointer=self.checkpointer,
            )
            print("**** agent created ****")
        except Exception:
            await self.checkpointer.conn.close()
            self.checkpointer = None
            raise

'''
CustomAgent是用于处理model api的agent

定义：
    model
    checkpointer
    agent

流程：
    1.初始化成员为None
    2.__aenter__异步初始化 create_agent：
        初始化checkpointer，model和agent
    3.__aexit__异步回收
    
内部函数
    clearSession： 清空 agent 会话记录

接口：
    async def achat(self, user_input, session_id):
    async def astream_chat(self,user_input,session_id,working_directory=None,):
    
'''

# python -m uvicorn cli:app --reload
