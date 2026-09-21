"""AI provider factory."""

from __future__ import annotations

from ..config import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OLLAMA_URL
from .base import Provider, ProviderError


def get_provider(settings: dict) -> Provider:
    kind = (settings.get("ai_provider") or "anthropic").lower()
    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider
        key = settings.get("anthropic_api_key") or ""
        if not key:
            raise ProviderError("No Anthropic API key. Add one in Settings → AI.")
        return AnthropicProvider(api_key=key, model=settings.get("anthropic_model") or DEFAULT_ANTHROPIC_MODEL)
    if kind == "ollama":
        from .ollama_provider import OllamaProvider
        model = settings.get("ollama_model") or ""
        if not model:
            raise ProviderError("No Ollama model selected. Choose one in Settings → AI.")
        return OllamaProvider(base_url=settings.get("ollama_base_url") or DEFAULT_OLLAMA_URL,
                              model=model)
    raise ProviderError(f"Unknown AI provider {kind!r}")
