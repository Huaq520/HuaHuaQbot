# -*- coding: utf-8 -*-
"""主动找话：随机在白名单群 / 私聊发一句，然后看有没有人接。

群：发完盯 5 分钟，有人说话就交给模型判断要不要接；没人说话就记成冷场，不再骚扰。
私聊：不用判断，正常回就行；可以反复找。
"""

import asyncio
import datetime
import json
import random
import time
from pathlib import Path

import httpx
from nonebot import get_bots, get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.rule import Rule

from . import settings, store
from . import memory
from .ai import _get_history, _RECENT, ask_deepseek, chat_once, get_persona, wake_touch

_DATA = Path("/root/nb_bot/data")
_STATE = _DATA / "proactive_state.json"
WATCH_SECONDS = 300

_watch: dict = {}       # 群号 -> {"deadline": ts, "opener": str, "seen": set}
_muted: dict = {}       # 冷场群 -> 冷场时间
_last_sent = 0.0
_next_at = 0.0
_opener: dict = {}      # 群号 -> 刚发的那句话
MUTE_HOURS = 24
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    TZ = datetime.timezone(datetime.timedelta(hours=8))

# 只在这个时间段内主动说话（本地时区）
DAY_START = "07:30"
DAY_END = "24:00"
# 白天这几小时更活跃，间隔打折
ACTIVE_START = "08:00"
ACTIVE_END = "23:00"
ACTIVE_FACTOR = 0.6


def _hm(now: datetime.datetime, text: str) -> int:
    """把 07:30 / 24:00 这种转成当天的分钟数。"""
    if text == "24:00":
        return 24 * 60
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def _in_window(now: datetime.datetime, start: str, end: str) -> bool:
    cur = now.hour * 60 + now.minute
    a, b = _hm(now, start), _hm(now, end)
    if a <= b:
        return a <= cur < b
    return cur >= a or cur < b


def _can_speak(now: datetime.datetime) -> bool:
    return _in_window(now, DAY_START, DAY_END)


def _base_seconds() -> float:
    """白天更频繁，夜里（窗口内）慢一些。"""
    now = datetime.datetime.now(TZ)
    base = settings.proactive_interval() * 60
    if _in_window(now, ACTIVE_START, ACTIVE_END):
        base *= ACTIVE_FACTOR
    return base


def _load_state() -> None:
    global _muted
    if _STATE.exists():
        try:
            data = json.loads(_STATE.read_text(encoding="utf-8"))
            raw = data.get("muted", {})
            if isinstance(raw, list):
                _muted = {int(x): time.time() for x in raw}
            else:
                _muted = {int(k): float(v) for k, v in raw.items()}
        except Exception:  # noqa: BLE001
            pass


