"""Provider-neutral chat interface.

A provider turns (system prompt, prior messages, user message, tools) into a
stream of ``ChatEvent`` objects. Tool calls are executed by the provider via
the supplied executor so tool progress can be streamed to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolResult:
    text: str                      # what the model sees
    refs: list[dict] = field(default_factory=list)   # {type, id/ref, title...} for the UI
    summary: str = ""              # one-line description for the UI


ToolExecutor = Callable[[str, dict], ToolResult]


@dataclass
class ChatEvent:
    type: str          # text_delta | tool_call | tool_result | done | error | info
    data: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class Provider:
    name = "base"
    model = ""
    supports_tools = True

    def stream(self, system: str, history: list[dict], user_message: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> Iterator[ChatEvent]:
        raise NotImplementedError

    def ping(self) -> dict[str, Any]:
        """Cheap connectivity/authentication check. Returns info for the UI."""
        raise NotImplementedError

    def generate_json(self, system: str, user_message: str, schema: dict) -> dict:
        """One-shot structured generation: returns a dict matching ``schema``."""
        raise NotImplementedError
