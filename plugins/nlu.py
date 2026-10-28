# -*- coding: utf-8 -*-
"""斜杠指令：全部本地解析，不调用大模型。

用法一律是「/命令 参数」，例如：
    /dsh 建一个 hello.txt
    /模型 v4pro
    /推理 max
    /联网 on
    /导入表情 30

不认识的命令直接提示看 /帮助，不会丢给模型瞎猜。
"""

import asyncio
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import httpx

import nonebot
from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.params import EventPlainText
from nonebot.adapters import Bot, Event
from nonebot.permission import Permission, SUPERUSER
from nonebot.rule import Rule

from . import (
    admins,
    affinity,
    coder,
    modellist,
    providers,
    groupadmin,
    memory,
    persona_store,
    qqfaces,
    settings,
    stickers,
    store,
)

_config = get_driver().config
SUPERUSERS = {str(u) for u in _config.superusers}


async def _is_admin(bot: Bot, event: Event) -> bool:
    try:
        return admins.is_admin(int(event.user_id))
    except Exception:  # noqa: BLE001
        return False


ADMIN = Permission(_is_admin)


def _persona_dir():
    from .ai import _PERSONA_DIR

    return _PERSONA_DIR


def _need_int(rest: str, usage: str):
    token = rest.split()[0] if rest.split() else ""
    if not token.isdigit():
        return None, usage
    return int(token), ""


_CHOICES: Dict[int, dict] = {}
_CHOICE_TTL = 180


def _set_choices(uid: int, title: str, options: List[Tuple[str, Callable]]) -> str:
    _CHOICES[uid] = {"at": time.time(), "options": options}
    lines = [f"{i}. {label}" for i, (label, _) in enumerate(options, 1)]
    return title + "\n" + "\n".join(lines) + "\n回数字选"


def _target(rest: str, ats=None, usage: str = "") -> tuple:
    """从参数或 @ 里取一个 QQ 号，返回 (值, 错误)。"""
    ats = ats or []
    raw = rest.strip()
    if raw.isdigit():
        return int(raw), ""
    if ats:
        return int(ats[0]), ""
    return None, usage


async def _say(uid: int, gid: int, text: str) -> None:
    await groupadmin.send_text(int(uid), int(gid), text)


# ---------- 基础 ----------
USER_CMDS = {"帮助", "我是谁", "好感", "人格", "切换人格"}


def _level(uid: int) -> str:
    if int(uid) == admins.OWNER:
        return "owner"
    return "admin" if admins.is_admin(int(uid)) else "user"


# 帮助菜单的元数据：类别, 展示用法, 最低权限
HELP_ITEMS = [
    ("基础", "/帮助（/help 也行） /我是谁 /好感 QQ", "user"),
    ("人格", "/人格 /切换人格 [全局]（弹菜单选）", "user"),
    ("人格", "/有哪些人格 /设人格 内容 /设全局人格 内容（主人）", "admin"),
    ("模型", "/模型（菜单选） /推理 low|high|max /联网 on|off /状态", "admin"),
    ("准入", "/白名单 看列表 | /白名单 @人 | /白名单 群号", "admin"),
    ("准入", "/白名单删 @人 或 群号", "admin"),
    ("准入", "/黑名单 | /黑名单 @人 | /黑名单删 @人 或 群号", "admin"),
    ("准入", "旧写法也认：/加群 /加人 /删群 /删人 /拉黑 /解黑", "admin"),
    ("记忆", "/会话 /忘记 关键词 /记忆 /清记忆 /唤醒", "admin"),
    ("表情", "/导入表情 数量 /表情 /删表情 编号", "admin"),
    ("群管理", "/群成员 号 /公告 号 内容 /撤回 ID", "admin"),
    ("群管理", "/退群 号 /踢人 号 QQ /禁言 号 QQ 分钟 /解禁 号 QQ", "admin"),
    ("群管理", "/名片 号 QQ 名 /群名 号 名 /全员禁言 号 on|off", "admin"),
    ("群管理", "/自动进群 on|off /自动加好友 on|off", "admin"),
    ("互动", "/点赞 QQ /戳 QQ /提醒 分钟 内容 /活跃", "admin"),
    ("互动", "/主动 on|off（随机找话） /主动 分钟数", "admin"),
    ("权限", "/op QQ 或 @人 /deop QQ /ops", "owner"),
    ("主人", "/余额 /接口 URL KEY", "owner"),
    ("主人", "/dsh 任务 /dsh会话 /dsh切换 ID /dsh新", "owner"),
]

_RANK = {"user": 0, "admin": 1, "owner": 2}


def _allowed_items(lv: str):
    allow = _RANK[lv]
    return [(c, u, n) for c, u, n in HELP_ITEMS if _RANK[n] <= allow]


def _render_items(items, cats=None) -> str:
    lines, last = [], None
    for cat, usage, _ in items:
        if cats is not None and cat not in cats:
            continue
        if cat != last:
            lines.append(f"【{cat}】")
            last = cat
        lines.append(usage)
    return "\n".join(lines)


def _category_options(uid: int, lv: str):
    cats = []
    for cat, _, _ in _allowed_items(lv):
        if cat not in cats:
            cats.append(cat)
    options = []
    for cat in cats:
        async def _open(c=cat):
            return await _help_category(uid, c, lv)

        count = len([1 for x in _allowed_items(lv) if x[0] == cat])
        options.append((f"{cat}（{count} 条）", _open))

    async def _all() -> str:
        return await cmd_help("全部", uid, 0)

    options.append(("全部命令", _all))
    return options


