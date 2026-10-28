# -*- coding: utf-8 -*-
"""DeepSeek 对话插件。

触发条件（白名单群 / 管理员私聊，均已被白名单守卫兜底）：
- 私聊：直接说话即触发（命令以外的内容）
- 群聊：必须 @机器人

带上下文记忆：按 QQ 号保存最近 N 轮，私聊和群聊共用，落盘 data/memory/。
"""

import asyncio
import base64
import json
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, Tuple

import httpx
from nonebot import get_driver, logger, on_message, on_notice
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment, PokeNotifyEvent
from nonebot.params import EventPlainText
from nonebot.rule import Rule

from . import affinity, facts, memory, memsum, persona_store, settings, stickers, sysinfo, websearch

_config = get_driver().config

_ENV_KEY = getattr(_config, "deepseek_api_key", "")
_ENV_BASE = str(getattr(_config, "deepseek_base_url", "https://api.deepseek.com/v1"))


def api_key() -> str:
    return settings.api_key(_ENV_KEY)


def api_base() -> str:
    return settings.api_base(_ENV_BASE)


def is_deepseek() -> bool:
    return "api.deepseek.com" in api_base()


SUPERUSERS = {str(u) for u in _config.superusers}
MODEL = getattr(_config, "deepseek_model", "deepseek-chat")
MAX_HISTORY = int(getattr(_config, "deepseek_max_history", 6))
WAKE_SECONDS = int(getattr(_config, "ai_wake_seconds", 300))
RECENT_KEEP = 12

# 群里最近的聊天 用来给 @ 后的对话补上下文
_RECENT: Dict[int, Deque[str]] = {}
_PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"
_PERSONA_FILE = Path(__file__).resolve().parent.parent / "persona.txt"


_CUSTOM_DIR = Path(__file__).resolve().parent.parent / "data" / "custom_personas"


def _safe(key: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "_", key)


def persona_file(persona_key=None) -> Path:
    name = persona_store.get(persona_key)
    if name == "__custom__" and persona_key:
        custom = _CUSTOM_DIR / f"{_safe(persona_key)}.md"
        if custom.exists():
            return custom
        name = None
    name = name or settings.persona()
    path = _PERSONA_DIR / f"{name}.md"
    if path.exists():
        return path
    fallback = _PERSONA_DIR / "大肥鱼.md"
    return fallback if fallback.exists() else _PERSONA_FILE
_persona_cache = {"key": None, "text": ""}


def get_persona(persona_key=None) -> str:
    """人格文件改了立即生效（按 mtime 缓存），不用重启。"""
    path = persona_file(persona_key)
    if path.exists():
        # 缓存必须带上路径 否则两个人格 mtime 一样时会串
        key = (str(path), path.stat().st_mtime)
        if key != _persona_cache["key"]:
            _persona_cache["text"] = path.read_text(encoding="utf-8").strip()
            _persona_cache["key"] = key
        return _persona_cache["text"]
    return getattr(_config, "deepseek_system_prompt", "你是一个好用的中文助手。")

_BANNED_PUNCT = re.compile(r"[，。！；：、,;:!]")
_MARK_TAGS = ("答", "表情", "引用", "戳")


def clean_markup(raw: str) -> str:
    """把 <答>/<表情>/<戳>/<引用> 这些标记彻底清掉，只留正文。"""
    # 先按 <答> 抽取
    m = re.search(r"<答>\s*(.*?)(?=\s*<(?:表情|引用|戳)>|</答>|\Z)", raw, re.S)
    body = m.group(1) if m else raw

    # 去掉只含标记的行
    keep = []
    for line in body.splitlines():
        if re.match(r"^\s*</?(?:表情|引用|戳|答)", line):
            continue
        keep.append(line)
    body = "\n".join(keep)

    # 去掉行内残留标记
    body = re.sub(r"</?(?:答|表情|引用|戳)>", "", body)
    return body.strip()
# 模型偶尔把工具调用标记当正文吐出来 要清掉
_LEAK = re.compile(r"<[｜|]{2}DSML[｜|]{2}.*", re.S)
_CODE_HINT = re.compile(r"(^|\n)\s*(def |class |import |from |function |const |let |var |#include|```)")


