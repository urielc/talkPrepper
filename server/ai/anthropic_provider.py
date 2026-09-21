"""Claude via the official Anthropic SDK.

Streams text deltas and runs a manual tool loop so tool progress can be
forwarded to the UI as it happens. The talk text lives in the system prompt
with a cache breakpoint, so follow-up questions in a session reuse the cache.
Server-side refusal fallbacks are requested by default; if the account or SDK
does not support the parameter the request is retried without it.
"""

from __future__ import annotations

import json
from typing import Iterator

import anthropic

from ..config import DEFAULT_ANTHROPIC_MODEL
from .base import ChatEvent, Provider, ProviderError, ToolExecutor, ToolSpec

MAX_TOOL_ROUNDS = 8
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_ANTHROPIC_MODEL):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self._use_fallbacks = True

    # ------------------------------------------------------------ helpers

    def _thinking_kwargs(self) -> dict:
        # Haiku 4.5 still uses the budget form; adaptive thinking is for the 4.6+ family.
        if self.model.startswith("claude-haiku"):
            return {}
        return {"thinking": {"type": "adaptive"}}

    def _request(self, system: str, messages: list[dict], tools: list[dict]):
        kwargs = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
            **self._thinking_kwargs(),
        )
        if self._use_fallbacks:
            return self.client.beta.messages.stream(
                betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"}, **kwargs)
        return self.client.messages.stream(**kwargs)

    # ------------------------------------------------------------ API

    def ping(self) -> dict:
        try:
            m = self.client.models.retrieve(self.model)
        except anthropic.AuthenticationError:
            raise ProviderError("Anthropic rejected the API key.")
        except anthropic.NotFoundError:
            raise ProviderError(f"Unknown model {self.model!r}.")
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Could not reach the Anthropic API: {e}")
        return {"provider": "anthropic", "model": m.id, "display_name": getattr(m, "display_name", m.id)}

    def generate_json(self, system: str, user_message: str, schema: dict) -> dict:
        kwargs = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            **self._thinking_kwargs(),
        )
        try:
            if self._use_fallbacks:
                try:
                    resp = self.client.beta.messages.create(
                        betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"}, **kwargs)
                except anthropic.BadRequestError as e:
                    if "fallback" not in str(e).lower():
                        raise
                    self._use_fallbacks = False
                    resp = self.client.messages.create(**kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise ProviderError("Anthropic rejected the API key. Check Settings → AI.")
        except anthropic.RateLimitError:
            raise ProviderError("Rate limited by the Anthropic API. Try again in a moment.")
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Could not reach the Anthropic API: {e}")
        if resp.stop_reason == "refusal":
            raise ProviderError("The model declined to generate this digest.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except ValueError:
            raise ProviderError("The model returned malformed JSON for the digest.")

    def stream(self, system: str, history: list[dict], user_message: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> Iterator[ChatEvent]:
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                     for t in tools]
        messages: list[dict] = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": user_message})

        for _round in range(MAX_TOOL_ROUNDS + 1):
            try:
                final = yield from self._stream_once(system, messages, tool_defs)
            except anthropic.BadRequestError as e:
                if self._use_fallbacks and "fallback" in str(e).lower():
                    self._use_fallbacks = False
                    final = yield from self._stream_once(system, messages, tool_defs)
                else:
                    yield ChatEvent("error", {"message": f"Bad request: {e.message}"})
                    return
            except anthropic.AuthenticationError:
                yield ChatEvent("error", {"message": "Anthropic rejected the API key. Check Settings → AI."})
                return
            except anthropic.RateLimitError:
                yield ChatEvent("error", {"message": "Rate limited by the Anthropic API. Try again in a moment."})
                return
            except anthropic.APIStatusError as e:
                yield ChatEvent("error", {"message": f"Anthropic API error {e.status_code}: {e.message}"})
                return
            except anthropic.APIConnectionError as e:
                yield ChatEvent("error", {"message": f"Could not reach the Anthropic API: {e}"})
                return

            if final.stop_reason == "refusal":
                detail = getattr(final, "stop_details", None)
                why = getattr(detail, "explanation", None) if detail else None
                yield ChatEvent("error", {"message": "The model declined to answer this request."
                                          + (f" ({why})" if why else "")})
                return
            if final.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": final.content})
                continue
            if final.stop_reason != "tool_use":
                usage = final.usage
                yield ChatEvent("info", {"usage": {
                    "input": usage.input_tokens, "output": usage.output_tokens,
                    "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                    "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                }, "model": final.model})
                return

            # Execute every tool call, then send all results back in one user turn.
            messages.append({"role": "assistant", "content": final.content})
            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                args = block.input if isinstance(block.input, dict) else json.loads(block.input or "{}")
                yield ChatEvent("tool_call", {"id": block.id, "name": block.name, "input": args})
                res = execute(block.name, args)
                yield ChatEvent("tool_result", {"id": block.id, "name": block.name, "summary": res.summary,
                                                "refs": res.refs, "preview": res.text[:600]})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": res.text})
            messages.append({"role": "user", "content": results})

        yield ChatEvent("error", {"message": "Stopped after too many tool calls."})

    def _stream_once(self, system: str, messages: list[dict], tool_defs: list[dict]):
        with self._request(system, messages, tool_defs) as stream:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield ChatEvent("text_delta", {"text": event.delta.text})
            return stream.get_final_message()