async def _help_category(uid: int, cat: str, lv: str) -> str:
    items = [x for x in _allowed_items(lv) if x[0] == cat]
    body = _render_items(items)
    # 看完一类还能直接回数字跳别的
    _set_choices(uid, f"【{cat}】", _category_options(uid, lv))
    return f"{body}\n\n还想看别的直接回数字 或 /帮助"


async def cmd_help(rest: str, uid: int, gid: int, ats=None) -> str:
    lv = _level(uid)
    arg = rest.strip().lower()

    # /帮助 全部 或 /help all
    if arg in ("全部", "all", "所有"):
        body = _render_items(_allowed_items(lv))
        tail = "\n\n（/帮助 看分类）"
        if lv == "user":
            tail = "\n\n其它管理命令需要管理员权限" + tail
        return body + tail

    cats = []
    for cat, _, _ in _allowed_items(lv):
        if cat not in cats:
            cats.append(cat)

    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(cats):
            return await _help_category(uid, cats[idx], lv)
        return f"只有 {len(cats)} 个分类"

    options = _category_options(uid, lv)
    head = "想看哪一类"
    if lv == "user":
        head += "（管理类的要管理员）"
    return _set_choices(uid, head, options)


async def cmd_model(rest: str, uid: int, gid: int) -> str:
    from .ai import api_base, api_key

    arg = rest.strip()
    alias = {"flash": "deepseek-flash", "v4pro": "deepseek-v4-pro", "pro": "deepseek-v4-pro"}

    if arg:
        name = alias.get(arg.lower(), arg)
        try:
            settings.set_model(name)
        except ValueError as e:
            return str(e)
        return f"模型换成 {name}"

    cur_base = api_base()
    plist = providers.all()

    async def _label(p: dict) -> str:
        is_cur = p["base"].rstrip("/") == cur_base.rstrip("/")
        key = p.get("key") or (api_key() if is_cur else "")
        prefer = settings.model("") if is_cur else ""
        if not key:
            return p["name"] + "（未配 Key）"
        ms, bal = await providers.health(
            {"name": p["name"], "base": p["base"], "key": key}, prefer
        )
        speed = f"{ms}ms" if ms and ms < 1000 else (f"{ms / 1000:.1f}s" if ms else "超时")
        return f"{p['name']} · {speed} · {bal}" + (" ←当前" if is_cur else "")

    labels = await asyncio.gather(*(_label(p) for p in plist))

    options = []
    for p, label in zip(plist, labels):
        async def _open(name=p["name"]):
            return await _provider_menu(uid, name)

        options.append((label, _open))

    async def _add() -> str:
        return await _add_provider_menu(uid)

    options.append(("＋ 新增大模型", _add))
    return _set_choices(uid, f"选一个大模型\n当前 {settings.model('')}", options)


PROVIDER_PRESETS = {
    "DeepSeek": "https://api.deepseek.com/v1",
    "OpenAI GPT": "https://api.openai.com/v1",
    "Kimi 月之暗面": "https://api.moonshot.cn/v1",
    "智谱 GLM": "https://open.bigmodel.cn/api/paas/v4",
    "通义千问": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "硅基流动": "https://api.siliconflow.cn/v1",
    "火山方舟": "https://ark.cn-beijing.volces.com/api/v3",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "Grok": "https://api.x.ai/v1",
}


async def _add_provider_menu(uid: int) -> str:
    options = []
    for name, base in PROVIDER_PRESETS.items():
        async def _pick(n=name, b=base):
            _AWAIT[uid] = ("newkey", time.time(), n)
            return f"把 {n} 的 API Key 发给我\n地址会用默认的 {b}\n两分钟内有效"

        options.append((name, _pick))

    async def _manual() -> str:
        return "自定义接口发：/接口 地址 KEY\n例如 /接口 https://xxx/v1 sk-xxx"

    async def _back() -> str:
        return await cmd_model("", uid, 0)

    options.append(("自定义接口", _manual))
    options.append(("← 返回", _back))
    return _set_choices(uid, "选一个服务商 点进去只要填 Key", options)


async def _save_provider_key(uid: int, name: str, key: str) -> str:
    base = PROVIDER_PRESETS.get(name, "")
    if not base:
        return f"不认识 {name}"
    providers.upsert(name, base, key)
    from .ai import api_key as _k

    names = await modellist.cached_models(base, key) or []
    if not names:
        return f"已保存 {name} 的 Key，但接口没返回模型列表，检查一下 Key 是否正确"
    return await _provider_menu(uid, name)


async def _provider_menu(uid: int, name: str) -> str:
    p = providers.get(name)
    if not p:
        return f"没有 {name}"
    from .ai import api_key

    key = p.get("key") or (api_key() if p["base"].rstrip("/") == settings.api_base("") else "")
    names = await modellist.cached_models(p["base"], key) or []

    options = []
    for m in names:
        async def _open(model=m, prov=p):
            return _model_menu(uid, prov, model)

        options.append((m, _open))

    async def _back():
        return await cmd_model("", uid, 0)

    options.append(("← 返回大模型列表", _back))
    head = f"{name} 共 {len(names)} 个模型\n接口 {p['base']}"
    if not names:
        head = f"{name}\n接口没返回模型列表 可能 Key 没配\n{p['base']}"
    return _set_choices(uid, head, options)