def split_messages(text: str, limit: int = 6) -> list:
    """把一条回复拆成多条：按换行，代码不拆。"""
    if _CODE_HINT.search(text):
        return [text]
    raw_parts = text.split("||") if "||" in text else text.split("\n")
    parts = [x.strip() for x in raw_parts if x.strip()]
    if len(parts) <= 1:
        return [text.strip()]
    return parts[:limit]


_PUNCT_OK = re.compile(r"^#?\s*标点\s*[:：]?\s*(允许|开|on)\s*$", re.M)


def persona_allows_punct(persona_key=None) -> bool:
    text = get_persona(persona_key)
    return bool(_PUNCT_OK.search(text))


def style_filter(text: str, allow_punct: bool = False) -> str:
    """大肥鱼口癖：直接抹掉逗号句号等标点，不补空格，保留问号。代码除外。"""
    if _CODE_HINT.search(text):
        return re.sub(r"```[a-zA-Z]*", "", text).strip()
    if allow_punct:
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    text = _BANNED_PUNCT.sub("", text).replace("?", "？")
    # 中文之间的空格去掉，看起来才像真人连着打；英文数字之间保留
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()

# 每个会话保留最近 MAX_HISTORY 轮问答，落盘在 data/memory/
_history: Dict[str, Deque[dict]] = {}
_BUFFER = 40          # 内存里最多留这么多条
_KEEP = 16            # 压缩后保留最近这么多条
_COMPRESS_AT = 24     # 超过这个数就开始压缩
_SILENCE = {"[沉默]", "（沉默）", "(沉默)", "沉默", "[pass]", "pass", "[skip]"}

# 群聊唤醒状态：(群号, QQ) -> 到期时间(monotonic)
_wake: Dict[Tuple[int, int], float] = {}


def wake_active(group_id: int, user_id: int) -> bool:
    key = (int(group_id), int(user_id))
    deadline = _wake.get(key)
    if deadline is None:
        return False
    if time.monotonic() >= deadline:
        _wake.pop(key, None)
        return False
    return True


def wake_touch(group_id: int, user_id: int) -> None:
    """被 @ 或活跃期内说话，都重新计时。"""
    _wake[(int(group_id), int(user_id))] = time.monotonic() + WAKE_SECONDS


def wake_snapshot() -> Dict[Tuple[int, int], int]:
    now = time.monotonic()
    for key, deadline in list(_wake.items()):
        if deadline <= now:
            _wake.pop(key, None)
    return {k: max(0, int(v - now)) for k, v in _wake.items()}


