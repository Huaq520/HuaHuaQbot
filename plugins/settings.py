# -*- coding: utf-8 -*-
"""运行时可调参数：模型、推理等级、联网搜索。

存在 data/settings.json，和 groupadmin 的开关共用同一个文件。
"""

import json
from pathlib import Path
from typing import Any, Dict

_SETTINGS = Path(__file__).resolve().parent.parent / "data" / "settings.json"

MODELS = ["deepseek-flash", "deepseek-v4-pro"]
EFFORTS = ["low", "high", "max"]
EFFORT_ALIAS = {
    "低": "low",
    "low": "low",
    "中": "high",
    "高": "high",
    "high": "high",
    "最高": "max",
    "max": "max",
}


def _load() -> Dict[str, Any]:
    if _SETTINGS.exists():
        try:
            return json.loads(_SETTINGS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save(data: Dict[str, Any]) -> None:
    _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def model(default: str) -> str:
    return str(_load().get("model") or default)


def set_model(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("模型名不能空")
    data = _load()
    data["model"] = name
    _save(data)
    return name


def effort(default: str = "high") -> str:
    value = str(_load().get("effort") or default)
    return value if value in EFFORTS else default


def set_effort(level: str) -> str:
    key = EFFORT_ALIAS.get(level.strip().lower(), EFFORT_ALIAS.get(level.strip()))
    if key not in EFFORTS:
        raise ValueError("推理等级只能是 low high max")
    data = _load()
    data["effort"] = key
    _save(data)
    return key


def persona(default: str = "大肥鱼") -> str:
    return str(_load().get("persona") or default)


def set_persona(name: str) -> str:
    data = _load()
    data["persona"] = name.strip()
    _save(data)
    return data["persona"]


def api_base(default: str) -> str:
    return str(_load().get("api_base") or default).rstrip("/")


def set_api_base(url: str) -> str:
    data = _load()
    data["api_base"] = url.strip().rstrip("/")
    _save(data)
    return data["api_base"]


def api_key(default: str) -> str:
    return str(_load().get("api_key") or default)


def set_api_key(key: str) -> None:
    data = _load()
    data["api_key"] = key.strip()
    _save(data)


def proactive() -> bool:
    return bool(_load().get("proactive", False))


def set_proactive(enable: bool) -> None:
    data = _load()
    data["proactive"] = bool(enable)
    _save(data)


def proactive_interval() -> int:
    return int(_load().get("proactive_interval", 180))


def set_proactive_interval(minutes: int) -> None:
    data = _load()
    data["proactive_interval"] = max(10, int(minutes))
    _save(data)


def auto_friend() -> bool:
    return bool(_load().get("auto_accept_friend", False))


def set_auto_friend(enable: bool) -> None:
    data = _load()
    data["auto_accept_friend"] = bool(enable)
    _save(data)


def dsh_session() -> str:
    return str(_load().get("dsh_session") or "")


def set_dsh_session(sid: str) -> None:
    data = _load()
    data["dsh_session"] = sid
    _save(data)


def clear_dsh_session() -> None:
    data = _load()
    data.pop("dsh_session", None)
    _save(data)


def web_search() -> bool:
    return bool(_load().get("web_search", False))


def set_web_search(enable: bool) -> bool:
    data = _load()
    data["web_search"] = bool(enable)
    _save(data)
    return bool(enable)
