# -*- coding: utf-8 -*-
"""会话级人格覆盖：某个群或某个人单独用一套人格，不影响全局。

键：group:<群号> 或 user:<QQ>
存 data/persona_sessions.json
"""

import json
from pathlib import Path
from typing import Optional

_FILE = Path(__file__).resolve().parent.parent / "data" / "persona_sessions.json"


def _load() -> dict:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return _load().get(key)


def set_persona(key: str, name: str) -> None:
    data = _load()
    data[key] = name
    _save(data)


def clear(key: str) -> bool:
    data = _load()
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def all_overrides() -> dict:
    return _load()
