import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1600, 900
BG      = (15, 23, 42)
CARD    = (27, 35, 54)
CARD2   = (22, 30, 46)
BORDER  = (71, 85, 105)
TEXT    = (248, 250, 252)
MUTED   = (148, 163, 184)
ACCENT  = (34, 197, 94)
BLUE    = (56, 189, 248)
PINK    = (232, 121, 249)

PLEX = "/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-%s.ttf"
MONO = "/usr/share/fonts/truetype/ibm-plex/IBMPlexMono-%s.ttf"
CJK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-%s.ttc"
CJK_INDEX = 2

_cache = {}
def lf(weight, size):
    k = ("l", weight, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(PLEX % weight, size)
    return _cache[k]

def mf(weight, size):
    k = ("m", weight, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(MONO % weight, size)
    return _cache[k]

def cf(weight, size):
    real = "Bold" if weight == "Bold" else "Regular"
    k = ("c", real, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(CJK % real, size, index=CJK_INDEX)
    return _cache[k]

RUN = re.compile(r"[\x00-\x7f]+|[^\x00-\x7f]+")

def draw_mixed(d, xy, text, cjk_weight, size, fill, latin_weight=None, mono=False, tracking=0):
    """拉丁用 Plex / 等宽用 Plex Mono，中文用 Noto Sans CJK SC。"""
    latin_weight = latin_weight or cjk_weight
    x, y = xy
    for part in RUN.findall(text):
        ascii_run = part.isascii()
        if mono and ascii_run:
            font = mf("Regular" if cjk_weight == "Regular" else "Medium", size)
        elif ascii_run:
            font = lf(latin_weight, size)
        else:
            font = cf(cjk_weight, size)
        if tracking and not ascii_run:
            for ch in part:
                d.text((x, y), ch, font=font, fill=fill)
                x += d.textlength(ch, font=font) + tracking
        else:
            d.text((x, y), part, font=font, fill=fill)
            x += d.textlength(part, font=font)
    return x

def mixed_len(d, text, cjk_weight, size, latin_weight=None, mono=False):
    latin_weight = latin_weight or cjk_weight
    total = 0
    for part in RUN.findall(text):
        if mono and part.isascii():
            f = mf("Medium", size)
        elif part.isascii():
            f = lf(latin_weight, size)
        else:
            f = cf(cjk_weight, size)
        total += d.textlength(part, font=f)
    return total

def rbox(xy, r=16, fill=CARD, outline=BORDER, width=1):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# 顶部极淡光晕
glow = Image.new("RGB", (W, H), BG)
gd = ImageDraw.Draw(glow)
gd.ellipse([W // 2 - 560, -420, W // 2 + 560, 220], fill=(23, 42, 66))
gd.ellipse([-320, H - 260, 420, H + 220], fill=(21, 46, 40))
glow = glow.filter(ImageFilter.GaussianBlur(190))
img = Image.blend(img, glow, 0.5)
d = ImageDraw.Draw(img)

# ===== Header =====
draw_mixed(d, (72, 56), "花花机器人", "Bold", 58, TEXT, tracking=1.2)
d.rounded_rectangle([74, 150, 222, 155], radius=3, fill=ACCENT)
draw_mixed(d, (74, 176), "huahuaQbot", "Regular", 24, MUTED, latin_weight="Medium")
draw_mixed(d, (208, 176), " · 跑在自己服务器上的 QQ 群聊助手", "Regular", 22, MUTED)

# 右上 tags
tags = [("NoneBot2", False), ("NapCat", False), ("OneBot v11", False), ("可选 DSH", True)]
tx = W - 72
for label, hot in tags[::-1]:
    tw = mixed_len(d, label, "Regular", 17) + 30
    tx -= tw
    rbox([tx, 60, tx + tw, 96], r=18, fill=CARD2, outline=(51, 65, 85))
    draw_mixed(d, (tx + 15, 69), label, "Regular", 17, ACCENT if hot else MUTED)
    tx -= 10

# ===== 左：流程 =====
steps = [
    ("01", "QQ 用户", "群聊 / 私聊 / 戳一戳 / 图片 / 视频", BLUE),
    ("02", "NapCat", "登录 QQ，把消息转成 OneBot v11 事件", BLUE),
    ("03", "NoneBot2", "人格 · 记忆 · 命令 · 群管 · 表情", ACCENT),
    ("04", "大模型", "DeepSeek / GPT / 任意 OpenAI 兼容", PINK),
]
bx, bw, bh, gap, top = 72, 660, 104, 34, 232
for i, (num, title, sub, color) in enumerate(steps):
    y = top + i * (bh + gap)
    rbox([bx, y, bx + bw, y + bh], r=16, fill=CARD, outline=(45, 58, 78))
    d.rounded_rectangle([bx + 22, y + 30, bx + 26, y + bh - 30], radius=2, fill=color)

    nb = [bx + 46, y + 26, bx + 92, y + 58]
    d.rounded_rectangle(nb, radius=8, fill=CARD2, outline=(56, 72, 94))
    draw_mixed(d, (nb[0] + 12, y + 33), num, "Regular", 15, color, mono=True)

    draw_mixed(d, (bx + 108, y + 24), title, "Bold", 26, TEXT)
    draw_mixed(d, (bx + 108, y + 68), sub, "Regular", 18, MUTED)

    if i < len(steps) - 1:
        cx = bx + 24
        ay = y + bh + 6
        by = y + bh + gap - 6
        d.line([(cx, ay), (cx, by - 6)], fill=(58, 74, 98), width=2)
        d.polygon([(cx - 5, by - 8), (cx + 5, by - 8), (cx, by)], fill=(94, 120, 150))

# ===== 右：数据面板 =====
px, pw = 776, 752
rbox([px, 232, px + pw, 636], r=18, fill=CARD, outline=(45, 58, 78))
draw_mixed(d, (px + 32, 258), "数据与状态", "Bold", 22, TEXT)
draw_mixed(d, (px + pw - 190, 262), "data/", "Regular", 16, MUTED, mono=True)
d.line([(px + 32, 300), (px + pw - 32, 300)], fill=(45, 58, 78), width=1)

rows = [
    ("对话记忆", "memory/", "按 QQ 分文件，超长自动压缩"),
    ("长期事实", "facts/", "压缩也不会丢"),
    ("人格", "personas/*.md", "热加载，改完立即生效"),
    ("准入名单", "whitelist · blacklist", "群和人分开管"),
    ("表情库", "stickers/", "自动打情绪标签"),
    ("会话与开关", "settings · providers", "模型 / 接口 / 开关"),
]
for i, (k, mono, note) in enumerate(rows):
    y = 320 + i * 50
    draw_mixed(d, (px + 32, y), k, "Medium", 18, TEXT)
    draw_mixed(d, (px + 168, y + 2), mono, "Regular", 15, BLUE, mono=True)
    draw_mixed(d, (px + 452, y + 2), note, "Regular", 16, MUTED)

# DSH 可选
rbox([px, 656, px + pw, 732], r=16, fill=(20, 28, 42), outline=(45, 58, 78))
d.ellipse([px + 30, 684, px + 38, 692], fill=ACCENT)
draw_mixed(d, (px + 50, 676), "DSH（可选）", "Medium", 18, ACCENT)
draw_mixed(d, (px + 188, 678), "装了可在服务器执行编码任务 · 不装不影响其它功能", "Regular", 16, MUTED)

# ===== 底部特性 =====
feats = [
    ("多模态", "看图 / 表情 / 抽帧看视频"),
    ("有人味", "可沉默 · 可还嘴 · 分条发"),
    ("会主动", "随机找话 · 冷场退避"),
    ("可运维", "dfy 一键启停 · 审计日志"),
]
fy, fw, fgap = 772, 352, 24
for i, (k, v) in enumerate(feats):
    x = 72 + i * (fw + fgap)
    rbox([x, fy, x + fw, fy + 80], r=14, fill=CARD2, outline=(45, 58, 78))
    draw_mixed(d, (x + 24, fy + 16), k, "Medium", 19, TEXT)
    draw_mixed(d, (x + 24, fy + 48), v, "Regular", 15, MUTED)

img.save("docs/architecture.png")
print("saved", img.size)
