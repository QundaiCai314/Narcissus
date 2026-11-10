"""Verify legacy and reasoning-model payloads through the actual SSE client."""
import asyncio
import json

import httpx
import pytest

from app import model_service
from app.config import Settings


@pytest.mark.parametrize("reasoning", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_chat_protocol(monkeypatch, reasoning, override):
    config = Settings(_env_file=None, chat_api_key="test-not-a-real-key")
    if reasoning:
        config.chat_model = "gpt-5.6-luna"
        config.chat_max_tokens_parameter = "max_completion_tokens"
        config.chat_send_temperature = False
        config.chat_reasoning_effort = "low"
    monkeypatch.setattr(model_service, "settings", lambda: config)
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=(
            b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
            b'data: {"choices":[],"usage":{"total_tokens":12}}\n\n'
            b'data: [DONE]\n\n'
        ))

    client = httpx.AsyncClient
    monkeypatch.setattr(model_service.httpx, "AsyncClient", lambda **kw: client(
        transport=httpx.MockTransport(respond), **kw
    ))

    async def run():
        options = {"max_tokens": 2048, "reasoning_effort": "high", "json_mode": True} if override else {}
        return [part async for part in model_service.chat_stream(
            [{"role": "user", "content": "Question"}], **options
        )]

    assert asyncio.run(run()) == [{"text": "answer"}, {"usage": {"total_tokens": 12}}]
    payload = requests[0]
    assert payload[config.chat_max_tokens_parameter] == (2048 if override else 8192)
    assert ("max_tokens" in payload) != ("max_completion_tokens" in payload)
    assert ("temperature" in payload) is (not reasoning)
    assert payload.get("reasoning_effort") == ("high" if override else "low" if reasoning else None)
    assert ("response_format" in payload) is override
    assert payload["stream_options"] == {"include_usage": True}
