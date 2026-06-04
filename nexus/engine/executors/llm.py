"""Helpers for workflow node executors that need LLM clients."""

from __future__ import annotations

import os
from typing import Any

from nexus.agent.llm_client import LLMClient
from nexus.config import settings


def create_llm_client(llm_settings: dict[str, Any] | None = None) -> LLMClient:
    """Create an LLM client using provider direct credentials when available."""
    llm_settings = llm_settings or {}
    provider = llm_settings.get("provider", settings.DEFAULT_LLM_PROVIDER)

    if provider in settings.PROVIDER_CONFIGS:
        direct_url, env_key = settings.PROVIDER_CONFIGS[provider]
        api_key = os.environ.get(env_key)
        if api_key:
            base_url = direct_url
        else:
            base_url = settings.LITELLM_PROXY_URL
            api_key = settings.LITELLM_API_KEY
    else:
        base_url = settings.LITELLM_PROXY_URL
        api_key = settings.LITELLM_API_KEY

    return LLMClient(proxy_url=base_url, api_key=api_key)