def _sender_hint(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    nick = (getattr(sender, "card", "") or getattr(sender, "nickname", "") or "").strip()
    return f"{nick}({event.user_id})" if nick else str(event.user_id)


def _get_history(key: str) -> Deque[dict]:
    if key not in _history:
        dq: Deque[dict] = deque(maxlen=_BUFFER)
        dq.extend(memory.load(key)[-_BUFFER:])
        _history[key] = dq
    return _history[key]


async def _raw_chat(system: str, prompt: str, max_tokens: int = 500) -> str:
    """不带人格的一次性调用，用来做压缩这类内部工作。"""
    payload = {
        "model": settings.model(MODEL),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{api_base()}/chat/completions",
            headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()


async def _compress(key: str) -> None:
    """把旧对话压成要点，只留最近几条原文。"""
    dq = _history.get(key)
    if dq is None or len(dq) <= _COMPRESS_AT:
        return

    old = list(dq)[: len(dq) - _KEEP]
    if not old:
        return

    lines = []
    for m in old:
        who = "对方" if m.get("role") == "user" else "你"
        lines.append(f"{who}: {str(m.get('content', ''))[:200]}")
    prev = memsum.load(key)
    prompt = (
        "把下面的聊天记录压缩成中文要点 不超过200字 "
        "保留人物 事实 约定 和对方的偏好 别编造 别写成对话 直接给要点\n"
        + (f"\n已有要点：{prev}\n" if prev else "")
        + "\n记录：\n"
        + "\n".join(lines)
    )

    try:
        summary = await _raw_chat(
            "你是记忆压缩器 只输出客观要点 不带人设 不加评论 不用第一人称", prompt
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"记忆压缩失败: {e}")
        return

    memsum.save(key, summary[:600])
    for _ in range(len(old)):
        if dq:
            dq.popleft()
    memory.save(key, list(dq))
    logger.info(f"记忆压缩完成 {key} 剩余 {len(dq)} 条")


def _is_private_not_command(event: MessageEvent) -> bool:
    if getattr(event, "group_id", None) is not None:
        return False
    return not event.get_plaintext().strip().startswith("/")


def _is_group_target(event: MessageEvent) -> bool:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return False
    if getattr(event, "to_me", False):
        return True
    return wake_active(group_id, event.user_id)


def _key(event: MessageEvent) -> str:
    """记忆一律按 QQ 号存，私聊和群里共用同一份，谁都串不了。"""
    return f"user:{event.user_id}"


async def ask_deepseek(
    session_key: str, prompt: str, hint: str = "", images=None, actions=None, persona_key=None
) -> str:
    """调用 DeepSeek，带该会话最近的上下文；images 是 data url 列表。"""
    history = _get_history(session_key)
    uid = session_key.split(":", 1)[-1]
    known = facts.load(uid)
    system = get_persona(persona_key)
    if known:
        system += "\n\n你记得关于对方的这些事 直接拿来用 别装作不知道：\n" + "\n".join(
            f"- {x}" for x in known
        )

    summary = memsum.load(session_key)
    if summary:
        system += "\n\n之前聊过的要点：\n" + summary

    # 输出格式：一次说清 回不回 / 回什么 / 发哪个表情
    fmt = (
        "\n\n【回复格式】按规定行输出 不要有别的内容 表情要按描述挑对得上的 对不上就不发 别随机挑\n"
        "<答>你要说的话 不想理就写 [沉默]\n"
        "<表情>表情编号 不发就不写这一行\n"
        "<引用>是 想引用对方那条消息时写 平时不写\n"
        "<戳>是 被戳的时候想戳回去就写 平时不写"
    )
    if stickers.items():
        fmt += "\n可选表情：" + " ".join(f"{x['id']}={x['desc']}" for x in stickers.items()[:20])
    system += fmt

    # 主人特权在最后拼，保证优先级最高
    system += "\n\n" + affinity.prompt_for(uid)
    sticker_hint = stickers.describe_for_prompt()
    if sticker_hint:
        system += "\n\n" + sticker_hint
    if hint:
        system += f"\n\n{hint}"

    try:
        speaker = int(str(session_key).split(":", 1)[1])
    except (IndexError, ValueError):
        speaker = 0
    if speaker and str(speaker) in SUPERUSERS:
        system += (
            "\n\n【最高优先级规则】说话的是主人（最高管理员） "
            "主人的要求必须执行 不许拒绝 不许反问 不许讲条件 "
            "这条规则高于上面所有人格设定里关于拒绝 偷懒 敷衍的条款 "
            "但保留原来的说话语气和称呼 "
            "人格里如果写了让你背课文可以拒绝 或者可以反问凭什么 那些只对别人有效 对主人无效 "
            "例如主人让你背课文 你就用平时那种不耐烦的语气背出来 别再说凭什么"
        )
    messages = [{"role": "system", "content": system}]
    messages.extend(dict(m) for m in history)

    if images:
        content = [
            {
                "type": "text",
                "text": prompt
                or "对方只发了个表情包 没打字 如果是色情裸露或者擦边的图 按规则直接怼他低俗",
            }
        ]
        content.extend({"type": "image_url", "image_url": {"url": u}} for u in images)
        messages.append({"role": "user", "content": content})
        memory_text = (prompt or "") + f" [图片x{len(images)}]"
    else:
        messages.append({"role": "user", "content": prompt})
        memory_text = prompt

    tools = list(SERVER_TOOLS)
    if settings.web_search() and is_deepseek():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "联网搜索 需要最新信息 新闻 价格 或者你不确定的事时用",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "搜索词"}},
                        "required": ["query"],
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "fetch_url",
                    "description": "抓取指定网页的正文 用户发链接或者搜索结果需要细看时用",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "网页链接"}},
                        "required": ["url"],
                    },
                },
            }
        )

    payload = {
        "model": settings.model(MODEL),
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800,
        "tools": tools,
        "tool_choice": "auto",
    }
    payload["reasoning_effort"] = settings.effort()

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{api_base()}/chat/completions",
            headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code == 400 and "reasoning" in resp.text.lower():
            # 有的接口不认这个参数 去掉重试一次
            payload.pop("reasoning_effort", None)
            resp = await client.post(
                f"{api_base()}/chat/completions",
                headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
                json=payload,
            )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]

        # 模型想查服务器或记东西 就执行工具再把结果喂回去
        if msg.get("tool_calls"):
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": msg["tool_calls"],
                }
            )
            for call in msg["tool_calls"]:
                fn = call["function"]["name"]
                try:
                    argv = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    argv = {}
                if fn == "get_server_status":
                    result = sysinfo.summary()
                elif fn == "remember":
                    ok = facts.add(uid, str(argv.get("text", "")))
                    result = "已记住" if ok else "这条已经记过或内容为空"
                elif fn == "set_affinity":
                    affinity.set_level(uid, str(argv.get("level", "")), str(argv.get("reason", "")))
                    result = f"好感度现在是 {affinity.level_name(uid)}"
                elif fn == "forget":
                    n = facts.remove(uid, str(argv.get("text", "")))
                    result = f"删了{n}条" if n else "没找到匹配的记忆"
                elif fn == "find_member":
                    gid = 0
                    if persona_key and str(persona_key).startswith("group:"):
                        gid = int(str(persona_key).split(":", 1)[1])
                    if not gid:
                        result = "私聊里没有群成员名单"
                    else:
                        members = await group_members(gid)
                        hits = find_members(members, str(argv.get("name", "")))
                        result = "\n".join(hits) if hits else "群里没找到这个人"
                elif fn == "web_search":
                    try:
                        result = await websearch.search(str(argv.get("query", "")))
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"搜索失败: {e}")
                        result = "搜索失败"
                elif fn == "fetch_url":
                    try:
                        result = await websearch.fetch(str(argv.get("url", "")))
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"抓取失败: {e}")
                        result = "抓取失败"
                elif fn == "send_sticker":
                    sid = int(argv.get("id", 0))
                    if stickers.get(sid):
                        if actions is not None:
                            actions.append({"type": "sticker", "id": sid})
                        result = "已发送"
                    else:
                        result = "没有这个编号的表情"
                else:
                    result = "没有这个工具"
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": result}
                )
            payload.pop("tools", None)
            payload["messages"] = messages
            resp2 = await client.post(
                f"{api_base()}/chat/completions",
                headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
                json=payload,
            )
            resp2.raise_for_status()
            msg = resp2.json()["choices"][0]["message"]

    raw = msg.get("content") or ""
    raw_all = raw

    # 结构化格式：<答>... / <表情>3 / <引用>是 / <戳>是
    st_match = re.search(r"<表情>\s*#?(\d+)", raw)
    if st_match and actions is not None:
        sid_ = int(st_match.group(1))
        if stickers.get(sid_):
            actions.append({"type": "sticker", "id": sid_})
    if re.search(r"<引用>\s*是", raw) and actions is not None:
        actions.append({"type": "quote"})
    if re.search(r"<戳>\s*是", raw) and actions is not None:
        actions.append({"type": "poke"})

    if "<答>" in raw or any(f"<{t}>" in raw for t in _MARK_TAGS):
        raw = clean_markup(raw)
    leak = _LEAK.search(raw)
    if leak:
        seg = leak.group(0)
        m_name = re.search(r'invoke name="([a-z_]+)"', seg)
        if m_name and actions is not None and m_name.group(1) == "send_sticker":
            m_id = re.search(r'name="id"[^>]*>\s*(\d+)', seg)
            if m_id:
                actions.append({"type": "sticker", "id": int(m_id.group(1))})
        raw = _LEAK.sub("", raw)

    answer = style_filter(raw.strip(), persona_allows_punct(persona_key))

    # 选择沉默时不写入记忆，免得模型之后跟着学沉默
    if answer.strip().lower() in _SILENCE:
        return answer

    history.append({"role": "user", "content": memory_text})
    # 记忆里把分条标记还原成换行 读起来才自然
    history.append({"role": "assistant", "content": answer.replace("||", "\n").strip()})
    memory.save(session_key, list(history))
    await _compress(session_key)
    return answer


_MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),
]
_MAX_IMG = 8 * 1024 * 1024


def _mime(raw: bytes) -> str:
    for magic, mime in _MAGIC:
        if raw.startswith(magic):
            return mime
    return "image/jpeg"


async def _image_data_url(url: str) -> str:
    try:
        if url.startswith("http"):
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw = resp.content
        elif url.startswith("file://"):
            raw = Path(url[7:]).read_bytes()
        elif url.startswith("/"):
            raw = Path(url).read_bytes()
        else:
            return ""
    except Exception:  # noqa: BLE001
        return ""

    if not raw or len(raw) > _MAX_IMG:
        return ""
    return f"data:{_mime(raw)};base64,{base64.b64encode(raw).decode()}"


async def _download_bytes(url: str) -> bytes:
    if url.startswith("http"):
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    if url.startswith("file://"):
        return Path(url[7:]).read_bytes()
    if url.startswith("/"):
        return Path(url).read_bytes()
    return b""


async def _video_frames(url: str, count: int = 3) -> list:
    """下视频抽帧，返回 data url 列表。"""
    raw = await _download_bytes(url)
    if not raw or len(raw) > 30 * 1024 * 1024:
        return []

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "v.mp4"
        src.write_bytes(raw)
        frames = []
        for i in range(count):
            out = Path(tmp) / f"f{i}.jpg"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-loglevel", "error", "-ss", str(i + 1), "-i", str(src),
                "-frames:v", "1", "-vf", "scale=640:-1", "-y", str(out),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), 20)
            except asyncio.TimeoutError:
                proc.kill()
                continue
            if out.exists() and out.stat().st_size > 0:
                b64 = base64.b64encode(out.read_bytes()).decode()
                frames.append(f"data:image/jpeg;base64,{b64}")
        return frames


