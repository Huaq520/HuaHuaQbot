# -*- coding: utf-8 -*-
"""好感度：机器人和每个 QQ 的关系档位，共 7 档。

存 data/affinity/user_<QQ>.json，默认「适中」。
档位会拼进系统提示词，直接影响说话态度。
"""

import json
import re
import threading
import time
from pathlib import Path
from typing import Dict

LEVELS = ["低", "略低", "适中", "略高", "高", "超高", "信任"]
DEFAULT = 2  # 适中

_DIR = Path(__file__).resolve().parent.parent / "data" / "affinity"
_lock = threading.Lock()
_SAFE = re.compile(r"[^0-9A-Za-z_-]")

TONE = {
    "低": "爱答不理 能一个字就一个字 不想多聊",
    "略低": "正常回但有点冷淡 不会主动找话",
    "适中": "友好 正常聊天 偶尔接个梗",
    "略高": "主动一点 愿意多聊两句 会接对方的话头",
    "高": "比较亲近 会开玩笑 会调侃对方",
    "超高": "很熟 说话随意 会互怼 会关心对方的事",
    "信任": "最信任的人 有求必应 会说心里话 会护着对方",
}


def _path(uid: str) -> Path:
    return _DIR / f"user_{_SAFE.sub('_', str(uid))}.json"


def get_index(uid: str) -> int:
    path = _path(uid)
    if not path.exists():
        return DEFAULT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return max(0, min(len(LEVELS) - 1, int(data.get("index", DEFAULT))))
    except Exception:  # noqa: BLE001
        return DEFAULT


def level_name(uid: str) -> str:
    return LEVELS[get_index(uid)]


def set_index(uid: str, index: int, reason: str = "") -> int:
    index = max(0, min(len(LEVELS) - 1, int(index)))
    with _lock:
        path = _path(uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict = {"index": index, "level": LEVELS[index], "updated": int(time.time())}
        if reason:
            data["reason"] = reason
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    return index


def set_level(uid: str, level: str, reason: str = "") -> int:
    level = level.strip()
    if level in LEVELS:
        return set_index(uid, LEVELS.index(level), reason)
    if level.isdigit():
        return set_index(uid, int(level), reason)
    return get_index(uid)


def prompt_for(uid: str) -> str:
    idx = get_index(uid)
    name = LEVELS[idx]
    return (
        f"你对当前这个人的好感度 {idx}/{len(LEVELS) - 1} 档 {name}。"
        f"这个档位下你的态度是 {TONE[name]}。"
        "好感度完全由你自己判断 看对方怎么跟你说话 聊得来就升 被冒犯就降 "
        "一次最多动两档 没有理由就别改"
    )
