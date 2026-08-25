from __future__ import annotations

from threading import RLock

from langchain.agents.middleware import ModelRequest, dynamic_prompt


DEFAULT_SYSTEM_PROMPT = "You are a useful assistant."


class SystemPromptStore:
    """Thread-safe, in-memory storage for the live system-prompt template."""

    def __init__(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT):
        self._lock = RLock()
        self._system_prompt = self._validate(system_prompt)

    @staticmethod
    def _validate(system_prompt: str) -> str:
        if not isinstance(system_prompt, str):
            raise TypeError("system_prompt must be a string")
        if not system_prompt.strip():
            raise ValueError("system_prompt must not be blank")
        return system_prompt

    def get(self) -> str:
        with self._lock:
            return self._system_prompt

    def update(self, system_prompt: str) -> str:
        validated_prompt = self._validate(system_prompt)
        with self._lock:
            self._system_prompt = validated_prompt
            return self._system_prompt

system_prompt_store = SystemPromptStore()


@dynamic_prompt
def dynamic_system_prompt(request: ModelRequest) -> str:
    """Build the current system prompt immediately before each model call."""

    return system_prompt_store.get()