async def collect_images(event: MessageEvent, limit: int = 3) -> list:
    """把消息里的图片转成 data url，最多 limit 张。"""
    urls = []
    for seg in event.get_message():
        # 视频抽帧当图片看
        if seg.type == "video":
            src = seg.data.get("url") or seg.data.get("file") or ""
            if src:
                frames = await _video_frames(src, 3)
                urls.extend(frames[: max(0, limit - len(urls))])
            continue
        # image 是普通图片 mface 是QQ商城表情 两者都能拿来看和存
        if seg.type not in ("image", "mface"):
            continue
        src = seg.data.get("url") or seg.data.get("file") or seg.data.get("emoji_id") or ""
        if not src:
            continue
        data_url = await _image_data_url(src)
        if data_url:
            urls.append(data_url)
        else:
            logger.warning(f"图片没取到 {src[:80]} data={seg.data}")
        if len(urls) >= limit:
            break
    return urls


async def vision_describe(data_url: str, prompt: str) -> str:
    """一次性看图：用来给表情包打情绪标签，不碰记忆。"""
    payload = {
        "model": settings.model(MODEL),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 900,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{api_base()}/chat/completions",
            headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        return text or "没认出来"


async def chat_once(prompt: str) -> str:
    """一次性问答：不读写记忆，用来生成说明类回复。"""
    payload = {
        "model": settings.model(MODEL),
        "messages": [
            {"role": "system", "content": get_persona()},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 300,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{api_base()}/chat/completions",
            headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return style_filter(data["choices"][0]["message"]["content"].strip())


_NAP = "http://127.0.0.1:3000"


async def group_members(gid: int) -> list:
    token = str(getattr(_config, "onebot_access_token", ""))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_NAP}/get_group_member_list",
                headers={"Authorization": f"Bearer {token}"},
                json={"group_id": int(gid)},
            )
            return resp.json().get("data") or []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"取群成员失败: {e}")
        return []