def _model_menu(uid: int, prov: dict, model: str) -> str:
    async def _switch() -> str:
        settings.set_api_base(prov["base"])
        if prov.get("key"):
            settings.set_api_key(prov["key"])
        settings.set_model(model)
        return f"已切到 {prov['name']} / {model}"

    async def _effort_menu() -> str:
        opts = []
        for lv in ("low", "high", "max"):
            async def _set(v=lv):
                settings.set_effort(v)
                return f"推理等级 {v}"

            opts.append((lv + (" ←当前" if settings.effort() == lv else ""), _set))
        return _set_choices(uid, f"{model} 的推理等级", opts)

    async def _toggle_web() -> str:
        settings.set_web_search(not settings.web_search())
        return "联网已开" if settings.web_search() else "联网已关"

    async def _await_key() -> str:
        _AWAIT[uid] = ("key", time.time(), prov["name"])
        return f"把 {prov['name']} 的新 Key 发给我 两分钟内有效"

    async def _await_url() -> str:
        _AWAIT[uid] = ("url", time.time(), prov["name"])
        return f"把 {prov['name']} 的新接口地址发给我 两分钟内有效"

    async def _back() -> str:
        return await _provider_menu(uid, prov["name"])

    return _set_choices(
        uid,
        f"{prov['name']} / {model}\n推理 {settings.effort()} 联网 {'开' if settings.web_search() else '关'}",
        [
            ("换成这个模型", _switch),
            ("调整推理等级", _effort_menu),
            ("联网 开/关", _toggle_web),
            ("更改 API Key", _await_key),
            ("更改 URL", _await_url),
            ("← 返回模型列表", _back),
        ],
    )


async def cmd_effort(rest: str, uid: int, gid: int) -> str:
    arg = rest.strip().lower()
    if not arg:
        return f"当前推理等级 {settings.effort()}"
    try:
        return f"推理等级 {settings.set_effort(arg)}"
    except ValueError as e:
        return str(e)


async def cmd_web(rest: str, uid: int, gid: int) -> str:
    arg = rest.strip().lower()
    if arg in ("on", "开", "开启", "1", "true"):
        settings.set_web_search(True)
        return "联网搜索已开"
    if arg in ("off", "关", "关闭", "0", "false"):
        settings.set_web_search(False)
        return "联网搜索已关"
    return f"联网搜索当前 {'开' if settings.web_search() else '关'} 用 /联网 on 或 off"


async def _nap(api: str, **params):
    token = str(getattr(get_driver().config, "onebot_access_token", ""))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"http://127.0.0.1:3000/{api}",
                headers={"Authorization": f"Bearer {token}"},
                json=params or {},
            )
            return resp.json().get("data")
    except Exception:  # noqa: BLE001
        return None


async def _names():
    groups = {}
    for g in await _nap("get_group_list") or []:
        try:
            groups[int(g["group_id"])] = g.get("group_name") or ""
        except Exception:  # noqa: BLE001
            continue
    users = {}
    for f in await _nap("get_friend_list") or []:
        try:
            users[int(f["user_id"])] = (f.get("remark") or f.get("nickname") or "").strip()
        except Exception:  # noqa: BLE001
            continue
    return groups, users


async def cmd_status(rest: str, uid: int, gid: int, ats=None) -> str:
    from .ai import api_base, wake_snapshot

    key = f"group:{gid}" if gid else f"user:{uid}"
    override = persona_store.get(key)
    persona_line = f"人格 全局 {settings.persona()}"
    if override and override != "__custom__":
        persona_line += f" / 本会话 {override}"
    elif override == "__custom__":
        persona_line += " / 本会话 自定义"

    wl, bl = store.snapshot(), store.black_snapshot()
    wake = wake_snapshot()
    sticker_count = len(stickers.items())

    return (
        f"模型 {settings.model('')} 推理 {settings.effort()} "
        f"联网 {'开' if settings.web_search() else '关'}\n"
        f"接口 {api_base()}\n"
        f"{persona_line}\n"
        f"白名单 群{len(wl['groups'])} 人{len(wl['users'])} "
        f"黑名单 群{len(bl['groups'])} 人{len(bl['users'])}\n"
        f"记忆 {len(memory.list_files())} 份 表情 {sticker_count} 张 活跃 {len(wake)}"
    )


async def cmd_wake(rest: str, uid: int, gid: int, ats=None) -> str:
    from .ai import wake_snapshot

    snap = wake_snapshot()
    if not snap:
        return "现在没人处于活跃期"
    return "\n".join(f"群 {g} QQ {u} 剩 {t}s" for (g, u), t in snap.items())


async def cmd_sessions(rest: str, uid: int, gid: int, ats=None) -> str:
    groups = await _nap("get_group_list") or []
    friends = await _nap("get_friend_list") or []
    names = {}
    for f in friends:
        try:
            names[int(f["user_id"])] = (f.get("remark") or f.get("nickname") or "").strip()
        except Exception:  # noqa: BLE001
            continue
    lines = [f"她所在的群 {len(groups)} 个"]
    for g in groups:
        try:
            lines.append(f"· {int(g['group_id'])} {g.get('group_name', '')}")
        except Exception:  # noqa: BLE001
            continue
    lines.append("")
    files = memory.list_files()
    lines.append(f"聊过的人 {len(files)} 个")
    for f in files:
        qq = f.replace("user_", "")
        if qq.isdigit():
            lines.append(f"· {qq} {names.get(int(qq), '')}".rstrip())
    return "\n".join(lines)


async def cmd_wl(rest: str, uid: int, gid: int, ats=None) -> str:
    d = store.snapshot()
    ats = ats or []
    raw = rest.strip()

    if not raw and not ats:
        gnames, unames = await _names()
        lines = ["白名单群"]
        for x in d["groups"]:
            name = gnames.get(x)
            lines.append(f"· {x} {name if name else '（她不在这个群）'}")
        lines.append("")
        lines.append("白名单私聊")
        for x in d["users"]:
            lines.append(f"· {x} {unames.get(x, '')}".rstrip())
        return "\n".join(lines)

    targets = list(ats)
    if raw.isdigit():
        targets.append(int(raw))
    if not targets:
        return "发 /白名单 看列表，或 /白名单 @某人 加人，/白名单 群号 加群"

    groups, _ = await _names()
    added = []
    for t in targets:
        if t in groups:
            added.append(f"群 {t} {groups[t]}" if store.add_group(t) else f"群 {t} 已在名单")
        else:
            added.append(f"人 {t}" if store.add_user(t) else f"{t} 已在名单")
    return "已加入白名单\n" + "\n".join(added)


