# -*- coding: utf-8 -*-
"""把任务丢给 DSH 跑：headless 模式，当前目录，尽量复用同一个会话。"""

import asyncio
import json
import os
from typing import Optional, Tuple

from nonebot import get_driver, logger

WORKDIR = "/root/大肥鱼"


async def _run(prompt: str, session_id: Optional[str], timeout: int) -> Tuple[str, Optional[str], Optional[str]]:
    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = str(getattr(get_driver().config, "deepseek_api_key", ""))

    args = ["dsh", "headless", "--json"]
    if session_id:
        args += ["--session-id", session_id]
    args.append(prompt)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=WORKDIR,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:  # noqa: BLE001
        return "", None, f"启动不了 dsh: {e}"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return "", session_id, f"跑了超过{timeout // 60}分钟 我掐了"

    text_parts, noise = [], []
    final_text, sid, err = None, None, None

    for line in out.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            if line:
                noise.append(line)
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = evt.get("type")
        if kind == "session":
            sid = evt.get("sessionId") or sid
        elif kind == "text":
            text_parts.append(evt.get("text") or "")
        elif kind == "final":
            final_text = evt.get("text") or "".join(text_parts)
        elif kind == "error":
            err = str(evt.get("message") or "").strip()

    text = (final_text or "".join(text_parts)).strip()
    if text:
        return text, sid, None
    if err:
        return "", sid, err
    tail = " / ".join(noise[-2:])[:200]
    return "", sid, f"跑完了 没输出（退出码 {proc.returncode}）{(' ' + tail) if tail else ''}"


async def run_task(
    prompt: str, session_id: Optional[str] = None, timeout: int = 900
) -> Tuple[str, Optional[str], bool]:
    text, sid, err = await _run(prompt, session_id, timeout)

    # 会话被别的进程占着 就开个新的重跑
    if err and "already owned" in err and session_id:
        logger.warning(f"DSH 会话被占用 改开新会话: {err}")
        text, sid, err = await _run(prompt, None, timeout)
        if text:
            text += "\n（原会话被占用 已开新会话）"

    if err:
        return err, sid, "分钟" in err
    return text or "跑完了 没输出", sid, False
