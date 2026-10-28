# -*- coding: utf-8 -*-
"""联网：用 DeepSeek 官方的 Search / Fetch 接口。

POST /v1/tools/search  搜索网页 返回标题 摘要 链接
POST /v1/tools/fetch   抓单个网页 返回 Markdown
两者都用同一个 API Key。
"""

from typing import Any, Dict, List

import httpx
from nonebot import get_driver

_config = get_driver().config
API_KEY = getattr(_config, "deepseek_api_key", "")
BASE = "https://api.deepseek.com/v1/tools"

_HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


async def search(query: str, count: int = 5) -> str:
    payload = {"query": query, "count": max(1, min(10, count))}
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(f"{BASE}/search", headers=_HEADERS, json=payload)
        resp.raise_for_status()
        data = resp.json()

    results: List[Dict[str, Any]] = data.get("results") or []
    if not results:
        return "没搜到结果"

    lines = []
    for i, r in enumerate(results, 1):
        summary = (r.get("summary") or "").replace("\n", " ").strip()
        lines.append(f"{i}. {r.get('title', '')}\n{summary[:220]}\n{r.get('url', '')}")
    return "\n".join(lines)


async def fetch(url: str, limit: int = 4000) -> str:
    if not url.startswith("http"):
        return "链接不对"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{BASE}/fetch", headers=_HEADERS, json={"url": url})
        resp.raise_for_status()
        data = resp.json()
    content = str(data.get("content") or "").strip()
    return content[:limit] if content else "页面没内容"
