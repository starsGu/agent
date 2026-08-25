import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from agent import (
    AgentReturnedNoReplyError,
    CustomAgent,
    MCPToolDisconnectedError,
    system_prompt_store,
    text_content,
)
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from tool import McpClient
from tool import plugin as plugin_registry


logger = logging.getLogger(__name__)
directory_picker_lock = asyncio.Lock()


def _append_text_segment(segments: list[dict], text: str) -> None:
    if not text:
        return
    if segments and segments[-1].get("type") == "text":
        segments[-1]["text"] += text
        return
    segments.append({"type": "text", "text": text})


def _apply_stream_event(segments: list[dict], event: dict) -> None:
    if event.get("type") == "chunk" and event.get("kind") == "text":
        _append_text_segment(segments, event.get("text", ""))
        return

    if event.get("type") == "chunk" and event.get("kind") == "tool_call":
        call_key = event.get("call_key")
        segment = next(
            (
                current
                for current in segments
                if current.get("type") == "tool_call"
                and current.get("call_key") == call_key
            ),
            None,
        )
        if segment is None:
            segment = {
                "type": "tool_call",
                "call_key": call_key,
                "tool_call_id": "",
                "name": "",
                "arguments": "",
                "status": "streaming",
            }
            segments.append(segment)
        segment["name"] += event.get("name_delta", "")
        segment["arguments"] += event.get("arguments_delta", "")
        return

    if event.get("type") != "tool_call_done":
        return

    call_key = event.get("call_key")
    segment = next(
        (
            current
            for current in segments
            if current.get("type") == "tool_call"
            and current.get("call_key") == call_key
        ),
        None,
    )
    if segment is None:
        segment = {"type": "tool_call", "call_key": call_key}
        segments.append(segment)
    segment.update({
        "tool_call_id": event.get("tool_call_id") or call_key,
        "name": event.get("name") or segment.get("name") or "unknown_tool",
        "status": "complete",
    })


def _public_segments(segments: list[dict]) -> list[dict]:
    public_segments = []
    for segment in segments:
        if segment.get("type") == "text":
            _append_text_segment(public_segments, segment.get("text", ""))
        elif segment.get("type") == "tool_call":
            public_segments.append({
                "type": "tool_call",
                "tool_call_id": (
                    segment.get("tool_call_id")
                    or segment.get("call_key")
                    or "unknown_call"
                ),
                "name": segment.get("name") or "unknown_tool",
                "status": "complete",
            })
    return public_segments


def _append_ai_message_segments(segments: list[dict], message) -> None:
    _append_text_segment(segments, text_content(message.content))
    for index, tool_call in enumerate(getattr(message, "tool_calls", None) or []):
        if not isinstance(tool_call, dict):
            continue
        segments.append({
            "type": "tool_call",
            "tool_call_id": tool_call.get("id") or f"tool-call-{index}",
            "name": tool_call.get("name") or "unknown_tool",
            "status": "complete",
        })


def _latest_turn_segments(messages) -> list[dict]:
    last_human_index = -1
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "human":
            last_human_index = index

    segments = []
    for message in messages[last_human_index + 1:]:
        if getattr(message, "type", None) == "ai":
            _append_ai_message_segments(segments, message)
    return segments


def get_default_working_directory() -> str:
    return str(Path.home().resolve())