async def cmd_wl_del(rest: str, uid: int, gid: int, ats=None) -> str:
    ats = ats or []
    raw = rest.strip()
    targets = list(ats)
    if raw.isdigit():
        targets.append(int(raw))
    if not targets:
        return "用法 /白名单删 @某人 或 /白名单删 群号"

    out = []
    for t in targets:
        if store.remove_group(t):
            out.append(f"群 {t} 已移出")
        elif store.remove_user(t):
            out.append(f"人 {t} 已移出")
        else:
            out.append(f"{t} 本来就不在名单")
    return "\n".join(out)


async def cmd_bl(rest: str, uid: int, gid: int, ats=None) -> str:
    d = store.black_snapshot()
    ats = ats or []
    raw = rest.strip()

    if not raw and not ats:
        gnames, unames = await _names()
        lines = ["黑名单群 " + (" ".join(map(str, d["groups"])) or "空")]
        lines.append("黑名单人 " + (" ".join(map(str, d["users"])) or "空"))
        return "\n".join(lines)

    targets = list(ats)
    if raw.isdigit():
        targets.append(int(raw))
    groups, _ = await _names()
    out = []
    for t in targets:
        if t in groups:
            out.append(f"群 {t} 已拉黑" if store.black_add("group", t) else f"群 {t} 已在黑名单")
        else:
            out.append(f"人 {t} 已拉黑" if store.black_add("user", t) else f"{t} 已在黑名单")
    return "\n".join(out)


async def cmd_bl_del(rest: str, uid: int, gid: int, ats=None) -> str:
    ats = ats or []
    raw = rest.strip()
    targets = list(ats)
    if raw.isdigit():
        targets.append(int(raw))
    groups, _ = await _names()
    out = []
    for t in targets:
        if t in groups:
            out.append(f"群 {t} 已解除" if store.black_remove("group", t) else f"群 {t} 不在黑名单")
        else:
            out.append(f"人 {t} 已解除" if store.black_remove("user", t) else f"{t} 不在黑名单")
    return "\n".join(out)


async def cmd_op(rest: str, uid: int, gid: int, ats=None) -> str:
    if uid != admins.OWNER:
        return "只有主人能授权管理员"
    ats = ats or []
    raw = rest.strip() or (str(ats[0]) if ats else "")
    if not raw.isdigit():
        return "用法 /op QQ号 或 /op @某人"
    v = int(raw)
    return f"已给 {v} 管理员权限" if admins.add(v) else f"{v} 本来就是管理员"


async def cmd_deop(rest: str, uid: int, gid: int, ats=None) -> str:
    if uid != admins.OWNER:
        return "只有主人能撤销管理员"
    ats = ats or []
    raw = rest.strip() or (str(ats[0]) if ats else "")
    if not raw.isdigit():
        return "用法 /deop QQ号 或 /deop @某人"
    v = int(raw)
    if v == admins.OWNER:
        return "主人的权限撤不掉"
    return f"已撤销 {v} 的管理员" if admins.remove(v) else f"{v} 不是管理员"


async def cmd_ops(rest: str, uid: int, gid: int) -> str:
    lines = ["管理员"]
    for q in admins.all():
        lines.append(f"· {q}" + ("（主人 全权限）" if q == admins.OWNER else "（只管机器人）"))
    return "\n".join(lines)


async def cmd_whoami(rest: str, uid: int, gid: int) -> str:
    return f"你是 {uid}"


async def cmd_affinity(rest: str, uid: int, gid: int, ats=None) -> str:
    target, err = _target(rest, ats, "用法 /好感 QQ号 或 /好感 @某人")
    if err:
        return err
    return f"{target} 好感度 {affinity.level_name(str(target))} {affinity.get_index(str(target))}/6"


# ---------- 人格 ----------
async def cmd_personas(rest: str, uid: int, gid: int) -> str:
    names = sorted(p.stem for p in _persona_dir().glob("*.md"))
    key = f"group:{gid}" if gid else f"user:{uid}"
    cur = persona_store.get(key)
    info = f"全局 {settings.persona()}"
    if cur:
        info += f" 本会话 {cur}"
    return f"{info}\n可选 " + " ".join(names)


async def cmd_switch_persona(rest: str, uid: int, gid: int, ats=None) -> str:
    args = rest.split()
    scope_global = bool(args and args[0] in ("全局", "global"))
    key = f"group:{gid}" if gid else f"user:{uid}"

    if scope_global and int(uid) != admins.OWNER:
        return "全局人格只有主人能改 你可以只改自己的会话"

    # 兼容旧用法：直接带名字就切
    if args and not scope_global:
        name = args[0]
        if (_persona_dir() / f"{name}.md").exists():
            persona_store.set_persona(key, name)
            return f"这个会话切成 {name} 了"

    names = sorted(p.stem for p in _persona_dir().glob("*.md"))
    if not names:
        return "还没有人格文件"

    options = []
    for name in names:
        async def _pick(n=name, glob=scope_global):
            if glob:
                settings.set_persona(n)
                return f"全局人格切成 {n} 了"
            persona_store.set_persona(key, n)
            return f"这个会话切成 {n} 了"

        cur = settings.persona() if scope_global else (persona_store.get(key) or settings.persona())
        options.append((f"{name}{' ←当前' if name == cur else ''}", _pick))

    async def _default() -> str:
        persona_store.clear(key)
        return "这个会话改回跟全局一样了"

    if not scope_global:
        options.append(("改回跟全局一样", _default))

    head = "换全局人格" if scope_global else "换这个会话的人格"
    return _set_choices(uid, head, options)


