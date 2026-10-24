"""Throwaway prototype #5: recommended dot-row language for round 2.

Output: docs/prototypes/tray-icon-row-recommended.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("tray-answer-row.png")
CLOUD = "#94A3B8"
SOCKET = "#D7DEE8"
DARK = "#1E293B"
GREEN = "#6BCB9F"
RED = "#E07A5F"

FONT = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
SMALL = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)


def cloud(d: ImageDraw.ImageDraw) -> None:
    d.ellipse((1, 8, 15, 14), fill=CLOUD)
    d.ellipse((2, 5, 8, 11), fill=CLOUD)
    d.ellipse((6, 5, 12, 11), fill=CLOUD)
    d.ellipse((4, 3, 10, 9), fill=CLOUD)


def status_dot(d: ImageDraw.ImageDraw, color: str) -> None:
    d.ellipse((8, 8, 15, 15), fill="#FFFFFF")
    d.ellipse((9, 9, 14, 14), fill=color)


def dots(d: ImageDraw.ImageDraw, selected: str, keys: str = "ABCD") -> None:
    xs = {"ABCD": [3, 6, 9, 12], "AB": [5, 10]}[keys]
    for key, x in zip(keys, xs):
        d.rectangle((x, 12, x + 1, 13), fill=DARK if key in selected else SOCKET)


def icon(kind: str) -> Image.Image:
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cloud(d)
    if kind == "status-ready":
        status_dot(d, GREEN)
    elif kind == "status-error":
        status_dot(d, RED)
    elif kind.startswith("bool-"):
        dots(d, "A" if kind == "bool-t" else "B", keys="AB")
    else:
        dots(d, kind.upper())
    return img


ITEMS = [
    ("status-ready", "代码答案就绪", "原绿色状态点"),
    ("status-error", "错误", "原红色状态点"),
    ("a", "单选 A", "从左第 1 点"),
    ("b", "单选 B", "第 2 点"),
    ("c", "单选 C", "第 3 点"),
    ("d", "单选 D", "第 4 点"),
    ("ac", "多选 A+C", "第 1、3 点亮"),
    ("abcd", "多选 A+B+C+D", "四点全亮"),
    ("bool-t", "判断：正确", "左点亮，右点灰"),
    ("bool-f", "判断：错误", "左点灰，右点亮"),
]

SCALE = 12
PAD = 16
LABEL_H = 34
CELL_W = 16 * SCALE + PAD * 2
COLS = 4
ROWS = (len(ITEMS) + COLS - 1) // COLS
TOP = 52
STRIP_H = 100
sheet = Image.new(
    "RGBA",
    (COLS * CELL_W, TOP + ROWS * (16 * SCALE + LABEL_H + PAD) + STRIP_H),
    (248, 250, 252, 255),
)
sd = ImageDraw.Draw(sheet)
sd.text((PAD, 12), "FuckRank 选择题/判断题托盘图标：云朵下方一行点", fill=(15, 23, 42, 255), font=FONT)
sd.text((PAD, 30), "16px；放大 12x 为最近邻，1x 为实际大小", fill=(71, 85, 105, 255), font=SMALL)

for i, (kind, title, note) in enumerate(ITEMS):
    c, r = i % COLS, i // COLS
    x = c * CELL_W + PAD
    y = TOP + r * (16 * SCALE + LABEL_H + PAD)
    big = icon(kind).resize((16 * SCALE, 16 * SCALE), Image.Resampling.NEAREST)
    for by in range(0, 16 * SCALE, 24):
        for bx in range(0, 16 * SCALE, 24):
            fill = (226, 232, 240, 255) if (bx // 24 + by // 24) % 2 else (255, 255, 255, 255)
            sd.rectangle((x + bx, y + by, x + bx + 23, y + by + 23), fill=fill)
    sheet.alpha_composite(big, (x, y))
    sd.rectangle((x, y, x + 16 * SCALE - 1, y + 16 * SCALE - 1), outline=(203, 213, 225, 255))
    sd.text((x, y + 16 * SCALE + 4), title, fill=(15, 23, 42, 255), font=SMALL)
    sd.text((x, y + 16 * SCALE + 18), note, fill=(100, 116, 139, 255), font=SMALL)

strip_top = TOP + ROWS * (16 * SCALE + LABEL_H + PAD)
sd.rectangle((0, strip_top, sheet.width, strip_top + 50), fill=(243, 243, 243, 255))
sd.text((PAD, strip_top + 4), "1x 浅色任务栏", fill=(15, 23, 42, 255), font=SMALL)
for i, (kind, _title, _note) in enumerate(ITEMS):
    sheet.alpha_composite(icon(kind), (PAD + 120 + i * 24, strip_top + 22))
sd.rectangle((0, strip_top + 50, sheet.width, strip_top + 100), fill=(32, 33, 36, 255))
sd.text((PAD, strip_top + 54), "1x 深色任务栏", fill=(226, 232, 240, 255), font=SMALL)
for i, (kind, _title, _note) in enumerate(ITEMS):
    sheet.alpha_composite(icon(kind), (PAD + 120 + i * 24, strip_top + 72))

sheet.save(OUT)
print(OUT)