def validate_working_directory(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("working_directory must not be blank")

    requested_directory = Path(value)
    if not requested_directory.is_absolute():
        raise ValueError("working_directory must be an absolute path")

    try:
        resolved_directory = requested_directory.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("working_directory must exist") from exc

    if not resolved_directory.is_dir():
        raise ValueError("working_directory must be a directory")

    return str(resolved_directory)


def select_working_directory(initial_directory: str) -> str | None:
    """Open the native Windows folder picker on a worker thread."""

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected_directory = filedialog.askdirectory(
            parent=root,
            title="选择当前对话的工作目录",
            initialdir=initial_directory,
            mustexist=True,
        )
    finally:
        root.destroy()

    if not selected_directory:
        return None
    return validate_working_directory(selected_directory)

class CLI:
    def __init__(self):
        self.chatList = {}
        self.sessionList = []
        self.agent = None
        self.agentState = False
        self.running = True
        self.mcp_client = McpClient()
        self.mcp_task = None
        self._plugin_lock = asyncio.Lock()

    async def run(self):
        self.mcp_task = asyncio.create_task(self.mcp_client.run())
        try:
            async with CustomAgent(self.mcp_client) as custom_agent:
                self.agent = custom_agent
                await self.loadMemory()
                self.agentState = True

                while self.running:
                    await asyncio.sleep(0.05)
        finally:
            if self.mcp_task is not None:
                self.mcp_task.cancel()
                await asyncio.gather(self.mcp_task, return_exceptions=True)
                self.mcp_task = None

    def stop(self):
        self.running = False

    async def chat(
        self,
        text: str,
        session_id: str,
        working_directory: str | None = None,
    ):
        if self.agent is None:
            raise RuntimeError("请先调用 await service.start()")
        response = await self.agent.achat(
            text,
            session_id,
            working_directory or get_default_working_directory(),
        )
        ai_message = text_content(response["messages"][-1].content)
        if not ai_message:
            raise AgentReturnedNoReplyError("agent_returned_no_reply")
        ai_segments = _latest_turn_segments(response["messages"])

        if session_id not in self.chatList:
            self.chatList[session_id] = []

        if session_id not in self.sessionList:
            self.sessionList.append(session_id)

        self.chatList[session_id].append({
            "human_message": text,
            "ai_message": ai_segments,
        })
        return ai_message

    async def stream_chat(
        self,
        text: str,
        session_id: str,
        working_directory: str | None = None,
    ):
        if self.agent is None:
            raise RuntimeError("请先调用 await service.start()")

        segments = []
        async for event in self.agent.astream_chat(
            text,
            session_id,
            working_directory or get_default_working_directory(),
        ):
            _apply_stream_event(segments, event)
            yield event

        ai_message = _public_segments(segments)
        if not ai_message:
            raise AgentReturnedNoReplyError("agent_returned_no_reply")

        if session_id not in self.chatList:
            self.chatList[session_id] = []

        if session_id not in self.sessionList:
            self.sessionList.append(session_id)

        self.chatList[session_id].append({
            "human_message": text,
            "ai_message": ai_message,
        })
        yield {
            "type": "done",
            "session_id": session_id,
            "ai_message": ai_message,
        }

    def getDataOfSession(self, session_id: str):
        return self.chatList.get(session_id, [])

    def getSessions(self):
        return self.sessionList

    def getAgentState(self):
        return self.agentState

    def getPlugins(self):
        return {
            "plugins": list(plugin_registry.plugins),
            "use_plugins": dict(plugin_registry.use_plugins),
        }

    async def setPluginEnabled(self, name: str, enabled: bool):
        async with self._plugin_lock:
            if name not in plugin_registry.use_plugins:
                raise KeyError(name)
            plugin_registry.use_plugins[name] = enabled
            await self.mcp_client.get_all_mcp()
        return {"name": name, "enabled": enabled}

    async def loadMemory(self):
        self.chatList.clear()
        self.sessionList.clear()

        loaded_sessions = set()

        async for saved_checkpoint in self.agent.checkpointer.alist(None):
            session_id = saved_checkpoint.config["configurable"]["thread_id"]

            # alist 返回同一个会话的多个历史快照，
            # 只读取每个会话最新的 checkpoint
            if session_id in loaded_sessions:
                continue

            loaded_sessions.add(session_id)
            self.sessionList.append(session_id)
            self.chatList[session_id] = []

            messages = saved_checkpoint.checkpoint.get(
                "channel_values", {}
            ).get("messages", [])

            human_message = None
            ai_segments = []

            for message in messages:
                if message.type == "human":
                    human_message = message.content
                    ai_segments = []

                elif message.type == "ai" and human_message is not None:
                    _append_ai_message_segments(ai_segments, message)

                    # 有工具调用的 AIMessage 属于当前轮中间步骤，继续累计。
                    if getattr(message, "tool_calls", None):
                        continue

                    if not ai_segments:
                        human_message = None
                        ai_segments = []
                        continue

                    self.chatList[session_id].append({
                        "human_message": human_message,
                        "ai_message": ai_segments,
                    })

                    human_message = None
                    ai_segments = []

    async def clearSession(self, session_id: str | None = None):
        if self.agent is None:
            raise RuntimeError("Agent 尚未初始化")

        if session_id is not None:
            await self.agent.clearSession(session_id)
            await self.loadMemory()

            return {
                "status": "success",
                "deleted": session_id,
            }

        deleted_count = await self.agent.clearAllSessions()
        await self.loadMemory()

        return {
            "status": "success",
            "deleted": "all",
            "deleted_count": deleted_count,
        }

load_dotenv()
service = CLI()
serviceTask = None

class ChatRequest(BaseModel):
    human_message: str
    session_id: str
    working_directory: str | None = None

    @field_validator("working_directory")
    @classmethod
    def validate_directory(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_working_directory(value)


class WorkingDirectoryResponse(BaseModel):
    working_directory: str


class WorkingDirectorySelectionRequest(BaseModel):
    initial_directory: str | None = None


class WorkingDirectorySelectionResponse(BaseModel):
    cancelled: bool
    working_directory: str


class SystemPromptRequest(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=50_000)

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("system_prompt must not be blank")
        return value


class SystemPromptResponse(BaseModel):
    system_prompt: str


class PluginToggleRequest(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

@asynccontextmanager
async def lifespan(app: FastAPI):
    service_task = asyncio.create_task(service.run())
    try:
        yield
    finally:
        service.stop()
        await service_task

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        return await service.chat(
            text=request.human_message,
            session_id=request.session_id,
            working_directory=request.working_directory,
        )
    except MCPToolDisconnectedError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"MCP tool '{exc.tool_name}' disconnected; please retry",
        ) from exc
    except AgentReturnedNoReplyError as exc:
        raise HTTPException(
            status_code=502,
            detail="agent_returned_no_reply",
        ) from exc


def _ndjson(event: dict) -> bytes:
    return (
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


@app.post("/chat/stream")
async def chatStream(request: ChatRequest):
    if service.agent is None:
        raise HTTPException(status_code=503, detail="agent_unavailable")

    async def events():
        yield _ndjson({
            "type": "start",
            "session_id": request.session_id,
        })

        try:
            async for event in service.stream_chat(
                text=request.human_message,
                session_id=request.session_id,
                working_directory=request.working_directory,
            ):
                yield _ndjson(event)
        except asyncio.CancelledError:
            raise
        except MCPToolDisconnectedError as exc:
            yield _ndjson({
                "type": "error",
                "code": "mcp_tool_disconnected",
                "message": f"MCP 工具 {exc.tool_name} 已断开，请重试",
            })
        except AgentReturnedNoReplyError:
            yield _ndjson({
                "type": "error",
                "code": "agent_returned_no_reply",
                "message": "Agent 没有返回可显示的回复",
            })
        except Exception:
            logger.exception("Chat stream failed")
            yield _ndjson({
                "type": "error",
                "code": "agent_stream_failed",
                "message": "生成回复失败，请重试",
            })

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(
    "/working-directory/default",
    response_model=WorkingDirectoryResponse,
)
async def getDefaultWorkingDirectory():
    return WorkingDirectoryResponse(
        working_directory=get_default_working_directory(),
    )


@app.post(
    "/working-directory/select",
    response_model=WorkingDirectorySelectionResponse,
)
async def selectWorkingDirectory(request: WorkingDirectorySelectionRequest):
    initial_directory = get_default_working_directory()
    if request.initial_directory is not None:
        try:
            initial_directory = validate_working_directory(
                request.initial_directory,
            )
        except ValueError:
            pass

    try:
        async with directory_picker_lock:
            selected_directory = await asyncio.to_thread(
                select_working_directory,
                initial_directory,
            )
    except Exception as exc:
        logger.exception("Unable to open the working-directory picker")
        raise HTTPException(
            status_code=500,
            detail="working_directory_picker_failed",
        ) from exc

    return WorkingDirectorySelectionResponse(
        cancelled=selected_directory is None,
        working_directory=selected_directory or initial_directory,
    )


@app.get("/system-prompt", response_model=SystemPromptResponse)
async def getSystemPrompt():
    return SystemPromptResponse(system_prompt=system_prompt_store.get())


@app.post("/system-prompt", response_model=SystemPromptResponse)
async def updateSystemPrompt(request: SystemPromptRequest):
    return SystemPromptResponse(
        system_prompt=system_prompt_store.update(request.system_prompt),
    )


@app.get("/agent")
async def getDataOfSession(session_id: str):
    return service.getDataOfSession(session_id)

@app.get("/agentSessions")
async def getSession():
    return service.getSessions()

@app.get("/agentState")
async def getAgentStte():
    return service.getAgentState()


@app.get("/plugins")
async def getPlugins():
    return service.getPlugins()


async def _set_plugin_enabled(name: str, enabled: bool):
    try:
        return await service.setPluginEnabled(name, enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown plugin: {name}") from exc


@app.post("/plugins/enable")
async def enablePlugins(request: PluginToggleRequest):
    return await _set_plugin_enabled(request.name, True)


@app.post("/plugins/disable")
async def disablePlugins(request: PluginToggleRequest):
    return await _set_plugin_enabled(request.name, False)

@app.delete("/sessions")
async def clearSession(session_id: str | None = None):
    return await service.clearSession(session_id)
'''
cli 是一个类似claude cli的 cmd 后端 app，用于用户与agent的命令行交互

数据：
    对话列表，内含用户提问--AI回答的列表
        {
            "session_id1": [{
                "human_message": human_message（没有rag额外内容的）,
                "ai_message": ai_message,
            },...],
            "session_id2":[...],
            ...
        }
    会话列表，
        ["session_id1", "session_id2", ...]
    agent对象，以及agent状态
    http server

接口：
    /chat -d {human_message: Str, session_id: Int} 非流式发送，返回本轮最终AI文本
    /chat/stream 流式发送，返回本轮AI文本及工具调用事件
    /agent?session_id={session_id} 查询完整会话的结构化可见内容，不包括工具返回正文
    /agentSessions 查询会话列表
    /sessions?session_id={session_id} 删除agent指定会话的记忆,若没有指定，则删除全部

    
流程：
    1. 创建agent对象
    2. 前端的每一个post请求，事件循环调用agent得到ai_message, 数据保存到对话列表，会话列表，

# python -m uvicorn cli:app --reload
'''
