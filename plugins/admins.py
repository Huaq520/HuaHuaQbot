# -*- coding: utf-8 -*-
"""机器人管理员名单：/op 授权，/deop 撤销。

存 data/admins.json。OWNER（.env 里的 SUPERUSERS）永远在名单里且撤不掉。
"""

import json
from pathlib import Path
from typing import List

from nonebot import get_driver

_FILE = Path(__file__).resolve().parent.parent / "data" / "admins.json"
_OWNERS = [int(u) for u in get_driver().config.superusers]
OWNER = _OWNERS[0] if _OWNERS else 0


def _load() -> List[int]:
    if not _FILE.exists():
        return list(_OWNERS)
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        items = {int(x) for x in data if str(x).isdigit()}
    except Exception:  # noqa: BLE001
        items = set()
    return sorted(items | set(_OWNERS))


def _save(items: List[int]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(sorted(items), indent=1), encoding="utf-8")


def all() -> List[int]:
    return _load()


def is_admin(uid: int) -> bool:
    return int(uid) in _load()


def add(uid: int) -> bool:
    items = _load()
    if uid in items:
        return False
    items.append(uid)
    _save(items)
    return True


def remove(uid: int) -> bool:
    if uid in _OWNERS:
        return False
    items = _load()
    if uid not in items:
        return False
    items.remove(uid)
    _save(items)
    return True
