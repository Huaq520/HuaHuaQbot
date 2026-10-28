# -*- coding: utf-8 -*-
"""自检：管理员私聊发送 /ping 回复 pong。斜杠命令一律只对管理员开放。"""

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule


ping = on_command("ping", aliases={"PING"}, permission=SUPERUSER, priority=10, block=True)


@ping.handle()
async def _handle_ping(event: MessageEvent) -> None:
    where = "私聊" if getattr(event, "group_id", None) is None else f"群 {event.group_id}"
    await ping.finish(f"pong ｜ {where} ｜ QQ {event.user_id}")
