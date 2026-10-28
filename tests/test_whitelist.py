"""白名单逻辑回归测试：直接调用守卫函数，验证动态增删是否即时生效。

运行：cd /root/nb_bot && PYTHONPATH=/root/nb_bot ./.venv/bin/python tests/test_whitelist.py
"""

import asyncio

import nonebot

nonebot.init()

from nonebot.exception import IgnoredException  # noqa: E402

from plugins import store  # noqa: E402
from plugins.whitelist import _whitelist_guard  # noqa: E402


class Ev:
    def __init__(self, t="message", **kw):
        self._t = t
        self.__dict__.update(kw)

    def get_type(self):
        return self._t


async def case(name, ev, expect_block):
    try:
        await _whitelist_guard(None, ev)
        got = False
    except IgnoredException:
        got = True
    print(f"{'PASS' if got == expect_block else 'FAIL'}  {name}: 丢弃={got} 期望={expect_block}")
    return got == expect_block


async def main():
    results = []
    results.append(await case("白名单群 100001", Ev(group_id=100001, user_id=1), False))
    results.append(await case("其它群 123456", Ev(group_id=123456, user_id=1), True))
    results.append(await case("管理员私聊 1000001", Ev(user_id=1000001), False))
    results.append(await case("白名单私聊 1000002", Ev(user_id=1000002), False))
    results.append(await case("陌生人私聊 111", Ev(user_id=111), True))
    results.append(await case("元事件", Ev(t="meta_event", user_id=1), False))

    # 动态加群后应立即放行，删掉后立即恢复拦截
    store.add_group(123456)
    results.append(await case("动态加群 123456 后", Ev(group_id=123456, user_id=1), False))
    store.remove_group(123456)
    results.append(await case("动态删群 123456 后", Ev(group_id=123456, user_id=1), True))

    # 动态加人同理
    store.add_user(999)
    results.append(await case("动态加人 999 后", Ev(user_id=999), False))
    store.remove_user(999)
    results.append(await case("动态删人 999 后", Ev(user_id=999), True))

    print(f"\n{sum(results)}/{len(results)} 通过")
    print("当前名单:", store.snapshot())


asyncio.run(main())
