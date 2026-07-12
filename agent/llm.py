"""Provider-agnostic LLM client factory (Groq or Gemini via the OpenAI SDK)."""

from __future__ import annotations

from openai import AsyncOpenAI

from core.config import settings


def get_client() -> tuple[AsyncOpenAI, str, str]:
    """Return (client, model, light_model) for the configured provider."""
    if settings.AI_PROVIDER == "groq":
        client = AsyncOpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        return client, settings.GROQ_MODEL, settings.GROQ_LIGHT_MODEL

    client = AsyncOpenAI(
        api_key=settings.GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    return client, settings.GEMINI_MODEL, settings.GEMINI_LIGHT_MODEL


def get_enrichment_client() -> tuple[AsyncOpenAI, str, str]:
    """Return (client, model, light_model) for the configured provider."""
    client = AsyncOpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )
    return client, settings.GROQ_MODEL, settings.GROQ_LIGHT_MODEL

   