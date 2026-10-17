"""Shared LLM routing; changing LLM.PROVIDER switches all language tasks."""

from openai import OpenAI
import time
from config import LLM


INTENT_TYPES = [
    "chat", "local.time", "system.shutdown", "robot.move", "audio.volume",
    "device.status", "web.search", "music.play", "music.stop", "music.pause",
    "music.resume", "music.next", "music.previous", "music.genres",
]
INTENT_SCHEMA = {
    "type": "object", "properties": {
        "type": {"type": "string", "enum": INTENT_TYPES},
        "query": {"type": "string"},
    }, "required": ["type", "query"], "additionalProperties": False,
}
WEB_PLAN_SCHEMA = {
    "type": "object", "properties": {
        "source": {"type": "string", "enum": ["weather", "news", "web"]},
        "query": {"type": "string"}, "city": {"type": "string"},
        "day": {"type": "string", "enum": ["today", "tomorrow", "day_after_tomorrow"]},
    }, "required": ["source", "query", "city", "day"], "additionalProperties": False,
}


def is_local():
    provider = LLM["PROVIDER"]
    if provider not in ("qwen", "openai"):
        raise ValueError(f"Unsupported LLM provider: {provider}")
    return provider == "qwen"


def create_client():
    if is_local():
        return OpenAI(
            base_url=LLM["BASE_URL"], api_key="local-qwen",
            timeout=LLM["TIMEOUT_SECONDS"], max_retries=0,
        )
    return OpenAI()


def complete(client, model, messages, temperature=0.2, schema=None, max_tokens=None):
    options = {"model": model, "messages": messages, "temperature": temperature}
    if is_local():
        options.update(
            model=LLM["MODEL"], max_tokens=LLM["MAX_TOKENS"],
            temperature=LLM["TEMPERATURE"] if temperature else 0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False},
                        "top_k": 20, "min_p": 0},
            top_p=0.8,
        )
        if schema:
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            }
    elif schema:
        options["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        options["max_tokens"] = min(max_tokens, LLM["MAX_TOKENS"]) if is_local() else max_tokens
    # Deliberately no automatic fallback to a remote provider.
    started = time.monotonic()
    try:
        return client.chat.completions.create(**options)
    finally:
        print(f"TIMING: llm model={options['model']} json={bool(schema)} "
              f"{time.monotonic() - started:.2f}s", flush=True)
