"""唤醒窗口逻辑测试。"""

import asyncio
import time

import nonebot

nonebot.init()

from plugins import ai  # noqa: E402


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def main():
    ok = []
    gid, uid = 100001, 1000001

    ok.append(ai.wake_active(gid, uid) is False)
    print("未唤醒时 wake_active =", ai.wake_active(gid, uid))

    ai.wake_touch(gid, uid)
    ok.append(ai.wake_active(gid, uid) is True)
    print("唤醒后 wake_active =", ai.wake_active(gid, uid))

    ok.append(ai._is_group_target(Ev(group_id=gid, user_id=uid, to_me=False)) is True)
    print("唤醒期内不@也响应 =", ai._is_group_target(Ev(group_id=gid, user_id=uid, to_me=False)))

    ok.append(ai._is_group_target(Ev(group_id=gid, user_id=1, to_me=True)) is True)
    print("别人@仍然响应 =", ai._is_group_target(Ev(group_id=gid, user_id=1, to_me=True)))

    ok.append(ai._is_group_target(Ev(group_id=gid, user_id=999, to_me=False)) is False)
    print("非唤醒人不@不响应 =", ai._is_group_target(Ev(group_id=gid, user_id=999, to_me=False)))

    # 模拟 5 分钟后：直接改到期时间
    ai._wake[(gid, uid)] = time.monotonic() - 1
    ok.append(ai.wake_active(gid, uid) is False)
    print("超时后自动休眠 =", ai.wake_active(gid, uid))

    print(f"\n{sum(ok)}/{len(ok)} 通过")


asyncio.run(main())