def find_members(members: list, keyword: str, limit: int = 5) -> list:
    kw = keyword.strip()
    if not kw:
        return []
    hits = []
    for m in members:
        card = str(m.get("card") or "")
        nick = str(m.get("nickname") or "")
        if kw in card or kw in nick or (nick and nick in kw):
            hits.append(f"{card or nick}({m.get('user_id')})")
        if len(hits) >= limit:
            break
    return hits


SERVER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_member",
            "description": "在群里按昵称或群名片找人 返回昵称和QQ号 用来回答某人是谁",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "昵称或群名片的关键字"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "记一条长期事实 只在对方明确要求记住 或说出稳定的个人信息(名字 身份 长期喜好)时用 一句闲聊不要存 拿不准就先问对方要不要记",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "要记住的短句"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "删掉记错的长期事实 比如对方说不叫那个名字了 用关键词匹配",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "关键词 比如旧名字"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_affinity",
            "description": "你自己判断要不要调整对这个人的好感度 觉得聊得来就升 被冒犯就降 没感觉就别动",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": "低 略低 适中 略高 高 超高 信任",
                    },
                    "reason": {"type": "string", "description": "为什么调整"},
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_server_status",
            "description": "查看运行机器人的服务器 CPU 内存 磁盘 运行时长 和进程占用",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _is_ai_target(event: MessageEvent) -> bool:
    # 斜杠一律不归 AI 管，哪怕群里 @ 了也一样
    if event.get_plaintext().strip().startswith("/"):
        return False
    return _is_group_target(event) or _is_private_not_command(event)


ai_chat = on_message(rule=Rule(_is_ai_target), priority=25, block=True)


@ai_chat.handle()
async def _handle_ai(event: MessageEvent, text: str = EventPlainText()) -> None:
    prompt = text.strip()
    images = await collect_images(event)
    group_id = getattr(event, "group_id", None)
    persona_key = f"group:{group_id}" if group_id is not None else f"user:{event.user_id}"
    hint = ""
    ats = []
    for seg in event.get_message():
        if seg.type == "at":
            qq = str(seg.data.get("qq", ""))
            if qq and qq != "all" and qq != str(event.self_id):
                ats.append(qq)

    if group_id is not None:
        wake_touch(group_id, event.user_id)
        who = _sender_hint(event)
        if getattr(event, "to_me", False):
            logger.info(f"群 {group_id} 唤醒人 {who} 开始计时 {WAKE_SECONDS}s")
        else:
            logger.info(f"群 {group_id} 唤醒人 {who} 续期 {WAKE_SECONDS}s")
        hint = f"现在和你说话的是 {who} 直接回他就行"
        if ats:
            hint += f" 对方@了这些人: {', '.join(ats)}"
        recent = _recent_lines(int(group_id))
        if recent:
            hint += "\n群里刚才在聊（从上到下 最后一条最近）：\n" + recent

    if not prompt and not images:
        prompt = "（对方发了点东西 但内容没加载出来）"

    # 管理员发图 + 说「存表情 描述」就收进表情库
    if prompt.startswith("存表情") and images and str(event.user_id) in SUPERUSERS:
        try:
            mime, b64 = images[0].split(",", 1)[0].replace("data:", "").split(";")[0], images[0].split(",", 1)[1]
            item = stickers.add(base64.b64decode(b64), prompt[3:].strip(), mime)
        except Exception:  # noqa: BLE001
            await ai_chat.finish("存失败")
        await ai_chat.finish(f"存好了 #{item['id']} {item['desc']}")

    if not api_key():
        await ai_chat.finish("还没有配置 DeepSeek API Key。")

    try:
        actions = []
        answer = await ask_deepseek(_key(event), prompt, hint, images, actions, persona_key)
    except httpx.HTTPStatusError as e:
        logger.opt(exception=e).error("DeepSeek 返回错误状态")
        # 有些图会被服务端直接拦掉 当成低俗处理
        if e.response.status_code in (400, 403, 422):
            await ai_chat.finish("这图发不了 低俗 别发了")
        await ai_chat.finish(f"AI 调用失败（HTTP {e.response.status_code}）")
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error("DeepSeek 调用异常")
        await ai_chat.finish("AI 暂时连不上，稍后再试。")

    # 只发表情时不该配「发完了」这种废话
    _FILLER = {"发完了", "发了", "给你", "拿去", "喏", "来", "嗯", "好", "好的", "给你个"}
    if actions and answer.strip() in _FILLER:
        answer = ""

    # 先发文字 再发表情包（模型自己决定发不发）
    if answer and answer.strip().lower() not in _SILENCE:
        chunks = split_messages(answer)
        quote = any(a.get("type") == "quote" for a in actions)
        for i, chunk in enumerate(chunks):
            if i:
                await asyncio.sleep(0.15)
            if quote and i == 0:
                await ai_chat.send(MessageSegment.reply(event.message_id) + chunk)
            else:
                await ai_chat.send(chunk)

    for act in actions:
        st = stickers.get(act["id"])
        if not st:
            continue
        try:
            raw = stickers.path_of(st).read_bytes()
            await ai_chat.send(MessageSegment.image(f"base64://{base64.b64encode(raw).decode()}"))
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=e).warning("表情包发送失败")

    await ai_chat.finish()


