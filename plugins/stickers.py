# -*- coding: utf-8 -*-
"""表情包库：图片存在 data/stickers/ 下，索引在同目录 index.json。

每条记录：{"id": 1, "file": "1.png", "desc": "无语 翻白眼"}
desc 是给模型看的，它靠这个判断什么时候该发哪张。
"""

import base64
import hashlib
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DIR = Path(__file__).resolve().parent.parent / "data" / "stickers"
_INDEX = _DIR / "index.json"
_lock = threading.Lock()

_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


def _load() -> List[Dict]:
    if not _INDEX.exists():
        return []
    try:
        data = json.loads(_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save_index(items: List[Dict]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    tmp = _INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_INDEX)


def items() -> List[Dict]:
    return _load()


def get(sid: int) -> Optional[Dict]:
    return next((s for s in _load() if int(s["id"]) == int(sid)), None)


def path_of(sticker: Dict) -> Path:
    return _DIR / sticker["file"]


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def has(digest: str) -> bool:
    return any(s.get("hash") == digest for s in _load())


def add(raw: bytes, desc: str, mime: str = "image/png") -> Dict:
    with _lock:
        data = _load()
        sid = max((int(s["id"]) for s in data), default=0) + 1
        ext = _EXT.get(mime, "png")
        name = f"{sid}.{ext}"
        _DIR.mkdir(parents=True, exist_ok=True)
        (_DIR / name).write_bytes(raw)
        item = {"id": sid, "file": name, "desc": desc.strip() or "没描述", "hash": _digest(raw)}
        data.append(item)
        _save_index(data)
        return item


def remove(sid: int) -> bool:
    with _lock:
        data = _load()
        keep = [s for s in data if int(s["id"]) != int(sid)]
        gone = [s for s in data if int(s["id"]) == int(sid)]
        if not gone:
            return False
        for s in gone:
            try:
                (_DIR / s["file"]).unlink()
            except OSError:
                pass
        _save_index(keep)
        return True


def describe_for_prompt() -> str:
    data = _load()
    if not data:
        return ""
    lines = [f"{s['id']} {s['desc']}" for s in data]
    return ("你手上有这些表情包 遇到情绪对得上的就发一张 别光顾着说话 发表情用 send_sticker 传编号\n" + "\n".join(lines))
