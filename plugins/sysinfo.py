# -*- coding: utf-8 -*-
"""服务器资源采集：CPU、内存、磁盘、运行时长、进程占用。

纯读 /proc 和 shutil，不依赖第三方包。
"""

import shutil
import time
from pathlib import Path


def _cpu_percent(interval: float = 0.2) -> float:
    def snap():
        parts = Path("/proc/stat").read_text().split("\n")[0].split()[1:]
        vals = [int(x) for x in parts]
        idle = vals[3] + vals[4]
        return sum(vals), idle

    t1, i1 = snap()
    time.sleep(interval)
    t2, i2 = snap()
    total = t2 - t1
    idle = i2 - i1
    return round((1 - idle / total) * 100, 1) if total else 0.0


def _mem() -> tuple:
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        info[k] = int(v.strip().split()[0])
    total = info["MemTotal"] / 1024 / 1024
    avail = info["MemAvailable"] / 1024 / 1024
    return round(total - avail, 2), round(total, 2)


def _uptime() -> str:
    secs = float(Path("/proc/uptime").read_text().split()[0])
    h, rem = divmod(int(secs), 3600)
    m = rem // 60
    return f"{h}小时{m}分"


def _proc_rss(name: str) -> int:
    """按进程名找常驻内存，单位 MB。"""
    total = 0
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            status = (p / "status").read_text()
        except OSError:
            continue
        if f"Name:\t{name}" in status:
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) // 1024
                    break
    return total


def summary() -> str:
    used, total = _mem()
    du = shutil.disk_usage("/")
    load = Path("/proc/loadavg").read_text().split()[:3]
    cpu = _cpu_percent()
    bot = _proc_rss("python")
    qq = _proc_rss("qq")
    return (
        f"CPU {cpu}% 负载 {' '.join(load)}\n"
        f"内存 {used}G/{total}G ({round(used / total * 100)}%)\n"
        f"磁盘 {du.used / 1024**3:.1f}G/{du.total / 1024**3:.1f}G ({round(du.used / du.total * 100)}%)\n"
        f"运行 {_uptime()} bot {bot}MB qq {qq}MB"
    )
