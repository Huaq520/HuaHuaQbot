# -*- coding: utf-8 -*-
"""对话记忆的本地存储。

每个会话（群 或 用户）一个 JSON 文件，放在 data/memory/ 下。
只保留最近若干轮，写入用临时文件替换，避免半截文件。
"""

import json
import re
import threading
from pathlib import Path
from typing import Dict, List

_DIR = Path(__file__).resolve().parent.parent / "data" / "memory"
_lock = threading.Lock()

_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def _path(key: str) -> Path:
    name = _SAFE.sub("_", key)
    return _DIR / f"{name}.json"


def load(key: str) -> List[Dict[str, str]]:
    path = _path(key)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict) and "role" in m and "content" in m]


def save(key: str, messages: List[Dict[str, str]]) -> None:
    path = _path(key)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)


def clear(key: str) -> bool:
    path = _path(key)
    if path.exists():
        path.unlink()
        return True
    return False


def list_files() -> List[str]:
    if not _DIR.exists():
        return []
    return sorted(p.stem for p in _DIR.glob("*.json"))
