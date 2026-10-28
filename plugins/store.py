# -*- coding: utf-8 -*-
"""白名单 / 黑名单存储：JSON 文件为唯一数据源，改完即时生效。"""

import json
import threading
from pathlib import Path
from typing import Set

from nonebot import get_driver

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_WL = _DATA_DIR / "whitelist.json"
_BL = _DATA_DIR / "blacklist.json"
_lock = threading.Lock()


def _read(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return dict(default)
    data.setdefault("groups", [])
    data.setdefault("users", [])
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------- 白名单 ----------
def snapshot() -> dict:
    return _read(_WL, {"groups": [], "users": []})


def groups() -> Set[int]:
    return {int(g) for g in snapshot()["groups"]}


def users() -> Set[int]:
    return {int(u) for u in snapshot()["users"]}


def add_group(gid: int) -> bool:
    with _lock:
        data = snapshot()
        if gid in data["groups"]:
            return False
        data["groups"] = sorted({*data["groups"], gid})
        _write(_WL, data)
        return True


def remove_group(gid: int) -> bool:
    with _lock:
        data = snapshot()
        if gid not in data["groups"]:
            return False
        data["groups"] = [g for g in data["groups"] if g != gid]
        _write(_WL, data)
        return True


def add_user(uid: int) -> bool:
    with _lock:
        data = snapshot()
        if uid in data["users"]:
            return False
        data["users"] = sorted({*data["users"], uid})
        _write(_WL, data)
        return True


def remove_user(uid: int) -> bool:
    with _lock:
        data = snapshot()
        if uid not in data["users"]:
            return False
        data["users"] = [u for u in data["users"] if u != uid]
        _write(_WL, data)
        return True


# ---------- 黑名单 ----------
def black_snapshot() -> dict:
    return _read(_BL, {"groups": [], "users": []})


def black_groups() -> Set[int]:
    return {int(g) for g in black_snapshot()["groups"]}


def black_users() -> Set[int]:
    return {int(u) for u in black_snapshot()["users"]}


def black_add(kind: str, value: int) -> bool:
    with _lock:
        data = black_snapshot()
        key = "groups" if kind == "group" else "users"
        if value in data[key]:
            return False
        data[key] = sorted({*data[key], value})
        _write(_BL, data)
        return True


def black_remove(kind: str, value: int) -> bool:
    with _lock:
        data = black_snapshot()
        key = "groups" if kind == "group" else "users"
        if value not in data[key]:
            return False
        data[key] = [x for x in data[key] if x != value]
        _write(_BL, data)
        return True
