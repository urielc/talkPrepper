"""Local models via Ollama's HTTP API.

Uses ``/api/chat`` with streaming. If the model supports tool calling the same
tool loop as the Anthropic provider runs; if Ollama reports that the model does
not support tools, the provider falls back to retrieve-then-answer: it runs the
``search_talks`` tool itself on the user's question and injects the results.
"""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from .base import ChatEvent, Provider, ProviderError, ToolExecutor, ToolSpec

MAX_TOOL_ROUNDS = 6


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._tools_supported: bool | None = None

    def ping(self) -> dict:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
        except Exception as e:
            raise ProviderError(f"Could not reach Ollama at {self.base_url}: {e}")
        names = [m["name"] for m in r.json().get("models", [])]
        if self.model not in names and f"{self.model}:latest" not in names:
            raise ProviderError(f"Model {self.model!r} is not pulled. Available: {', '.join(names) or 'none'}")
        return {"provider": "ollama", "model": self.model}

    def generate_json(self, system: str, user_message: str, schema: dict) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_message}],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.3},
        }
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=httpx.Timeout(600, connect=10))
        except httpx.HTTPError as e:
            raise ProviderError(f"Ollama request failed: {e}")
        if r.status_code >= 400:
            raise ProviderError(f"Ollama error {r.status_code}: {r.text[:300]}")
        content = (r.json().get("message") or {}).get("content", "")
        try:
            return json.loads(content)
        except ValueError:
            raise ProviderError("The model returned malformed JSON for the digest.")

    def stream(self, system: str, history: list[dict], user_message: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> Iterator[ChatEvent]:
        tool_defs = [{"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        messages = [{"role": "system", "content": system}]
        messages += [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": user_message})

        use_tools = self._tools_supported is not False
        for _round in range(MAX_TOOL_ROUNDS + 1):
            try:
                msg = yield from self._stream_once(messages, tool_defs if use_tools else None)
            except _NoToolSupport:
                self._tools_supported = False
                use_tools = False
                yield ChatEvent("info", {"note": "This model does not support tools; answering from a search of the talks instead."})
                res = execute("search_talks", {"query": user_message, "mode": "hybrid", "limit": 8})
                yield ChatEvent("tool_result", {"id": "rag", "name": "search_talks", "summary": res.summary,
                                                "refs": res.refs, "preview": res.text[:600]})
                messages[0] = {"role": "system", "content": system + "\n\n--- SEARCH RESULTS FOR THIS QUESTION ---\n" + res.text}
                continue
            except httpx.HTTPError as e:
                yield ChatEvent("error", {"message": f"Ollama request failed: {e}"})
                return
            except ProviderError as e:
                yield ChatEvent("error", {"message": str(e)})
                return

            calls = msg.get("tool_calls") or []
            if not calls:
                yield ChatEvent("info", {"model": self.model})
                return
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for i, call in enumerate(calls):
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                cid = f"ollama-{_round}-{i}"
                yield ChatEvent("tool_call", {"id": cid, "name": name, "input": args})
                res = execute(name, args)
                yield ChatEvent("tool_result", {"id": cid, "name": name, "summary": res.summary,
                                                "refs": res.refs, "preview": res.text[:600]})
                messages.append({"role": "tool", "content": res.text, "tool_name": name})
        yield ChatEvent("error", {"message": "Stopped after too many tool calls."})

    def _stream_once(self, messages: list[dict], tool_defs: list[dict] | None):
        payload: dict = {"model": self.model, "messages": messages, "stream": True}
        if tool_defs:
            payload["tools"] = tool_defs
        content_parts: list[str] = []
        tool_calls: list[dict] = []
        with httpx.stream("POST", f"{self.base_url}/api/chat", json=payload, timeout=httpx.Timeout(300, connect=10)) as r:
            if r.status_code >= 400:
                body = r.read().decode("utf-8", "replace")
                if "does not support tools" in body:
                    raise _NoToolSupport()
                raise ProviderError(f"Ollama error {r.status_code}: {body[:300]}")
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                if "error" in chunk:
                    if "does not support tools" in chunk["error"]:
                        raise _NoToolSupport()
                    raise ProviderError(f"Ollama error: {chunk['error']}")
                m = chunk.get("message") or {}
                if m.get("content"):
                    content_parts.append(m["content"])
                    yield ChatEvent("text_delta", {"text": m["content"]})
                if m.get("tool_calls"):
                    tool_calls.extend(m["tool_calls"])
                if chunk.get("done"):
                    break
        return {"content": "".join(content_parts), "tool_calls": tool_calls}


class _NoToolSupport(Exception):
    pass
