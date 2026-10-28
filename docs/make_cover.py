import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1680, 1360
BG     = (15, 23, 42)
CARD   = (27, 35, 54)
CARD2  = (22, 30, 46)
BORDER = (55, 70, 92)
TEXT   = (248, 250, 252)
MUTED  = (148, 163, 184)
DIM    = (120, 138, 162)
BLUE   = (96, 165, 250)
GREEN  = (52, 211, 153)
PURPLE = (192, 132, 252)
AMBER  = (251, 191, 36)

PLEX = "/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-%s.ttf"
MONO = "/usr/share/fonts/truetype/ibm-plex/IBMPlexMono-%s.ttf"
CJK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-%s.ttc"

_c = {}
def lf(w, s):
    k = ("l", w, s)
    if k not in _c: _c[k] = ImageFont.truetype(PLEX % w, s)
    return _c[k]

def mf(w, s):
    k = ("m", w, s)
    if k not in _c: _c[k] = ImageFont.truetype(MONO % w, s)
    return _c[k]

def cf(w, s):
    real = "Bold" if w == "Bold" else "Regular"
    k = ("c", real, s)
    if k not in _c: _c[k] = ImageFont.truetype(CJK % real, s, index=2)
    return _c[k]

RUN = re.compile(r"[\x00-\x7f]+|[^\x00-\x7f]+")

def text(d, xy, s, w, size, fill, mono=False, latin=None):
    latin = latin or w
    x, y = xy
    for part in RUN.findall(s):
        if mono and part.isascii():
            f = mf("Regular" if w == "Regular" else "Medium", size)
        elif part.isascii():
            f = lf(latin, size)
        else:
            f = cf(w, size)
        d.text((x, y), part, font=f, fill=fill)
        x += d.textlength(part, font=f)

def width(d, s, w, size, mono=False, latin=None):
    latin = latin or w
    t = 0
    for part in RUN.findall(s):
        if mono and part.isascii():
            f = mf("Medium", size)
        elif part.isascii():
            f = lf(latin, size)
        else:
            f = cf(w, size)
        t += d.textlength(part, font=f)
    return t

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

def box(x, y, w, h, color=None, fill=CARD, r=14):
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=BORDER, width=1)
    if color:
        d.rounded_rectangle([x, y, x + 5, y + h], radius=3, fill=color)

# ===== 标题 =====
text(d, (64, 46), "花花机器人 · 系统架构", "Bold", 40, TEXT)
text(d, (64, 104), "NapCat 协议层 · NoneBot2 业务层 · 大模型接口 · 可选 DSH", "Regular", 17, MUTED)

# ===== 第一行：用户 → NapCat → 业务端 =====
y1, h1 = 168, 250
box(64, y1, 210, h1, BLUE)
text(d, (88, y1 + 24), "QQ 用户", "Bold", 22, TEXT)
for i, s in enumerate(["群友 / 管理员", "私聊 · 群聊", "图片 · 视频 · 表情"]):
    text(d, (88, y1 + 72 + i * 34), s, "Regular", 16, MUTED)

box(400, y1, 300, h1, AMBER)
text(d, (424, y1 + 24), "NapCat", "Bold", 22, TEXT)
text(d, (424, y1 + 60), "QQ 客户端 + OneBot v11", "Regular", 15, MUTED)
for i, s in enumerate(["反向 WS  :8080", "HTTP API  :3000", "WebUI     :6099"]):
    text(d, (424, y1 + 104 + i * 34), s, "Regular", 16, BLUE, mono=True)
text(d, (424, y1 + 208), "扫码登录后常驻", "Regular", 15, DIM)

box(830, y1, 786, h1, GREEN)
text(d, (856, y1 + 24), "NoneBot2", "Bold", 22, TEXT)
text(d, (856 + width(d, "NoneBot2", "Bold", 22) + 12, y1 + 28), "bot.py", "Regular", 15, MUTED, mono=True)
items = [
    "准入：白名单 / 黑名单（群和人分开）",
    "对话：人格 · 记忆 · 压缩 · 好感度",
    "命令：斜杠本地解析，不烧额度",
    "群聊：@ 或唤醒后 5 分钟窗口",
    "多模态：图片 / 表情 / 视频抽帧",
]
for i, s in enumerate(items):
    text(d, (856, y1 + 70 + i * 33), s, "Regular", 16, MUTED)