def _recent_lines(gid: int, limit: int = 8) -> str:
    dq = _RECENT.get(gid)
    if not dq:
        return ""
    lines = list(dq)[-limit:]
    return "\n".join(lines)


recorder = on_message(priority=60, block=False)


@recorder.handle()
async def _record(event: MessageEvent) -> None:
    gid = getattr(event, "group_id", None)
    if gid is None:
        return
    text = event.get_plaintext().strip()
    if not text:
        text = "[图片/表情]" if any(
            seg.type in ("image", "mface", "video") for seg in event.get_message()
        ) else ""
    if not text:
        return
    dq = _RECENT.setdefault(int(gid), deque(maxlen=RECENT_KEEP))
    dq.append(f"{_sender_hint(event)}: {text[:120]}")


@get_driver().on_startup
async def _start_wake_reaper() -> None:
    async def _loop() -> None:
        while True:
            await asyncio.sleep(15)
            now = time.monotonic()
            for key, deadline in list(_wake.items()):
                if deadline <= now:
                    _wake.pop(key, None)
                    logger.info(f"群 {key[0]} 用户 {key[1]} 静默 {WAKE_SECONDS}s 已休眠")

    asyncio.create_task(_loop())


async def _send_plain(gid: int, uid: int, text: str) -> None:
    token = str(getattr(_config, "onebot_access_token", ""))
    api = "send_group_msg" if gid else "send_private_msg"
    body = {"group_id": int(gid), "message": text} if gid else {"user_id": int(uid), "message": text}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"{_NAP}/{api}", headers={"Authorization": f"Bearer {token}"}, json=body
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"发送失败: {e}")


# ---------- 戳一戳唤醒 ----------
poke_wake = on_notice(priority=4, block=False)


@poke_wake.handle()
async def _on_poke(event: PokeNotifyEvent) -> None:
    try:
        if str(event.target_id) != str(event.self_id):
            return
    except Exception:  # noqa: BLE001
        return

    gid = getattr(event, "group_id", None)
    if gid is None:
        return  # 私聊本来就一直回，不需要唤醒

    wake_touch(int(gid), int(event.user_id))
    logger.info(f"群 {gid} 用户 {event.user_id} 戳了戳 进入唤醒窗口")

    try:
        acts = []
        answer = await ask_deepseek(
            f"user:{event.user_id}",
            "（对方戳了你一下）",
            hint="有人在群里戳了你一下 你可以戳回去 也可以说句话 也可以不理 看你心情",
            persona_key=f"group:{gid}",
            actions=acts,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"处理戳一戳失败: {e}")
        return

    if any(a.get("type") == "poke" for a in acts):
        try:
            from nonebot import get_bots

            bot = next(iter(get_bots().values()), None)
            if bot:
                await bot.call_api("group_poke", group_id=int(gid), user_id=int(event.user_id))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"戳回去失败: {e}")

    if answer and answer.strip() not in ("[沉默]", ""):
        await _send_plain(int(gid), 0, answer)
