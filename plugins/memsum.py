# -*- coding: utf-8 -*-
"""记忆压缩：聊得久了把旧对话提炼成要点，避免越记越多。

每个会话一份 data/memory_summary/user_<QQ>.json 或 group_<群号>.json
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent.parent / "data" / "memory_summary"
_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def _path(key: str) -> Path:
    return _DIR / f"{_SAFE.sub('_', key)}.json"


def load(key: str) -> str:
    path = _path(key)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("summary") or "")
    except Exception:  # noqa: BLE001
        return ""


def save(key: str, summary: str) -> None:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"summary": summary, "updated": int(time.time())}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(path)


def clear(key: str) -> bool:
    path = _path(key)
    if path.exists():
        path.unlink()
        return True
    return False


def get_any(key: str) -> Optional[str]:
    text = load(key)
    return text or None
