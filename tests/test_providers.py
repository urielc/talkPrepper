"""Provider tests against a fake Ollama HTTP server (Ollama is not installed here)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from server.ai.base import ToolResult, ToolSpec
from server.ai.ollama_provider import OllamaProvider

TOOLS = [ToolSpec("search_talks", "search", {"type": "object", "properties": {"query": {"type": "string"}}})]


class FakeOllama(BaseHTTPRequestHandler):
    """First /api/chat call returns a tool call; the second streams a final answer.
    When the request model is 'notools', return Ollama's no-tool-support error."""
    calls: list[dict] = []

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": "llama3.1:8b"}, {"name": "notools:latest"}]})
        else:
            self._json(404, {"error": "nope"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.calls.append(body)
        if body["model"] == "notools" and "tools" in body:
            self._json(400, {"error": "registry.ollama.ai/library/notools does not support tools"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        has_tool_msgs = any(m["role"] == "tool" for m in body["messages"])
        if "tools" in body and not has_tool_msgs:
            chunks = [
                {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "search_talks", "arguments": {"query": "faith"}}}]}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ]
        else:
            chunks = [
                {"message": {"role": "assistant", "content": "Here is "}, "done": False},
                {"message": {"role": "assistant", "content": "the answer."}, "done": True},
            ]
        for c in chunks:
            self.wfile.write((json.dumps(c) + "\n").encode())
        self.wfile.flush()

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def fake_server():
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def executor(name, args):
    return ToolResult(f"result of {name}({args})", [{"type": "talk", "id": "2024-10/x", "title": "X"}], f"ran {name}")


def test_ollama_tool_loop(fake_server):
    FakeOllama.calls.clear()
    p = OllamaProvider(fake_server, "llama3.1:8b")
    assert p.ping()["model"] == "llama3.1:8b"
    events = list(p.stream("SYSTEM", [], "question", TOOLS, executor))
    types = [e.type for e in events]
    assert types[:2] == ["tool_call", "tool_result"]
    assert "".join(e.data["text"] for e in events if e.type == "text_delta") == "Here is the answer."
    assert types[-1] == "info"
    # second request carried the tool result back
    assert any(m["role"] == "tool" for m in FakeOllama.calls[1]["messages"])


def test_ollama_no_tool_support_falls_back(fake_server):
    FakeOllama.calls.clear()
    p = OllamaProvider(fake_server, "notools")
    events = list(p.stream("SYSTEM", [], "question", TOOLS, executor))
    kinds = [e.type for e in events]
    assert "tool_result" in kinds                      # RAG fallback ran search_talks
    assert "".join(e.data["text"] for e in events if e.type == "text_delta") == "Here is the answer."
    # fallback injected search results into the system prompt and dropped tools
    last = FakeOllama.calls[-1]
    assert "tools" not in last
    assert "SEARCH RESULTS" in last["messages"][0]["content"]


def test_ollama_ping_unknown_model(fake_server):
    from server.ai.base import ProviderError
    with pytest.raises(ProviderError):
        OllamaProvider(fake_server, "missing-model").ping()


def test_anthropic_provider_requires_key():
    from server.ai import get_provider
    from server.ai.base import ProviderError
    with pytest.raises(ProviderError):
        get_provider({"ai_provider": "anthropic", "anthropic_api_key": ""})
    p = get_provider({"ai_provider": "anthropic", "anthropic_api_key": "sk-test", "anthropic_model": "claude-opus-5"})
    assert p.name == "anthropic" and p.model == "claude-opus-5"
