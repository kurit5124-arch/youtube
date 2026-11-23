"""コードで描くイラスト（背景と、表情のある人物）。

画像生成サービスを使わずに、Pillow だけで描く。
- 背景: school（校庭）/ street（街の道路）/ courtroom（法廷）/ hospital（病室）/ net（ネットの声）/ home（部屋）
- 人物: child / woman / mother / elder_woman / elder_man / man / man2 / judge
- 表情: neutral / happy / angry / sad / shock / worried / serious（talking=True で口が開く）
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920
INK = (34, 30, 40)
SKIN = (255, 224, 196)
FLOOR_Y = 1720   # 人物が立つ床の高さ


def _grad(top, bottom, h=H) -> Image.Image:
    img = Image.new("RGBA", (W, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return img


# ---------------------------------------------------------------- 背景
def _street(rng) -> tuple[Image.Image, Image.Image | None]:
    img = _grad((150, 205, 245), (235, 245, 255))
    d = ImageDraw.Draw(img)
    for cx, cy, r in ((200, 300, 70), (820, 220, 90), (560, 380, 60)):  # 雲
        for k in range(3):
            d.ellipse([cx - r + k * r * 0.6, cy - r * 0.6, cx + r * 0.4 + k * r * 0.6, cy + r * 0.5], fill=(255, 255, 255, 230))
    x = -40
    while x < W:  # 家並み
        w = rng.randint(170, 250)
        h = rng.randint(260, 380)
        base = 1330
        wall = rng.choice([(250, 240, 225), (235, 225, 210), (225, 235, 240), (245, 230, 230)])
        roof = rng.choice([(150, 70, 60), (70, 90, 120), (90, 110, 80)])
        d.rectangle([x, base - h, x + w, base], fill=wall, outline=INK, width=5)
        d.polygon([(x - 20, base - h), (x + w / 2, base - h - 110), (x + w + 20, base - h)], fill=roof, outline=INK, width=5)
        for wy in (base - h + 60, base - h + 170):
            d.rectangle([x + 35, wy, x + 95, wy + 60], fill=(180, 215, 240), outline=INK, width=4)
        x += w + rng.randint(10, 40)
    d.line([(850, 520), (850, 1340)], fill=(120, 110, 100), width=18)  # 電柱
    d.line([(0, 600), (W, 560)], fill=(60, 60, 70), width=3)
    d.rectangle([0, 1330, W, 1420], fill=(200, 200, 205), outline=INK, width=5)  # 歩道
    d.rectangle([0, 1420, W, H], fill=(120, 124, 132))  # 道路
    for i in range(6):  # 横断歩道
        d.rectangle([120 + i * 150, 1500, 200 + i * 150, 1700], fill=(245, 245, 245))
    return img, None


def _courtroom(rng) -> tuple[Image.Image, Image.Image | None]:
    img = _grad((236, 222, 196), (210, 190, 160))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 120):  # 木の壁
        d.rectangle([x, 560, x + 110, 1300], fill=(176, 128, 84), outline=(120, 80, 50), width=5)
    d.ellipse([W / 2 - 110, 600, W / 2 + 110, 820], fill=(214, 170, 60), outline=INK, width=6)  # 紋章
    d.ellipse([W / 2 - 70, 640, W / 2 + 70, 780], outline=INK, width=5)
    d.line([(W / 2, 650), (W / 2, 770)], fill=INK, width=6)
    d.line([(W / 2 - 55, 680), (W / 2 + 55, 680)], fill=INK, width=6)
    for sx in (-50, 50):
        d.arc([W / 2 + sx - 25, 690, W / 2 + sx + 25, 740], 0, 180, fill=INK, width=5)
    d.rectangle([0, 1300, W, H], fill=(150, 110, 80))
    # 手前の机（人物より前に描く）
    front = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(front)
    fd.rectangle([60, 1420, W - 60, 1760], fill=(110, 70, 40), outline=INK, width=7)
    fd.rectangle([60, 1400, W - 60, 1450], fill=(140, 92, 55), outline=INK, width=7)
    for x in range(140, W - 120, 230):
        fd.rectangle([x, 1490, x + 170, 1700], outline=(80, 50, 28), width=6)
    return img, front


def _hospital(rng) -> tuple[Image.Image, Image.Image | None]:
    img = _grad((222, 238, 232), (200, 222, 215))
    d = ImageDraw.Draw(img)
    d.rectangle([120, 520, 560, 980], fill=(190, 225, 250), outline=INK, width=6)  # 窓
    d.line([(340, 520), (340, 980)], fill=INK, width=5)
    d.rectangle([90, 500, 200, 1010], fill=(250, 250, 245), outline=INK, width=5)  # カーテン
    d.rectangle([700, 600, 960, 800], fill=(30, 40, 40), outline=INK, width=6)  # モニター
    pts, x = [], 720
    while x < 940:
        y = 700 + (-60 if (x // 30) % 4 == 2 else 0)
        pts.append((x, y))
        x += 15
    d.line(pts, fill=(80, 240, 120), width=5)
    d.rectangle([0, 1350, W, H], fill=(185, 200, 195))
    d.rectangle([140, 1180, 940, 1400], fill=(250, 250, 250), outline=INK, width=7)  # ベッド
    d.rounded_rectangle([170, 1110, 420, 1200], radius=40, fill=(255, 255, 255), outline=INK, width=6)  # 枕
    d.rounded_rectangle([380, 1150, 930, 1330], radius=50, fill=(170, 200, 235), outline=INK, width=6)  # 布団
    d.ellipse([230, 1050, 380, 1190], fill=SKIN, outline=INK, width=6)  # 寝ている人
    d.arc([265, 1110, 300, 1130], 0, 180, fill=INK, width=5)
    d.arc([310, 1110, 345, 1130], 0, 180, fill=INK, width=5)
    d.rectangle([860, 920, 920, 1110], fill=(200, 230, 240), outline=INK, width=5)  # 花瓶
    for k, c in enumerate(((240, 110, 140), (250, 200, 80), (240, 140, 90))):
        d.ellipse([840 + k * 30, 860 - k * 15, 900 + k * 30, 920 - k * 15], fill=c, outline=INK, width=4)
    return img, None


def _net(rng) -> tuple[Image.Image, Image.Image | None]:
    img = _grad((40, 44, 70), (70, 60, 110))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for _ in range(14):  # 流れてくるコメント
        x, y = rng.randint(-100, W - 200), rng.randint(480, 1700)
        w = rng.randint(260, 520)
        d.rounded_rectangle([x, y, x + w, y + 90], radius=40, fill=(255, 255, 255, 40))
        d.ellipse([x + 18, y + 18, x + 72, y + 72], fill=(255, 255, 255, 70))
        d.rounded_rectangle([x + 95, y + 30, x + w - 40, y + 50], radius=10, fill=(255, 255, 255, 60))
    img.alpha_composite(over)
    return img, None


def _home(rng) -> tuple[Image.Image, Image.Image | None]:
    img = _grad((250, 236, 214), (240, 220, 196))
    d = ImageDraw.Draw(img)
    d.rectangle([620, 560, 980, 900], fill=(200, 230, 250), outline=INK, width=6)
    d.line([(800, 560), (800, 900)], fill=INK, width=5)
    d.rectangle([0, 1380, W, H], fill=(196, 150, 110))
    for x in range(0, W, 140):
        d.line([(x, 1380), (x - 60, H)], fill=(170, 125, 90), width=4)
    d.rounded_rectangle([80, 1180, 560, 1420], radius=40, fill=(120, 150, 200), outline=INK, width=6)  # ソファ
    return img, None


def _school(rng) -> tuple[Image.Image, Image.Image | None]:
    img = _grad((150, 205, 245), (235, 245, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 640, 1020, 1150], fill=(245, 240, 228), outline=INK, width=6)  # 校舎
    d.rectangle([60, 600, 1020, 650], fill=(200, 90, 70), outline=INK, width=6)
    d.ellipse([W / 2 - 55, 680, W / 2 + 55, 790], fill=(255, 255, 255), outline=INK, width=5)  # 時計
    d.line([(W / 2, 735), (W / 2, 700)], fill=INK, width=5)
    d.line([(W / 2, 735), (W / 2 + 25, 745)], fill=INK, width=5)
    for row in (830, 990):
        for x in range(110, 980, 150):
            d.rectangle([x, row, x + 100, row + 100], fill=(180, 215, 240), outline=INK, width=4)
    d.rectangle([0, 1150, W, H], fill=(214, 186, 140))  # 校庭
    for x in range(0, W, 60):  # フェンス
        d.line([(x, 1080), (x, 1180)], fill=(110, 120, 110), width=4)
    d.line([(0, 1090), (W, 1090)], fill=(110, 120, 110), width=5)
    d.line([(0, 1170), (W, 1170)], fill=(110, 120, 110), width=5)
    gx, gy = 640, 1200  # サッカーゴール
    d.rectangle([gx, gy, gx + 380, gy + 230], outline=(255, 255, 255), width=12)
    for k in range(1, 8):
        d.line([(gx + k * 47, gy), (gx + k * 47, gy + 230)], fill=(255, 255, 255, 140), width=3)
    for k in range(1, 5):
        d.line([(gx, gy + k * 46), (gx + 380, gy + k * 46)], fill=(255, 255, 255, 140), width=3)
    return img, None


BACKGROUNDS = {"school": _school, "street": _street, "courtroom": _courtroom, "hospital": _hospital, "net": _net, "home": _home}


@lru_cache(maxsize=16)
def background(name: str, seed: int = 0) -> tuple[Image.Image, Image.Image | None]:
    return BACKGROUNDS.get(name, _home)(random.Random(seed))


# ---------------------------------------------------------------- 人物
LOOKS = {
    # 髪型, 髪の色, 服の色
    "child": ("spiky", (60, 45, 40), (80, 160, 230)),
    "woman": ("long", (90, 60, 45), (240, 150, 170)),
    "mother": ("bob", (70, 50, 40), (250, 190, 110)),
    "elder_woman": ("bun", (190, 190, 195), (150, 120, 180)),
    "elder_man": ("short", (205, 205, 210), (140, 120, 95)),
    "man": ("short", (40, 40, 45), (90, 110, 140)),
    "man2": ("short", (110, 75, 50), (110, 170, 120)),
    "judge": ("judge", (150, 150, 155), (30, 30, 36)),
}


def _hair_back(d, style, col):
    if style == "long":
        d.rounded_rectangle([40, 70, 360, 470], radius=120, fill=col, outline=INK, width=6)
    elif style == "bob":
        d.rounded_rectangle([45, 60, 355, 330], radius=110, fill=col, outline=INK, width=6)
    elif style == "bun":
        d.ellipse([140, 0, 260, 110], fill=col, outline=INK, width=6)


def _hair_front(d, style, col):
    if style == "spiky":
        pts = [(55, 190), (70, 90), (110, 120), (130, 40), (180, 100), (210, 30), (245, 100), (290, 50), (300, 120), (345, 110), (345, 190)]
        d.polygon(pts, fill=col, outline=INK, width=6)
    elif style in ("long", "bob"):
        d.chord([55, 55, 345, 330], 180, 360, fill=col, outline=INK, width=6)
        d.polygon([(70, 190), (150, 120), (200, 170), (260, 115), (335, 190), (335, 160), (70, 160)], fill=col)
    elif style == "bun":
        d.chord([60, 60, 340, 320], 185, 355, fill=col, outline=INK, width=6)
    elif style == "short":
        d.chord([55, 50, 345, 320], 180, 360, fill=col, outline=INK, width=6)
        d.polygon([(60, 190), (60, 150), (250, 120), (340, 150), (340, 190), (300, 160), (120, 175)], fill=col)
    elif style == "judge":
        d.chord([60, 55, 340, 300], 185, 355, fill=col, outline=INK, width=6)


def _face(d, expr: str, talking: bool, blink: bool):
    lx, rx, ey = 150, 250, 215
    # 眉
    brows = {
        "angry": [((115, 160), (180, 185)), ((285, 160), (220, 185))],
        "sad": [((120, 180), (180, 160)), ((280, 180), (220, 160))],
        "worried": [((120, 175), (180, 155)), ((280, 175), (220, 155))],
        "shock": [((120, 140), (180, 135)), ((220, 135), (280, 140))],
        "serious": [((120, 170), (180, 175)), ((220, 175), (280, 170))],
    }.get(expr, [((125, 168), (180, 165)), ((220, 165), (275, 168))])
    for a, b in brows:
        d.line([a, b], fill=INK, width=9)
    # 目
    if blink and expr not in ("shock",):
        for x in (lx, rx):
            d.line([(x - 20, ey), (x + 20, ey)], fill=INK, width=7)
    elif expr == "happy":
        for x in (lx, rx):
            d.arc([x - 24, ey - 18, x + 24, ey + 22], 200, 340, fill=INK, width=8)
    elif expr == "shock":
        for x in (lx, rx):
            d.ellipse([x - 28, ey - 30, x + 28, ey + 30], fill=(255, 255, 255), outline=INK, width=6)
            d.ellipse([x - 7, ey - 7, x + 7, ey + 7], fill=INK)
    elif expr == "sad":
        for x in (lx, rx):
            d.arc([x - 22, ey - 10, x + 22, ey + 24], 20, 160, fill=INK, width=8)
        for x in (lx - 10, rx + 10):  # 涙
            d.polygon([(x, ey + 25), (x - 14, ey + 65), (x + 14, ey + 65)], fill=(110, 180, 255))
            d.ellipse([x - 14, ey + 50, x + 14, ey + 80], fill=(110, 180, 255))
    else:
        for x in (lx, rx):
            d.ellipse([x - 11, ey - 17, x + 11, ey + 17], fill=INK)
            d.ellipse([x - 5, ey - 12, x + 1, ey - 4], fill=(255, 255, 255))
    if expr == "happy":
        for x in (lx - 25, rx + 25):
            d.ellipse([x - 26, ey + 35, x + 26, ey + 60], fill=(255, 160, 160))
    if expr == "shock":  # ガーン線
        for k in range(5):
            d.line([(120 + k * 40, 80), (120 + k * 40, 140)], fill=(90, 110, 220), width=6)
    # 口
    mx, my = 200, 285
    if talking:
        size = {"shock": 34, "angry": 30}.get(expr, 24)
        d.ellipse([mx - size, my - size * 0.7, mx + size, my + size * 0.9], fill=(150, 40, 50), outline=INK, width=6)
    elif expr == "happy":
        d.chord([mx - 40, my - 30, mx + 40, my + 30], 0, 180, fill=(150, 40, 50), outline=INK, width=6)
    elif expr == "angry":
        d.rectangle([mx - 38, my - 12, mx + 38, my + 18], fill=(255, 255, 255), outline=INK, width=6)
        d.line([(mx - 38, my + 3), (mx + 38, my + 3)], fill=INK, width=4)
    elif expr == "sad":
        d.arc([mx - 35, my, mx + 35, my + 40], 200, 340, fill=INK, width=8)
    elif expr == "shock":
        d.ellipse([mx - 24, my - 20, mx + 24, my + 34], fill=(120, 30, 40), outline=INK, width=6)
    elif expr == "worried":
        d.line([(mx - 34, my + 8), (mx - 12, my - 4), (mx + 12, my + 8), (mx + 34, my - 4)], fill=INK, width=7)
    else:
        d.line([(mx - 26, my + 4), (mx + 26, my + 4)], fill=INK, width=8)


def _bike(d):
    for cx in (60, 340):
        d.ellipse([cx - 95, 560, cx + 95, 750], outline=INK, width=12)
        d.ellipse([cx - 12, 643, cx + 12, 667], fill=INK)
    d.line([(60, 655), (180, 540), (340, 655)], fill=(220, 60, 60), width=16)
    d.line([(180, 540), (300, 540), (340, 655)], fill=(220, 60, 60), width=16)
    d.line([(300, 540), (320, 480)], fill=INK, width=12)
    d.line([(290, 480), (360, 470)], fill=INK, width=12)


@lru_cache(maxsize=128)
def person(who: str, expr: str = "neutral", talking: bool = False, blink: bool = False, bike: bool = False) -> Image.Image:
    """人物 1 人（400x760 の透明 PNG。足元が下端）。"""
    style, hair, cloth = LOOKS.get(who, LOOKS["man"])
    img = Image.new("RGBA", (400, 760), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _hair_back(d, style, hair)
    # 体
    d.rounded_rectangle([95, 360, 305, 720], radius=70, fill=cloth, outline=INK, width=6)
    if who == "judge":
        d.polygon([(160, 360), (200, 440), (240, 360)], fill=(255, 255, 255), outline=INK)
    for x0 in (55, 295):  # 腕
        d.rounded_rectangle([x0, 390, x0 + 50, 620], radius=25, fill=cloth, outline=INK, width=6)
        d.ellipse([x0 - 2, 600, x0 + 52, 650], fill=SKIN, outline=INK, width=5)
    d.rectangle([90, 700, 310, 760], fill=(0, 0, 0, 0))
    d.rectangle([170, 330, 230, 370], fill=SKIN)
    # 頭
    d.ellipse([60, 70, 340, 350], fill=SKIN, outline=INK, width=6)
    _hair_front(d, style, hair)
    if who == "judge":  # 眼鏡
        for x in (150, 250):
            d.ellipse([x - 34, 185, x + 34, 245], outline=INK, width=5)
        d.line([(184, 212), (216, 212)], fill=INK, width=5)
    _face(d, expr, talking, blink)
    if bike:
        _bike(d)
    return img


def shadow(width: int) -> Image.Image:
    sh = Image.new("RGBA", (width, 60), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([0, 0, width, 60], fill=(0, 0, 0, 70))
    return sh.filter(ImageFilter.GaussianBlur(6))


def bob(t: float, k: int) -> float:
    return math.sin(t * 3 + k * 1.7) * 6