async def cmd_show_persona(rest: str, uid: int, gid: int, ats=None) -> str:
    from .ai import persona_file

    if gid:
        return "人格提示词只能在私聊里看"
    if int(uid) != admins.OWNER:
        return "人格提示词只有主人能看"

    key = f"group:{gid}" if gid else f"user:{uid}"
    path = persona_file(key)
    text = path.read_text(encoding="utf-8").strip() if path.exists() else "没设置"
    scope = "本会话专属" if persona_store.get(key) else f"全局 {settings.persona()}"
    return f"[{scope}]\n{text[:280]}"


async def cmd_set_persona(rest: str, uid: int, gid: int) -> str:
    """只改当前会话的人格内容，不影响别处。"""
    from .ai import _CUSTOM_DIR, _safe

    text = rest.strip()
    if len(text) < 10:
        return "太短了 至少10个字"
    if len(text) > 800:
        return "太长了 800字以内"
    key = f"group:{gid}" if gid else f"user:{uid}"
    _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    path = _CUSTOM_DIR / f"{_safe(key)}.md"
    path.write_text(text + "\n", encoding="utf-8")
    persona_store.set_persona(key, "__custom__")
    return f"这个会话的人格已改 共{len(text)}字 只影响这里"


async def cmd_set_global_persona(rest: str, uid: int, gid: int) -> str:
    """改全局人格文件，影响没单独设置的会话。"""
    if int(uid) != admins.OWNER:
        return "这个只有主人能用"
    from .ai import _PERSONA_DIR

    text = rest.strip()
    if len(text) < 10:
        return "太短了 至少10个字"
    path = _PERSONA_DIR / f"{settings.persona()}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return f"全局人格({settings.persona()})已改 共{len(text)}字"


# ---------- 表情 ----------
async def cmd_import_stickers(rest: str, uid: int, gid: int) -> str:
    count, _ = _need_int(rest, "")
    count = count or 10
    target_uid, target_gid = uid, gid

    async def _on_progress(done: int, total: int) -> None:
        await _say(target_uid, target_gid, f"导了 {done}/{total}")

    async def _run() -> None:
        res = await qqfaces.import_faces(count, progress=_on_progress)
        await _say(target_uid, target_gid, f"表情包{res}")

    asyncio.create_task(_run())
    return f"开始导入 {count} 张 好了叫你"


async def cmd_stickers(rest: str, uid: int, gid: int) -> str:
    data = stickers.items()
    if not data:
        return "表情库是空的 用 /导入表情 或发图说 存表情 描述"
    return "\n".join(f"#{s['id']} {s['desc']}" for s in data)


async def cmd_del_sticker(rest: str, uid: int, gid: int) -> str:
    sid, err = _need_int(rest, "用法 /删表情 3")
    if err:
        return err
    return "删掉了" if stickers.remove(sid) else "没这个编号"


# ---------- 群管理 ----------
async def cmd_auto_join(rest: str, uid: int, gid: int) -> str:
    arg = rest.strip().lower()
    if arg in ("on", "开", "开启", "1", "true"):
        groupadmin.set_auto_accept(True)
        return "已开启自动同意入群邀请 有人拉她就进"
    if arg in ("off", "关", "关闭", "0", "false"):
        groupadmin.set_auto_accept(False)
        return "已关闭自动同意入群邀请"
    state = "开" if groupadmin.auto_accept() else "关"
    return f"自动同意邀请当前 {state} 用 /自动进群 on 或 off"


async def cmd_proactive(rest: str, uid: int, gid: int, ats=None) -> str:
    arg = rest.strip().lower()
    from . import proactive as _p

    if arg in ("on", "开", "开启"):
        settings.set_proactive(True)
        return "主动找话已开 每 %d 分钟左右一次" % settings.proactive_interval()
    if arg in ("off", "关", "关闭"):
        settings.set_proactive(False)
        return "主动找话已关"
    if arg.isdigit():
        settings.set_proactive_interval(int(arg))
        return f"间隔改成 {settings.proactive_interval()} 分钟"

    state = "开" if settings.proactive() else "关"
    muted = " ".join(map(str, sorted(_p.muted_groups()))) or "无"
    watching = " ".join(map(str, sorted(_p.active_watches()))) or "无"
    return (
        f"主动找话 {state} 间隔 {settings.proactive_interval()} 分钟\n"
        f"正在盯的群 {watching}\n冷场群 {muted}\n"
        "用 /主动 on|off 开关 /主动 分钟数 改间隔"
    )


async def cmd_auto_friend(rest: str, uid: int, gid: int) -> str:
    arg = rest.strip().lower()
    if arg in ("on", "开", "开启", "1", "true"):
        settings.set_auto_friend(True)
        return "已开启自动同意好友申请"
    if arg in ("off", "关", "关闭", "0", "false"):
        settings.set_auto_friend(False)
        return "已关闭自动同意好友申请"
    state = "开" if settings.auto_friend() else "关"
    return f"自动加好友当前 {state} 用 /自动加好友 on 或 off"


async def cmd_members(rest: str, uid: int, gid: int) -> str:
    target, err = _need_int(rest, "用法 /群成员 群号")
    if err:
        return err
    data, e = await groupadmin.call("get_group_member_list", group_id=target)
    if e:
        return f"失败 {e}"
    names = [str(m.get("card") or m.get("nickname") or m.get("user_id")) for m in (data or [])]
    return f"群 {target} 有 {len(names)} 人\n" + " ".join(names[:20])


