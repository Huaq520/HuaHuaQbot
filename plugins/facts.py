# -*- coding: utf-8 -*-
"""长期事实记忆：和「最近 6 轮对话」分开，不会被滚动挤掉。

每人一份 data/facts/user_<QQ>.json，内容是若干条短句。
每次对话都会把这些事实拼进系统提示词。
"""

import json
import re
import threading
from pathlib import Path
from typing import List

_DIR = Path(__file__).resolve().parent.parent / "data" / "facts"
_lock = threading.Lock()
_SAFE = re.compile(r"[^0-9A-Za-z_-]")
MAX_FACTS = 30


def _path(uid: str) -> Path:
    return _DIR / f"user_{_SAFE.sub('_', str(uid))}.json"


def load(uid: str) -> List[str]:
    path = _path(uid)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(x) for x in data][:MAX_FACTS]
    except Exception:  # noqa: BLE001
        return []


def add(uid: str, text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    with _lock:
        items = load(uid)
        if text in items:
            return False
        items.append(text)
        items = items[-MAX_FACTS:]
        path = _path(uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    return True


def remove(uid: str, keyword: str) -> int:
    """按关键词删事实，返回删掉几条。"""
    keyword = keyword.strip()
    if not keyword:
        return 0
    with _lock:
        items = load(uid)
        keep = [x for x in items if keyword not in x]
        removed = len(items) - len(keep)
        if removed:
            path = _path(uid)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        return removed


def clear(uid: str) -> bool:
    path = _path(uid)
    if path.exists():
        path.unlink()
        return True
    return False
