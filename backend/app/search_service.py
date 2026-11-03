"""StepFun's independent /search API. Provider content is never treated as fetched evidence."""

import json
from urllib.parse import parse_qsl, urlencode, urlunsplit

import httpx

from .config import settings
from .pdf_processing import InvalidPDF
from .source_parsing import digest
from .web_import import validate_url


class SearchError(Exception):
    pass


def credential():
    s = settings()
    if s.search_api_key:
        return s.search_api_key
    if (
        s.search_reuse_stepfun_key
        and s.chat_base_url.rstrip("/") == "https://api.stepfun.com/v1"
        and s.search_base_url.rstrip("/") == "https://api.stepfun.com/v1"
    ):
        return s.chat_api_key
    return ""


def canonical_url(url):
    parsed, host, port = validate_url(url)
    pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in ("spm", "fbclid", "gclid")
    ]
    # Keep path and semantic query intact; no assumptions about trailing-slash equivalence.
    authority = f"[{host}]" if ":" in host else host
    return urlunsplit(
        (
            parsed.scheme.lower(),
            authority,
            parsed.path or "/",
            urlencode(sorted(pairs)),
            "",
        )
    )


def search(query):
    s = settings()
    key = credential()
    if not key:
        raise SearchError(
            "尚未配置搜索服务，请设置 SEARCH_API_KEY 或启用复用阶跃星辰密钥"
        )
    try:
        with httpx.Client(
            timeout=min(60, max(5, s.search_timeout_seconds)), follow_redirects=False
        ) as client:
            with client.stream(
                "POST",
                s.search_base_url.rstrip("/") + "/search",
                headers={"Authorization": "Bearer " + key},
                json={"query": query, "n": min(20, max(1, s.research_max_results))},
            ) as response:
                if response.status_code != 200:
                    raise SearchError(
                        f"搜索服务调用失败（HTTP {response.status_code}），请检查权限、余额或稍后重试"
                    )
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 4000000:
                        raise SearchError("搜索响应超过安全上限")
                data = json.loads(raw)
        if not isinstance(data.get("results"), list):
            raise SearchError("搜索服务返回格式无效")
        items, seen = [], set()
        for rank, item in enumerate(data["results"][:20], 1):
            try:
                url = canonical_url(item["url"])
            except (InvalidPDF, KeyError, TypeError, ValueError):
                continue
            identity = digest(url)
            if identity in seen:
                continue
            seen.add(identity)
            items.append(
                {
                    "url": url,
                    "url_hash": identity,
                    "title": str(item.get("title") or url)[:255],
                    "snippet": str(item.get("snippet") or "")[:4000],
                    "rank": rank,
                    # time is explicitly documented as INDEX time, never publication time.
                    "details": {
                        "provider": "stepfun",
                        "indexed_at": str(item.get("time") or "")[:100],
                        "published_at": None,
                    },
                }
            )
        return items, {
            "provider": "stepfun",
            "calls": 1,
            "returned": len(items),
            "provider_usage": data.get("usage")
            if isinstance(data.get("usage"), dict)
            else None,
        }
    except (httpx.HTTPError, ValueError, TypeError):
        raise SearchError(
            "搜索连接失败、超时或响应无效；结果未保存，可手动重试"
        ) from None
