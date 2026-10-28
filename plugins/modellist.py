# -*- coding: utf-8 -*-
"""模型列表与测速：给 /模型 提供可选项和延迟，结果缓存 10 分钟。"""

import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

CACHE = Path(__file__).resolve().parent.parent / "data" / "latency.json"
TTL = 600


def _load() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save(data: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


async def models(base: str, key: str) -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
        return [str(m.get("id")) for m in data.get("data", []) if m.get("id")]
    except Exception:  # noqa: BLE001
        return []


async def cached_models(base: str, key: str, ttl: int = 3600) -> List[str]:
    cache = _load()
    entry = cache.get("_models", {}).get(base)
    if entry and time.time() - entry.get("ts", 0) < ttl and entry.get("list"):
        return entry["list"]
    names = await models(base, key)
    if names:
        cache.setdefault("_models", {})[base] = {"ts": time.time(), "list": names}
        _save(cache)
    return names or (entry or {}).get("list", [])


async def _probe(base: str, key: str, model: str, timeout: float = 15.0) -> Optional[int]:
    """测首字节时间：连上并且模型开始吐字就算，不等它说完。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": True,
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            ) as resp:
                if resp.status_code >= 500:
                    return None
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        return int((time.monotonic() - start) * 1000)
        return None
    except Exception:  # noqa: BLE001
        return None


async def speeds(base: str, key: str, names: List[str]) -> Dict[str, Optional[int]]:
    cache = _load()
    entry = cache.get(base, {})
    now = time.time()
    need = [n for n in names if now - entry.get(n, {}).get("ts", 0) > TTL]

    if need:
        sem = asyncio.Semaphore(2)

        async def one(name: str):
            async with sem:
                return await _probe(base, key, name)

        results = await asyncio.gather(*(one(n) for n in need))
        for name, ms in zip(need, results):
            entry[name] = {"ms": ms, "ts": now}
        cache[base] = entry
        _save(cache)

    return {n: entry.get(n, {}).get("ms") for n in names}