async def cmd_notice(rest: str, uid: int, gid: int) -> str:
    parts = rest.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return "用法 /公告 群号 内容"
    _, e = await groupadmin.call("_send_group_notice", group_id=int(parts[0]), content=parts[1])
    return "公告发了" if not e else f"失败 {e}"


async def cmd_recall(rest: str, uid: int, gid: int) -> str:
    mid, err = _need_int(rest, "用法 /撤回 消息ID")
    if err:
        return err
    _, e = await groupadmin.call("delete_msg", message_id=mid)
    return "撤回了" if not e else f"失败 {e}"


async def cmd_leave(rest: str, uid: int, gid: int) -> str:
    target, err = _need_int(rest, "用法 /退群 群号")
    if err:
        return err
    groupadmin.set_pending(uid, {"kind": "leave_group", "group_id": target})
    return f"确定退群 {target} 回 /确认"


async def cmd_kick(rest: str, uid: int, gid: int, ats=None) -> str:
    parts = rest.split()
    if not parts or not parts[0].isdigit():
        return "用法 /踢人 群号 QQ号 或 /踢人 群号 @某人"
    g = int(parts[0])
    if len(parts) > 1 and parts[1].isdigit():
        u = int(parts[1])
    elif ats:
        u = int(ats[0])
    else:
        return "用法 /踢人 群号 QQ号 或 /踢人 群号 @某人"
    groupadmin.set_pending(uid, {"kind": "kick_member", "group_id": g, "user_id": u})
    return f"确定踢 {u} 回 /确认"


async def cmd_mute(rest: str, uid: int, gid: int, ats=None) -> str:
    parts = rest.split()
    if not parts or not parts[0].isdigit():
        return "用法 /禁言 群号 QQ号 分钟 或 /禁言 群号 @某人 分钟"
    g = int(parts[0])
    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
        u, m = int(parts[1]), int(parts[2])
    elif ats and parts[-1].isdigit():
        u, m = int(ats[0]), int(parts[-1])
    else:
        return "用法 /禁言 群号 QQ号 分钟 或 /禁言 群号 @某人 分钟"
    _, e = await groupadmin.call("set_group_ban", group_id=g, user_id=u, duration=max(1, m) * 60)
    return f"已禁言 {u} {m}分钟" if not e else f"失败 {e}"


async def cmd_unmute(rest: str, uid: int, gid: int, ats=None) -> str:
    parts = rest.split()
    if not parts or not parts[0].isdigit():
        return "用法 /解禁 群号 QQ号 或 /解禁 群号 @某人"
    g = int(parts[0])
    if len(parts) > 1 and parts[1].isdigit():
        u = int(parts[1])
    elif ats:
        u = int(ats[0])
    else:
        return "用法 /解禁 群号 QQ号 或 /解禁 群号 @某人"
    _, e = await groupadmin.call("set_group_ban", group_id=g, user_id=u, duration=0)
    return "已解禁" if not e else f"失败 {e}"


async def cmd_card(rest: str, uid: int, gid: int, ats=None) -> str:
    parts = rest.split(maxsplit=2)
    if not parts or not parts[0].isdigit():
        return "用法 /名片 群号 QQ号 新名字 或 /名片 群号 @某人 新名字"
    g = int(parts[0])
    if len(parts) >= 3 and parts[1].isdigit():
        u, name = int(parts[1]), parts[2]
    elif ats and len(parts) >= 2:
        u, name = int(ats[0]), parts[-1]
    else:
        return "用法 /名片 群号 QQ号 新名字 或 /名片 群号 @某人 新名字"
    _, e = await groupadmin.call("set_group_card", group_id=g, user_id=u, card=name)
    return "改好了" if not e else f"失败 {e}"


async def cmd_group_name(rest: str, uid: int, gid: int) -> str:
    parts = rest.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return "用法 /群名 群号 新群名"
    _, e = await groupadmin.call("set_group_name", group_id=int(parts[0]), group_name=parts[1])
    return "群名已改" if not e else f"失败 {e}"


async def cmd_whole_ban(rest: str, uid: int, gid: int) -> str:
    parts = rest.split()
    if len(parts) < 2 or not parts[0].isdigit():
        return "用法 /全员禁言 群号 on|off"
    enable = parts[1].lower() in ("on", "开", "true", "1")
    _, e = await groupadmin.call("set_group_whole_ban", group_id=int(parts[0]), enable=enable)
    return ("已开启" if enable else "已关闭") if not e else f"失败 {e}"


# ---------- 互动 ----------
async def cmd_like(rest: str, uid: int, gid: int, ats=None) -> str:
    target, err = _target(rest, ats, "用法 /点赞 QQ号 或 /点赞 @某人")
    if err:
        return err
    _, e = await groupadmin.call("send_like", user_id=target, times=10)
    return "赞了" if not e else f"失败 {e}"


async def cmd_poke(rest: str, uid: int, gid: int, ats=None) -> str:
    target, err = _target(rest, ats, "用法 /戳 QQ号 或 /戳 @某人")
    if err:
        return err
    if gid:
        _, e = await groupadmin.call("group_poke", group_id=gid, user_id=target)
    else:
        _, e = await groupadmin.call("friend_poke", user_id=target)
    return "戳了" if not e else f"失败 {e}"


async def cmd_remind(rest: str, uid: int, gid: int) -> str:
    parts = rest.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return "用法 /提醒 分钟 内容"
    minutes, text = int(parts[0]), parts[1]
    target_uid, target_gid = uid, gid

    async def _fire() -> None:
        await asyncio.sleep(minutes * 60)
        await _say(target_uid, target_gid, f"提醒你 {text}")

    asyncio.create_task(_fire())
    return f"{minutes}分钟后提醒你"