# 箭头
def arrow(x1, y1_, x2, y2_, color=BORDER):
    d.line([(x1, y1_), (x2, y2_)], fill=color, width=2)
    if x2 > x1:
        d.polygon([(x2 - 8, y2_ - 5), (x2 - 8, y2_ + 5), (x2, y2_)], fill=color)
    else:
        d.polygon([(x2 + 8, y2_ - 5), (x2 + 8, y2_ + 5), (x2, y2_)], fill=color)

arrow(276, y1 + h1 // 2, 396, y1 + h1 // 2)
text(d, (300, y1 + h1 // 2 - 30), "消息", "Regular", 14, DIM)
arrow(702, y1 + 90, 826, y1 + 90)
text(d, (706, y1 + 60), "事件", "Regular", 14, DIM)
arrow(826, y1 + 180, 702, y1 + 180)
text(d, (706, y1 + 186), "下发", "Regular", 14, DIM)

# ===== 第二行：对外依赖 =====
y2, h2 = 452, 214
box(64, y2, 420, h2, PURPLE)
text(d, (88, y2 + 22), "大模型接口", "Bold", 22, TEXT)
for i, s in enumerate(["chat/completions 对话", "tools/search 联网检索", "user/balance 余额"]):
    text(d, (88, y2 + 68 + i * 32), s, "Regular", 16, MUTED, mono=False)
text(d, (88, y2 + 172), "DeepSeek / GPT / 任意 OpenAI 兼容", "Regular", 15, DIM)

box(516, y2, 420, h2, GREEN)
text(d, (540, y2 + 22), "数据层", "Bold", 22, TEXT)
for i, s in enumerate(["data/memory/     对话", "data/facts/      长期事实", "data/stickers/   表情库", "personas/*.md    人格"]):
    text(d, (540, y2 + 66 + i * 31), s, "Regular", 15, MUTED, mono=True)

box(968, y2, 420, h2, BLUE)
text(d, (992, y2 + 22), "配置层", "Bold", 22, TEXT)
for i, s in enumerate(["data/settings.json", "data/providers.json", "data/whitelist.json", "data/admins.json"]):
    text(d, (992, y2 + 66 + i * 31), s, "Regular", 15, MUTED, mono=True)

# ===== 插件层 =====
px, py, pw = 64, 700, 1552
text(d, (px, py), "插件层", "Bold", 22, TEXT)
text(d, (px + 88, py + 4), "21 个模块", "Regular", 15, DIM)

plugins = [
    ("nlu", "斜杠命令路由"), ("ai", "对话与工具调用"), ("whitelist", "群/私聊准入"),
    ("store", "名单存储"), ("groupadmin", "群管与确认"), ("admins", "管理员授权"),
    ("memory", "对话记忆"), ("memsum", "记忆压缩"), ("facts", "长期事实"),
    ("stickers", "表情库"), ("qqfaces", "收藏表情导入"), ("affinity", "好感度"),
    ("persona_store", "会话人格"), ("proactive", "主动找话"), ("coder", "DSH 调度"),
    ("modellist", "模型探测"), ("providers", "服务商"), ("settings", "运行时配置"),
    ("websearch", "联网检索"), ("sysinfo", "资源采集"), ("ping", "连通检查"),
]
cols, cw, ch, gx, gy = 3, 512, 58, 16, 16
for i, (name, desc) in enumerate(plugins):
    r, c = divmod(i, cols)
    x = px + c * (cw + gx)
    y = py + 46 + r * (ch + gy)
    d.rounded_rectangle([x, y, x + cw, y + ch], radius=10, fill=(26, 35, 53), outline=(72, 90, 116), width=1)
    text(d, (x + 18, y + 9), name, "Medium", 16, BLUE, mono=True)
    text(d, (x + 18, y + 34), desc, "Regular", 14, MUTED)

# ===== 底部：托管 =====
by = 1288
box(64, by, 1552, 0, fill=BG)  # 占位不画
d.rounded_rectangle([64, by, 1616, by + 54], radius=12, fill=(20, 28, 42), outline=BORDER, width=1)
text(d, (86, by + 16), "dfy start | stop | status", "Regular", 16, GREEN, mono=True)
text(d, (420, by + 17), "systemd   nb-bot.service（Restart=always）· nc-napcat.service（NapCat 常驻）", "Regular", 15, MUTED)

img.save("docs/architecture.png")
print("saved", img.size)
