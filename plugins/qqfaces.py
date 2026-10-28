# -*- coding: utf-8 -*-
"""把 QQ 收藏的表情包导进表情库。

拉取 fetch_custom_face 的图片，逐张让模型看一眼打个情绪标签，
这样机器人挑表情时才有描述可用。
"""

import base64

import httpx
from nonebot import get_driver, logger

from . import stickers
from .ai import _mime, vision_describe

PROMPT = (
    "这是什么表情包 用不超过8个字说它的情绪 比如 无语 笑死 震惊 嘲讽 委屈 开心 摆烂 "
    "只说这几个字 不要解释"
)


_cfg = get_driver().config
_NAP_URL = "http://127.0.0.1:3000"
_TOKEN = str(getattr(_cfg, "onebot_access_token", ""))


async def _custom_faces() -> list:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{_NAP_URL}/fetch_custom_face",
            headers={"Authorization": f"Bearer {_TOKEN}"},
            json={},
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("data") or []


async def import_faces(limit: int = 10, progress=None) -> str:
    try:
        urls = await _custom_faces()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"拉取收藏表情失败: {e}")
        return "取不到收藏表情 QQ那边报错了"

    urls = [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")]
    if not urls:
        return "QQ里没收藏表情"

    added = skipped = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for url in urls[: max(1, limit)]:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                raw = resp.content
            except Exception:  # noqa: BLE001
                skipped += 1
                continue

            if stickers.has(stickers._digest(raw)):
                skipped += 1
                continue

            mime = _mime(raw)
            data_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
            try:
                desc = await vision_describe(data_url, PROMPT)
            except Exception:  # noqa: BLE001
                desc = "没认出来"
            stickers.add(raw, desc, mime)
            added += 1
            if progress is not None and added % 5 == 0:
                try:
                    await progress(added, min(limit, len(urls)))
                except Exception:  # noqa: BLE001
                    pass

    return f"导入 {added} 张 跳过 {skipped} 张"
