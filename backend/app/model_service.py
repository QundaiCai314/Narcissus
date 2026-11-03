"""One configurable OpenAI-compatible protocol, independent chat/embedding settings."""

import json
import hashlib
import math
import httpx
from .config import settings


class ModelError(Exception):
    pass


def embedding_signature():
    s = settings()
    endpoint = hashlib.sha256(s.embedding_base_url.rstrip("/").encode()).hexdigest()[
        :16
    ]
    return f"{endpoint}:{s.embedding_model}:{s.embedding_dimensions}"


def _embedding_request(texts):
    s = settings()
    if not s.embedding_api_key:
        raise ModelError("尚未配置资料理解服务，请联系管理员")
    payload = {"model": s.embedding_model, "input": texts, "encoding_format": "float"}
    if s.embedding_send_dimensions:
        payload["dimensions"] = s.embedding_dimensions
    return s, payload


def _parse_embeddings(data, count):
    try:
        rows = sorted(data["data"], key=lambda x: x["index"])
        if [x["index"] for x in rows] != list(range(count)):
            raise ValueError()
        vectors = [x["embedding"] for x in rows]
        if any(
            len(v) != settings().embedding_dimensions
            or not all(math.isfinite(float(n)) for n in v)
            or sum(float(n) ** 2 for n in v) == 0
            for v in vectors
        ):
            raise ValueError()
        return vectors, data.get("usage", {})
    except (KeyError, TypeError, ValueError):
        raise ModelError("资料理解服务返回了无效结果，请核对模型及向量维数") from None


def embed(texts):
    s, payload = _embedding_request(texts)
    try:
        with httpx.Client(timeout=s.model_timeout_seconds) as client:
            response = client.post(
                s.embedding_base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {s.embedding_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            return _parse_embeddings(response.json(), len(texts))
    except (httpx.HTTPError, ValueError):
        raise ModelError("资料理解服务暂时不可用，请稍后重试") from None


async def embed_query(text):
    s, payload = _embedding_request([text])
    try:
        async with httpx.AsyncClient(timeout=s.model_timeout_seconds) as client:
            response = await client.post(
                s.embedding_base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {s.embedding_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            vectors, usage = _parse_embeddings(response.json(), 1)
            return vectors[0], usage
    except (httpx.HTTPError, ValueError):
        raise ModelError("资料理解服务暂时不可用，请稍后重试") from None


async def chat_stream(messages, max_tokens=None, *, json_mode=False, reasoning_effort=""):
    s = settings()
    if not s.chat_api_key:
        raise ModelError("尚未配置问答服务，请联系管理员")
    payload = {
        "model": s.chat_model,
        "messages": messages,
        "temperature": s.chat_temperature,
        "max_tokens": max_tokens or s.chat_max_tokens,
        "stream": True,
    }
    if s.chat_send_usage:
        payload["stream_options"] = {"include_usage": True}
    # Opt in per caller/provider: compatible endpoints need not support these fields.
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(s.model_timeout_seconds, connect=10)
        ) as client:
            async with client.stream(
                "POST",
                s.chat_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {s.chat_api_key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                finished = False
                finish_error = None
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        finished = True
                        break
                    data = json.loads(raw)
                    if data.get("error"):
                        raise ModelError("问答服务返回错误，请重试")
                    if data.get("usage"):
                        yield {"usage": data["usage"]}
                    for choice in data.get("choices", []):
                        reason = choice.get("finish_reason")
                        if reason == "length":
                            finish_error = "回答达到生成长度上限，请缩小回答范围后重试"
                        elif reason == "content_filter":
                            finish_error = "模型服务未能提供该回答，请调整问题后重试"
                        content = choice.get("delta", {}).get("content")
                        if isinstance(content, str):
                            yield {"text": content}
                if not finished:
                    raise ModelError("回答连接意外中断，请重试")
                if finish_error:
                    raise ModelError(finish_error)
    except (httpx.HTTPError, ValueError):
        raise ModelError("问答服务连接失败或超时，请稍后重试") from None
