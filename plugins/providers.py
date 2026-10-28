# -*- coding: utf-8 -*-
"""大模型供应商清单：DeepSeek / GPT / 其他 OpenAI 兼容接口。

存 data/providers.json，每项 {name, base, key}
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from . import modellist

_FILE = Path(__file__).resolve().parent.parent / "data" / "providers.json"

DEFAULT = [
    {"name": "DeepSeek", "base": "https://api.deepseek.com/v1", "key": ""},
    {"name": "GPT", "base": "https://misaka.tsham.cn/v1", "key": ""},
]


def _load() -> List[Dict]:
    if not _FILE.exists():
        return [dict(p) for p in DEFAULT]
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) and data else [dict(p) for p in DEFAULT]
    except Exception:  # noqa: BLE001
        return [dict(p) for p in DEFAULT]


def _save(items: List[Dict]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def all() -> List[Dict]:
    return _load()


def get(name: str) -> Optional[Dict]:
    return next((p for p in _load() if p["name"] == name), None)


def upsert(name: str, base: str, key: str = "") -> Dict:
    items = _load()
    for p in items:
        if p["name"] == name:
            p["base"] = base
            if key:
                p["key"] = key
            _save(items)
            return p
    item = {"name": name, "base": base, "key": key}
    items.append(item)
    _save(items)
    return item


def match_base(base: str) -> Optional[Dict]:
    base = base.rstrip("/")
    for p in _load():
        if p["base"].rstrip("/") == base:
            return p
    return None


def _pick(models: List[str], prefer: str = "") -> str:
    if prefer and prefer in models:
        return prefer
    for m in models:
        if "flash" in m or "mini" in m:
            return m
    return min(models, key=len) if models else ""


async def _balance(base: str, key: str) -> str:
    root = base[:-3] if base.endswith("/v1") else base
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.get(f"{root}/user/balance", headers=headers)
            if r.status_code == 200:
                info = (r.json().get("balance_infos") or [{}])[0]
                return f"{info.get('total_balance')} {info.get('currency')}"
        except Exception:  # noqa: BLE001
            pass
        try:
            r = await client.get(f"{base}/usage", headers=headers)
            if r.status_code == 200:
                d = r.json()
                return f"{round(float(d.get('balance', 0)), 2)} {d.get('unit', '')}".strip()
        except Exception:  # noqa: BLE001
            pass
    return "余额?"


_HEALTH_CACHE: Dict[str, tuple] = {}
_HEALTH_TTL = 120


async def health(p: Dict, prefer_model: str = "") -> Tuple[Optional[int], str]:
    """返回 (首字节毫秒, 余额文本)，结果缓存 2 分钟。"""
    base = p["base"].rstrip("/")
    cached = _HEALTH_CACHE.get(base)
    if cached and time.time() - cached[0] < _HEALTH_TTL:
        return cached[1], cached[2]
    key = p.get("key") or ""
    names = await modellist.cached_models(base, key) or []
    model = _pick(names, prefer_model)
    ms = await modellist._probe(base, key, model) if model else None
    bal = await _balance(base, key)
    _HEALTH_CACHE[base] = (time.time(), ms, bal)
    return ms, bal
