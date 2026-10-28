# -*- coding: utf-8 -*-
"""群操作底座：退群、群管理、自动同意邀请。

破坏性操作（退群、踢人）走二次确认：先把动作挂起，管理员回 /确认 才真的执行。
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import nonebot
from nonebot import get_bots, logger, on_command, on_request
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import (
    FriendRequestEvent,
    GroupRequestEvent,
    MessageEvent,
)
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from . import admins, coder, settings

_DATA = Path(__file__).resolve().parent.parent / "data"
_SETTINGS = _DATA / "settings.json"

_pending: Dict[str, Dict[str, Any]] = {}


# ---------- 设置 ----------
def _load_settings() -> Dict[str, Any]:
    if _SETTINGS.exists():
        try:
            return json.loads(_SETTINGS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_settings(data: Dict[str, Any]) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    _SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def auto_accept() -> bool:
    return bool(_load_settings().get("auto_accept_invite", False))


def set_auto_accept(enable: bool) -> None:
    data = _load_settings()
    data["auto_accept_invite"] = bool(enable)
    _save_settings(data)


# ---------- API ----------
async def call(api: str, **params: Any) -> Tuple[Optional[Any], Optional[str]]:
    bot = next(iter(get_bots().values()), None)
    if bot is None:
        return None, "机器人没连上"
    try:
        return await bot.call_api(api, **params), None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"调用 {api} 失败: {e}")
        return None, str(e)


# ---------- 待确认 ----------
async def send_text(uid: int, gid: int, text: str) -> None:
    bot = next(iter(get_bots().values()), None)
    if bot is None:
        return
    try:
        if gid:
            await bot.call_api("send_group_msg", group_id=int(gid), message=text)
        else:
            await bot.call_api("send_private_msg", user_id=int(uid), message=text)
    except Exception:  # noqa: BLE001
        pass


def set_pending(uid: int, action: Dict[str, Any]) -> None:
    _pending[str(uid)] = action


def pop_pending(uid: int) -> Optional[Dict[str, Any]]:
    return _pending.pop(str(uid), None)


async def run_action(action: Dict[str, Any]) -> str:
    kind = action.get("kind")
    if kind == "leave_group":
        gid = action["group_id"]
        _, err = await call("set_group_leave", group_id=gid)
        if err:
            return f"退群失败 {err}"
        return f"已退出群 {gid}"
    if kind == "code_task":
        uid, gid = int(action.get("uid", 0)), int(action.get("gid", 0))
        if uid != admins.OWNER:
            return "只有主人能确认这个操作"
        prompt = str(action.get("prompt", ""))

        async def _run() -> None:
            sid = settings.dsh_session() or None
            out, new_sid, timed_out = await coder.run_task(prompt, sid)
            if new_sid:
                settings.set_dsh_session(new_sid)
            from pathlib import Path as _P

            try:
                with (_P("/root/nb_bot/data/dsh_audit.log")).open("a", encoding="utf-8") as f:
                    f.write(f"{int(asyncio.get_event_loop().time())} uid={uid} task={prompt[:120]} result={out[:120]}\n")
            except Exception:  # noqa: BLE001
                pass
            await send_text(uid, gid, ("超时了 " if timed_out else "") + out)

        import asyncio as _asyncio

        _asyncio.create_task(_run())
        return "开始跑了 好了叫你"
    if kind == "kick_member":
        _, err = await call(
            "set_group_kick",
            group_id=action["group_id"],
            user_id=action["user_id"],
            reject_add_request=False,
        )
        return f"已踢出 {action['user_id']}" if not err else f"踢人失败 {err}"
    return "不认识这个操作"


from nonebot.permission import Permission


async def _is_admin(_b: Bot, event: Event):
    return admins.is_admin(int(event.user_id))


ADMIN = Permission(_is_admin)

confirm = on_command("确认", permission=ADMIN, priority=5, block=True)
cancel = on_command("取消", permission=ADMIN, priority=5, block=True)


@confirm.handle()
async def _confirm(event: MessageEvent) -> None:
    action = pop_pending(int(event.user_id))
    if not action:
        await confirm.finish("没有待确认的操作")
    await confirm.finish(await run_action(action))


@cancel.handle()
async def _cancel(event: MessageEvent) -> None:
    action = pop_pending(int(event.user_id))
    await cancel.finish("已取消" if action else "没有待确认的操作")


# ---------- 通知管理员 ----------
async def notify_admin(text: str) -> None:
    bot = next(iter(get_bots().values()), None)
    if bot is None:
        return
    for uid in admins.all():
        try:
            await bot.send_private_msg(user_id=int(uid), message=text)
        except Exception:  # noqa: BLE001
            pass


# ---------- 入群邀请 / 好友申请 ----------
all_requests = on_request(priority=10, block=False)


@all_requests.handle()
async def _handle_request(event) -> None:
    # 群邀请
    if isinstance(event, GroupRequestEvent) and event.sub_type == "invite":
        who = event.user_id
        note = (getattr(event, "comment", "") or "").strip()[:60]
        if not auto_accept():
            await notify_admin(
                f"收到入群邀请\n群 {event.group_id}\n邀请人 {who}\n附言 {note or '无'}\n自动进群是关的"
            )
            return
        bot = next(iter(get_bots().values()), None)
        if bot is None:
            return
        try:
            await bot.call_api(
                "set_group_add_request", flag=event.flag, sub_type="invite", approve=True
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"同意邀请失败: {e}")
            await notify_admin(f"入群邀请自动同意失败\n群 {event.group_id}\n原因 {e}")
            return
        await notify_admin(f"已同意入群邀请 {event.group_id}\n邀请人 {who}")
        return

    # 好友申请
    if isinstance(event, FriendRequestEvent):
        note = (getattr(event, "comment", "") or "").strip()[:60]
        if not settings.auto_friend():
            await notify_admin(
                f"收到好友申请\nQQ {event.user_id}\n附言 {note or '无'}\n自动加好友是关的"
            )
            return
        bot = next(iter(get_bots().values()), None)
        if bot is None:
            return
        try:
            await bot.call_api("set_friend_add_request", flag=event.flag, approve=True)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"同意好友申请失败: {e}")
            await notify_admin(f"好友申请自动同意失败\nQQ {event.user_id}\n原因 {e}")
            return
        await notify_admin(f"已同意好友申请 {event.user_id}")
