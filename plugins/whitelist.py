# -*- coding: utf-8 -*-
"""准入守卫：黑名单优先拦截，然后白名单放行。

名单在 data/whitelist.json 和 data/blacklist.json，改完即时生效。
"""

from nonebot import get_driver
from nonebot.adapters import Bot, Event
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

from . import admins, store

_config = get_driver().config
SUPERUSERS = {str(u) for u in _config.superusers}


@event_preprocessor
async def _guard(bot: Bot, event: Event) -> None:
    if event.get_type() == "meta_event":
        return

    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)

    # 黑名单：群整个拦，人连群带私聊都拦
    if group_id is not None and int(group_id) in store.black_groups():
        raise IgnoredException(f"群 {group_id} 在黑名单")
    if user_id is not None and int(user_id) in store.black_users():
        raise IgnoredException(f"用户 {user_id} 在黑名单")

    # 群消息一律看群白名单，管理员也不例外
    if group_id is not None:
        if int(group_id) not in store.groups():
            raise IgnoredException(f"群 {group_id} 不在白名单")
        return

    # 私聊：管理员永远放行，其余看名单
    if user_id is not None and (
        admins.is_admin(int(user_id)) or int(user_id) in store.users()
    ):
        return

    raise IgnoredException(f"用户 {user_id} 不在白名单")