def _save_state() -> None:
    try:
        _STATE.write_text(
            json.dumps({"muted": {str(k): v for k, v in _muted.items()}}, indent=1),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


async def _target_name(gid: int, uid: int) -> str:
    token = str(getattr(get_driver().config, "onebot_access_token", ""))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if gid:
                r = await client.post(
                    "http://127.0.0.1:3000/get_group_list",
                    headers={"Authorization": f"Bearer {token}"},
                    json={},
                )
                for g in r.json().get("data") or []:
                    if int(g["group_id"]) == gid:
                        return str(g.get("group_name") or "")
            else:
                r = await client.post(
                    "http://127.0.0.1:3000/get_friend_list",
                    headers={"Authorization": f"Bearer {token}"},
                    json={},
                )
                for f in r.json().get("data") or []:
                    if int(f["user_id"]) == uid:
                        return str(f.get("remark") or f.get("nickname") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


async def _send(gid: int, uid: int, text: str) -> None:
    token = str(getattr(get_driver().config, "onebot_access_token", ""))
    body = {"group_id": gid, "message": text} if gid else {"user_id": uid, "message": text}
    api = "send_group_msg" if gid else "send_private_msg"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"http://127.0.0.1:3000/{api}",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        # 记进上下文 免得对方回复时她不知道自己在说什么
        if gid:
            dq = _RECENT.setdefault(int(gid), __import__("collections").deque(maxlen=12))
            dq.append(f"你(自己): {text}")
        else:
            key = f"user:{int(uid)}"
            h = _get_history(key)
            h.append({"role": "assistant", "content": text})
            memory.save(key, list(h))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"主动发言失败: {e}")


async def _opener_for(gid: int, uid: int) -> str:
    name = await _target_name(gid, uid)
    if gid:
        where = f"群「{name}」里" if name else "一个群里"
    else:
        where = f"私聊找「{name}」" if name else "私聊找一个人"
    prompt = (
        f"地点是{where} 你想主动开口聊一句 像朋友那样随便说 一句就够 不超过20字 "
        "别自我介绍 别提自己是AI 别把对方名字念出来 句子要通顺 不要重复词"
    )
    try:
        text = await chat_once(prompt)
    except Exception:  # noqa: BLE001
        text = "在干嘛呢"
    return text.strip().split("\n")[0][:40] or "在吗"


async def _tick() -> None:
    global _last_sent, _next_at
    if not settings.proactive():
        return
    now = time.time()
    local = datetime.datetime.now(TZ)
    if not _can_speak(local):
        return
    base = _base_seconds()
    if _next_at == 0:
        _next_at = now + base * random.uniform(0.5, 1.5)
        return
    if now < _next_at:
        return

    groups = [g for g in store.groups() if g not in _muted]
    users = list(store.users())
    targets = []
    for g in groups:
        targets.append(("group", g))
    for u in users:
        targets.append(("user", u))
    if not targets:
        return

    kind, tid = random.choice(targets)
    if kind == "group":
        text = await _opener_for(int(tid), 0)
        await _send(int(tid), 0, text)
        _watch[int(tid)] = {
            "deadline": time.time() + WATCH_SECONDS,
            "opener": text,
            "seen": set(),
        }
    else:
        text = await _opener_for(0, int(tid))
        await _send(0, int(tid), text)
    _last_sent = now
    _next_at = now + base * random.uniform(0.5, 1.5)
    logger.info(f"主动发言 -> {kind} {tid}: {text[:30]} 下次 {int((_next_at - now) / 60)} 分钟后")


async def _check_timeout() -> None:
    now = time.time()
    for gid, info in list(_watch.items()):
        if now > info["deadline"]:
            _watch.pop(gid, None)
            if not info["seen"]:
                _muted[gid] = now
                _save_state()
                logger.info(f"群 {gid} 没人理 记成冷场")
            else:
                logger.info(f"群 {gid} 有人说过话 不记冷场")

    # 冷场自动解除
    for gid, ts in list(_muted.items()):
        if now - ts > MUTE_HOURS * 3600:
            _muted.pop(gid, None)
            _save_state()
            logger.info(f"群 {gid} 冷场超过 {MUTE_HOURS} 小时 自动解除")


@get_driver().on_startup
async def _start() -> None:
    _load_state()

    async def loop() -> None:
        while True:
            try:
                await _tick()
                await _check_timeout()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"主动发言循环出错: {e}")
            await asyncio.sleep(60)

    asyncio.create_task(loop())


async def _is_group_msg(event: MessageEvent) -> bool:
    return isinstance(event, GroupMessageEvent) and int(event.group_id) in _watch


watch_group = on_message(rule=Rule(_is_group_msg), priority=5, block=False)


@watch_group.handle()
async def _on_watch(event: GroupMessageEvent) -> None:
    gid = int(event.group_id)
    info = _watch.get(gid)
    if not info:
        return
    uid = int(event.user_id)
    if uid == int(event.self_id):
        return

    # 每个人在这个窗口里只判断第一条
    if uid in info["seen"]:
        return
    info["seen"].add(uid)

    text = event.get_plaintext().strip()
    if not text:
        return

    try:
        judge = await chat_once(
            "判断这句话是不是在回应、提到或延续下面这个话题 或者提到了大肥鱼 机器人 AI "
            "只回一个字 是 或 否\n"
            f"你刚才说：{info['opener']}\n对方说：{text}"
        )
    except Exception:  # noqa: BLE001
        return

    if "是" not in judge[:2]:
        logger.info(f"群 {gid} 用户 {uid} 第一条无关 跳过")
        return

    # 有关：给他开 5 分钟窗口，后面的消息走正常 AI 流程（相当于被@）
    wake_touch(gid, uid)
    logger.info(f"群 {gid} 用户 {uid} 第一条相关 交给正常回复流程")


def muted_groups() -> set:
    return set(_muted.keys())


def active_watches() -> dict:
    return dict(_watch)


def unmute(gid: int) -> None:
    if gid in _muted:
        _muted.pop(gid, None)
        _save_state()


async def _in_muted(event: MessageEvent) -> bool:
    return isinstance(event, GroupMessageEvent) and int(event.group_id) in _muted


wake_up = on_message(rule=Rule(_in_muted), priority=50, block=False)


@wake_up.handle()
async def _wake(event: GroupMessageEvent) -> None:
    unmute(int(event.group_id))