async def cmd_clear_memory(rest: str, uid: int, gid: int) -> str:
    from . import facts, memsum

    key = f"user:{uid}"
    a = memory.clear(key)
    b = memsum.clear(key)
    c = facts.clear(str(uid))
    return "已清空你的记忆" if (a or b or c) else "本来就没有记忆"


async def cmd_forget(rest: str, uid: int, gid: int) -> str:
    from . import facts

    n = facts.remove(str(uid), rest.strip())
    return f"删了{n}条记忆" if n else "没找到匹配的"


# ---------- DSH ----------
async def cmd_dsh(rest: str, uid: int, gid: int) -> str:
    # 第一道：身份必须是主人
    if int(uid) != admins.OWNER:
        return f"DSH 只有主人 {admins.OWNER} 能用 你是 {uid}"

    task = rest.strip()
    if not task:
        return "用法 /dsh 要它做的事"

    # 第二道：挂起等 /确认 且只能主人确认
    groupadmin.set_pending(
        uid, {"kind": "code_task", "prompt": task, "uid": uid, "gid": gid, "owner": admins.OWNER}
    )
    return (
        f"身份 {uid}\n"
        f"确认让DSH在服务器上执行吗（仅限主人 {admins.OWNER}）\n"
        f"{task[:80]}\n回 /确认"
    )


def _dsh_sessions(limit: int = 5) -> List[str]:
    base = Path("/root/.dsh/sessions")
    if not base.exists():
        return []
    cands = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        for sess in d.glob("session-*"):
            cands.append((sess.stat().st_mtime, sess.name))
    cands.sort(reverse=True)
    return [name for _, name in cands[:limit]]


async def cmd_dsh_session(rest: str, uid: int, gid: int) -> str:
    if int(uid) != admins.OWNER:
        return "这个只有主人能用"
    sid = settings.dsh_session()
    return f"当前 DSH 会话\n{sid}" if sid else "还没有 DSH 会话 下一条 /dsh 会自动开一个"


async def cmd_dsh_switch(rest: str, uid: int, gid: int) -> str:
    if int(uid) != admins.OWNER:
        return "这个只有主人能用"
    sid = rest.strip()
    if not sid:
        sessions = _dsh_sessions()
        if not sessions:
            return "没找到会话 直接用 /dsh 开一个"
        options = []
        for name in sessions:
            async def _pick(n=name):
                settings.set_dsh_session(n)
                return f"切到 {n}"

            options.append((name.replace("session-", "")[:12], _pick))
        return _set_choices(uid, "切到哪个 DSH 会话", options)
    if not sid.startswith("session-"):
        return "会话ID应该是 session- 开头"
    settings.set_dsh_session(sid)
    return f"切到 {sid}"


async def cmd_dsh_new(rest: str, uid: int, gid: int) -> str:
    if int(uid) != admins.OWNER:
        return "这个只有主人能用"
    settings.clear_dsh_session()
    return "已清空 下一条 /dsh 会开新会话"


async def cmd_balance(rest: str, uid: int, gid: int) -> str:
    if int(uid) != admins.OWNER:
        return "这个只有主人能用"
    from .ai import api_base, api_key

    base = api_base()
    root = base[:-3] if base.endswith("/v1") else base
    headers = {"Authorization": f"Bearer {api_key()}"}

    async with httpx.AsyncClient(timeout=25) as client:
        try:
            r = await client.get(f"{root}/user/balance", headers=headers)
            if r.status_code == 200:
                d = r.json()
                info = (d.get("balance_infos") or [{}])[0]
                return f"余额 {info.get('total_balance')} {info.get('currency')} 可用 {d.get('is_available')}"
        except Exception:  # noqa: BLE001
            pass
        try:
            r = await client.get(f"{base}/usage", headers=headers)
            if r.status_code == 200:
                d = r.json()
                today = (d.get("daily_usage") or [{}])[0]
                unit = d.get("unit") or ""
                return (
                    f"余额 {d.get('balance')} {unit}\n"
                    f"今日请求 {today.get('requests', '-')} 次 "
                    f"token {today.get('total_tokens', '-')}"
                )
        except Exception:  # noqa: BLE001
            pass
    return "这个接口查不到余额"


async def cmd_endpoint(rest: str, uid: int, gid: int) -> str:
    if int(uid) != admins.OWNER:
        return "这个只有主人能用"
    from .ai import api_base, api_key

    parts = rest.split()
    if not parts:
        key = api_key()
        masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "未设置"
        return f"接口 {api_base()}\n密钥 {masked}"
    if len(parts) < 2:
        return "用法 /接口 https://xxx sk-xxx"
    settings.set_api_base(parts[0])
    settings.set_api_key(parts[1])
    return f"接口已换成 {parts[0]}"


# 会碰到服务器或凭证的，只有主人能用
OWNER_ONLY = {"dsh", "dsh会话", "dsh切换", "dsh新", "接口", "余额", "设全局人格"}

