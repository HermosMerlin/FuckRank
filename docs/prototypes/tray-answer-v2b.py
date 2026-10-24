"""Prototype: 3x3 single-choice row with a selected-dot halo (no white strip)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("tray-answer-v2b.png")
CLOUD = "#94A3B8"
WHITE = "#FFFFFF"
SOCKET = "#CBD5E1"
GREEN = "#16A34A"
BLUE = "#2563EB"
RED = "#DC2626"

FONT = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
SMALL = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 10)


def cloud(d: ImageDraw.ImageDraw) -> None:
    d.ellipse((1, 8, 15, 14), fill=CLOUD)
    d.ellipse((2, 5, 8, 11), fill=CLOUD)
    d.ellipse((6, 5, 12, 11), fill=CLOUD)
    d.ellipse((4, 3, 10, 9), fill=CLOUD)


def row(d: ImageDraw.ImageDraw, selected: int, color: str) -> None:
    xs = (1, 5, 9, 13)
    for i, x in enumerate(xs):
        if i == selected:
            d.rectangle((x - 1, 9, x + 3, 13), fill=WHITE)
            d.rectangle((x, 10, x + 2, 12), fill=color)
        else:
            d.rectangle((x, 10, x + 2, 12), fill=SOCKET)


def bool_dots(d: ImageDraw.ImageDraw, true_value: bool, color: str) -> None:
    left_selected = true_value
    for selected, cx in ((left_selected, 5), (not left_selected, 10)):
        if selected:
            d.rectangle((cx - 3, 8, cx + 3, 14), fill=WHITE)
            d.rectangle((cx - 2, 9, cx + 2, 13), fill=color)
        else:
            d.rectangle((cx - 2, 9, cx + 2, 13), fill=SOCKET)


def icon(kind: str) -> Image.Image:
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cloud(d)
    if kind == "green-a":
        row(d, 0, GREEN)
    elif kind == "green-b":
        row(d, 1, GREEN)
    elif kind == "green-c":
        row(d, 2, GREEN)
    elif kind == "green-d":
        row(d, 3, GREEN)
    elif kind == "blue-a":
        row(d, 0, BLUE)
    elif kind == "blue-d":
        row(d, 3, BLUE)
    elif kind == "red-a":
        row(d, 0, RED)
    elif kind == "red-d":
        row(d, 3, RED)
    elif kind == "bool-t":
        bool_dots(d, True, GREEN)
    elif kind == "bool-f":
        bool_dots(d, False, GREEN)
    return img


ITEMS = [
    ("green-a", "V5 绿 A"),
    ("green-b", "V5 绿 B"),
    ("green-c", "V5 绿 C"),
    ("green-d", "V5 绿 D"),
    ("blue-a", "V5 蓝 A"),
    ("blue-d", "V5 蓝 D"),
    ("red-a", "V5 红 A"),
    ("red-d", "V5 红 D"),
    ("bool-t", "V5 判断 对"),
    ("bool-f", "V5 判断 错"),
]

SCALE = 12
PAD = 14
CELL_W = 16 * SCALE + PAD * 2
CELL_H = 16 * SCALE + 42
COLS = 5
ROWS = (len(ITEMS) + COLS - 1) // COLS
TOP = 48
STRIP_H = 100
sheet = Image.new("RGBA", (COLS * CELL_W, TOP + ROWS * (CELL_H + PAD) + STRIP_H), (248, 250, 252, 255))
sd = ImageDraw.Draw(sheet)
sd.text((PAD, 10), "V5：3x3 点 + 选中点白描边（无白色底条）", fill=(15, 23, 42, 255), font=FONT)
sd.text((PAD, 28), "16px，12x 最近邻；1x 在底部", fill=(71, 85, 105, 255), font=SMALL)

for i, (kind, label) in enumerate(ITEMS):
    c, r = i % COLS, i // COLS
    x = c * CELL_W + PAD
    y = TOP + r * (CELL_H + PAD)
    big = icon(kind).resize((16 * SCALE, 16 * SCALE), Image.Resampling.NEAREST)
    for by in range(0, 16 * SCALE, 24):
        for bx in range(0, 16 * SCALE, 24):
            fill = (226, 232, 240, 255) if (bx // 24 + by // 24) % 2 else (255, 255, 255, 255)
            sd.rectangle((x + bx, y + by, x + bx + 23, y + by + 23), fill=fill)
    sheet.alpha_composite(big, (x, y))
    sd.rectangle((x, y, x + 16 * SCALE - 1, y + 16 * SCALE - 1), outline=(203, 213, 225, 255))
    sd.text((x, y + 16 * SCALE + 4), label, fill=(15, 23, 42, 255), font=SMALL)

strip_top = TOP + ROWS * (CELL_H + PAD)
sd.rectangle((0, strip_top, sheet.width, strip_top + 50), fill=(243, 243, 243, 255))
sd.text((PAD, strip_top + 4), "1x 浅色任务栏", fill=(15, 23, 42, 255), font=SMALL)
for i, (kind, _label) in enumerate(ITEMS):
    sheet.alpha_composite(icon(kind), (PAD + 110 + i * 22, strip_top + 22))
sd.rectangle((0, strip_top + 50, sheet.width, strip_top + 100), fill=(32, 33, 36, 255))
sd.text((PAD, strip_top + 54), "1x 深色任务栏", fill=(226, 232, 240, 255), font=SMALL)
for i, (kind, _label) in enumerate(ITEMS):
    sheet.alpha_composite(icon(kind), (PAD + 110 + i * 22, strip_top + 72))

sheet.save(OUT)
print(OUT)