COMMANDS: Dict[str, Callable] = {
    "帮助": cmd_help, "help": cmd_help,
    "模型": cmd_model, "推理": cmd_effort, "联网": cmd_web,
    "状态": cmd_status, "op": cmd_op, "deop": cmd_deop, "ops": cmd_ops,
    "白名单": cmd_wl, "白名单删": cmd_wl_del,
    "加群": cmd_wl, "加人": cmd_wl, "删群": cmd_wl_del, "删人": cmd_wl_del,
    "黑名单": cmd_bl, "黑名单删": cmd_bl_del,
    "拉黑": cmd_bl, "解黑": cmd_bl_del,
    "会话": cmd_sessions, "活跃": cmd_wake, "我是谁": cmd_whoami,
    "好感": cmd_affinity,
    "有哪些人格": cmd_personas, "切换人格": cmd_switch_persona,
    "人格": cmd_show_persona, "设人格": cmd_set_persona,
    "设全局人格": cmd_set_global_persona,
    "导入表情": cmd_import_stickers, "表情": cmd_stickers, "删表情": cmd_del_sticker,
    "主动": cmd_proactive,
    "自动进群": cmd_auto_join, "自动加好友": cmd_auto_friend,
    "群成员": cmd_members, "公告": cmd_notice, "撤回": cmd_recall,
    "退群": cmd_leave, "踢人": cmd_kick, "禁言": cmd_mute, "解禁": cmd_unmute,
    "名片": cmd_card, "群名": cmd_group_name, "全员禁言": cmd_whole_ban,
    "点赞": cmd_like, "戳": cmd_poke, "提醒": cmd_remind,
    "忘记": cmd_forget, "清记忆": cmd_clear_memory, "记忆": cmd_sessions, "唤醒": cmd_wake,
    "dsh": cmd_dsh,
    "dsh会话": cmd_dsh_session, "dsh切换": cmd_dsh_switch, "dsh新": cmd_dsh_new,
    "余额": cmd_balance, "接口": cmd_endpoint,
}


async def dispatch(query: str, uid: int, gid: int, ats=None) -> str:
    parts = query.split(maxsplit=1)
    word = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    handler = COMMANDS.get(word)
    if handler is None:
        return "没这个命令 发 /帮助 看列表"

    lv = _level(uid)
    if lv == "user" and word not in USER_CMDS:
        return "这个只有管理员能用 直接说话就行"
    if word in OWNER_ONLY and lv != "owner":
        return "这个只有主人能用 机器人管理员不碰服务器"

    import inspect

    kwargs = {}
    if "ats" in inspect.signature(handler).parameters:
        kwargs["ats"] = ats or []
    return await handler(rest, uid, gid, **kwargs)


async def _is_slash(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().startswith("/")


nlu = on_message(rule=Rule(_is_slash), priority=6, block=True)


@nlu.handle()
async def _handle(event: MessageEvent, text: str = EventPlainText()) -> None:
    query = text.strip().lstrip("/").strip()
    if not query:
        await nlu.finish("斜杠后面说点啥")

    gid = int(getattr(event, "group_id", 0) or 0)
    uid = int(event.user_id)

    ats = []
    for seg in event.get_message():
        if seg.type == "at":
            qq = str(seg.data.get("qq", ""))
            if qq.isdigit():
                ats.append(int(qq))

    try:
        reply = await dispatch(query, uid, gid, ats)
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error("斜杠命令执行失败")
        await nlu.finish("执行出错了 看下日志")
        return

    await nlu.finish(reply)


def _has_choice(event: MessageEvent) -> bool:
    text = event.get_plaintext().strip()
    if not text.isdigit():
        return False
    ent = _CHOICES.get(int(event.user_id))
    if not ent or time.time() - ent["at"] > _CHOICE_TTL:
        return False
    return 1 <= int(text) <= len(ent["options"])


pick = on_message(rule=Rule(_has_choice), priority=7, block=True)


@pick.handle()
async def _handle_pick(event: MessageEvent) -> None:
    uid = int(event.user_id)
    ent = _CHOICES.pop(uid, None)
    if not ent:
        await pick.finish()
        return
    idx = int(event.get_plaintext().strip()) - 1
    options = ent["options"]
    if idx < 0 or idx >= len(options):
        await pick.finish(f"只有 {len(options)} 个选项")
        return
    _, fn = options[idx]
    try:
        reply = await fn()
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error("选项执行失败")
        await pick.finish("执行出错了")
        return
    await pick.finish(reply)


USER_HELP = (
    "你能用的\n"
    "· 直接说话 我就陪你聊\n"
    "· 群里 @我 唤醒后 5 分钟内都能聊\n"
    "· 发图 / 表情包 我也能看\n"
    "· /我是谁 看自己的号\n"
    "· /好感 看我对你的好感度\n"
    "· /人格 看我现在的设定\n"
    "· /切换人格 换成预制人格\n"
    "· /帮助 再喊一次这个菜单\n\n"
    "改设置 群管理 派活给 DSH 这些要管理员才行的哦"
)


# ---------- 等待用户输入（填 Key / 改 URL） ----------
_AWAIT: Dict[int, tuple] = {}
_AWAIT_TTL = 120


def _awaiting(event: MessageEvent) -> bool:
    uid = int(event.user_id)
    item = _AWAIT.get(uid)
    if not item:
        return False
    if time.time() - item[1] > _AWAIT_TTL:
        _AWAIT.pop(uid, None)
        return False
    return not event.get_plaintext().strip().startswith("/")


await_input = on_message(rule=Rule(_awaiting), priority=7, block=True)


@await_input.handle()
async def _handle_await(event: MessageEvent) -> None:
    uid = int(event.user_id)
    kind, _, target = _AWAIT.pop(uid)
    text = event.get_plaintext().strip()

    if kind == "newkey":
        await await_input.finish(await _save_provider_key(uid, str(target), text))

    prov = providers.get(str(target)) if target else None
    if kind == "key":
        settings.set_api_key(text)
        if prov:
            providers.upsert(prov["name"], prov["base"], text)
        await await_input.finish(f"{target or '当前'} 的 Key 已更新")

    settings.set_api_base(text)
    if prov:
        providers.upsert(prov["name"], text, prov.get("key", ""))
    await await_input.finish(f"{target or '当前'} 的地址已改成 {text}")
