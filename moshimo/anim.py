"""もしもシリーズの横長アニメーション動画（1920x1080）を1コマずつ描く。

絵はすべてプログラムで描く図形と Noto Color Emoji（無料・商用可）。
1つの「場面（shot）」は数秒〜十数秒続き、その間ずっと何かが動き続ける。
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFont

from shorts import illust, render as srender

W, H = 1920, 1080
FPS = 30

FONT = srender.find_font(None)


@lru_cache(maxsize=128)
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, max(8, int(size)))


# ---------------------------------------------------------------- イージング
def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if x < a else b if x > b else x


def ease_out(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_back(x: float) -> float:
    """少し行きすぎてから戻る（ポンッと出る）。"""
    x = clamp(x)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def appear(t: float, start: float, dur: float = 0.45) -> float:
    return ease_back((t - start) / dur) if t >= start else 0.0


# ---------------------------------------------------------------- 部品
@lru_cache(maxsize=512)
def text_sprite(text: str, size: int, color: tuple = (255, 255, 255), stroke: int = 0,
                stroke_color: tuple = (0, 0, 0), max_w: int = 1700, align: str = "center") -> Image.Image:
    """文字を画像にする（何度も使うのでキャッシュ）。改行・はみ出しは折り返す。"""
    f = font(size)
    lines: list[str] = []
    for para in text.split("\n"):
        lines += srender.wrap(para, f, max_w) or [""]
    lh = int(size * 1.32)
    w = int(max(f.getlength(l) for l in lines)) + stroke * 2 + 8
    h = lh * len(lines) + stroke * 2 + 8
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        x = {"center": w / 2, "left": stroke + 4}[align]
        d.text((x, stroke + 4 + i * lh + lh / 2), l, font=f, fill=color + (255,) if len(color) == 3 else color,
               anchor="mm" if align == "center" else "lm", stroke_width=stroke, stroke_fill=stroke_color)
    return img


@lru_cache(maxsize=256)
def emoji(ch: str, size: int) -> Image.Image | None:
    return illust.image(ch, size)


def paste_center(base: Image.Image, sprite: Image.Image | None, cx: float, cy: float,
                 scale: float = 1.0, alpha: float = 1.0, angle: float = 0.0) -> None:
    if sprite is None or scale <= 0.01 or alpha <= 0.01:
        return
    s = sprite
    if abs(scale - 1) > 0.01:
        s = s.resize((max(1, int(s.width * scale)), max(1, int(s.height * scale))), Image.BILINEAR)
    if angle:
        s = s.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        a = s.getchannel("A").point(lambda v: int(v * alpha))
        s = s.copy()
        s.putalpha(a)
    base.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))


def card(w: int, h: int, fill=(255, 255, 255, 240), radius: int = 40) -> Image.Image:
    return _card(int(w), int(h), tuple(fill), radius)


@lru_cache(maxsize=64)
def _card(w, h, fill, radius):
    img = Image.new("RGBA", (w + 24, h + 28), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 18, w + 12, h + 18], radius=radius, fill=(0, 0, 0, 70))
    d.rounded_rectangle([0, 0, w, h], radius=radius, fill=fill)
    return img


# ---------------------------------------------------------------- 背景
class Background:
    def __init__(self, top, bottom, accent, seed: int = 1):
        self.base = Image.new("RGBA", (W, H))
        px = self.base.load()
        grad = [tuple(int(top[k] + (bottom[k] - top[k]) * y / (H - 1)) for k in range(3)) + (255,) for y in range(H)]
        col = Image.new("RGBA", (1, H))
        for y in range(H):
            col.putpixel((0, y), grad[y])
        self.base = col.resize((W, H))
        del px
        rng = random.Random(seed)
        self.stars = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(1.2, 3.2), rng.uniform(0, 6.28),
                       rng.uniform(4, 16)) for _ in range(90)]
        self.blobs = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(220, 420), rng.uniform(0, 6.28)) for _ in range(5)]
        self.accent = accent
        self._glow = self._make_glow()

    def _make_glow(self):
        from PIL import ImageFilter
        g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(g)
        for x, y, r, _ in self.blobs:
            d.ellipse([x - r, y - r, x + r, y + r], fill=self.accent + (26,))
        return g.filter(ImageFilter.GaussianBlur(90))

    def frame(self, t: float) -> Image.Image:
        img = self.base.copy()
        # ゆっくり漂う光
        dx = int(math.sin(t * 0.07) * 40)
        dy = int(math.cos(t * 0.05) * 25)
        img.alpha_composite(self._glow, (dx, dy)) if dx >= 0 and dy >= 0 else img.alpha_composite(
            self._glow.crop((max(0, -dx), max(0, -dy), W, H)), (max(0, dx), max(0, dy)))
        d = ImageDraw.Draw(img)
        for x, y, r, ph, sp in self.stars:
            xx = (x - t * sp) % W
            a = int(110 + 110 * math.sin(t * 1.3 + ph))
            d.ellipse([xx - r, y - r, xx + r, y + r], fill=(255, 255, 255, max(0, a)))
        return img


# ---------------------------------------------------------------- 主人公「あなた」
SKIN = (255, 214, 170)
HAIR = (45, 35, 55)
SHIRT = (88, 166, 255)


def mascot(face: str, t: float, size: float = 1.0) -> Image.Image:
    """シリーズの主人公。face: normal / tired / exhausted / dizzy / sleep / happy / surprised / hungry"""
    S = 2  # 2倍で描いてから縮小してなめらかに
    w, h = 520 * S, 640 * S
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = w / 2
    # 体
    d.rounded_rectangle([cx - 150 * S, 400 * S, cx + 150 * S, 640 * S], radius=110 * S, fill=SHIRT)
    d.rounded_rectangle([cx - 40 * S, 392 * S, cx + 40 * S, 430 * S], radius=20 * S, fill=SKIN)
    # 頭
    hy = 250 * S
    r = 160 * S
    d.ellipse([cx - r, hy - r, cx + r, hy + r], fill=SKIN)
    # 髪
    d.chord([cx - r - 6 * S, hy - r - 10 * S, cx + r + 6 * S, hy + r * 0.55], 180, 360, fill=HAIR)
    d.ellipse([cx - r - 6 * S, hy - 70 * S, cx - r + 40 * S, hy + 10 * S], fill=HAIR)
    d.ellipse([cx + r - 40 * S, hy - 70 * S, cx + r + 6 * S, hy + 10 * S], fill=HAIR)
    # ほっぺ
    for sx in (-1, 1):
        d.ellipse([cx + sx * 95 * S - 26 * S, hy + 55 * S, cx + sx * 95 * S + 26 * S, hy + 85 * S],
                  fill=(255, 160, 150, 140))
    ey = hy + 10 * S
    blink = (t % 3.4) < 0.14
    lid = {"normal": 0.0, "happy": 0.0, "surprised": 0.0, "hungry": 0.0,
           "tired": 0.45, "exhausted": 0.62}.get(face, 0.0)
    if face == "exhausted":
        lid += 0.12 * (0.5 + 0.5 * math.sin(t * 1.7))
    for sx in (-1, 1):
        ex = cx + sx * 62 * S
        if face == "sleep" or (blink and face not in ("dizzy", "surprised")):
            d.arc([ex - 26 * S, ey - 14 * S, ex + 26 * S, ey + 20 * S], 20, 160, fill=(40, 30, 40), width=7 * S)
        elif face == "happy":
            d.arc([ex - 26 * S, ey - 6 * S, ex + 26 * S, ey + 34 * S], 200, 340, fill=(40, 30, 40), width=8 * S)
        elif face == "dizzy":
            rot = t * 360
            for k in range(3):
                rr = (10 + k * 9) * S
                d.arc([ex - rr, ey - rr, ex + rr, ey + rr], rot + k * 60, rot + k * 60 + 260, fill=(40, 30, 40), width=5 * S)
        else:
            ew, eh = (30 if face == "surprised" else 22) * S, (36 if face == "surprised" else 30) * S
            d.ellipse([ex - ew, ey - eh, ex + ew, ey + eh], fill=(40, 30, 40))
            d.ellipse([ex - ew * 0.2, ey - eh * 0.75, ex + ew * 0.35, ey - eh * 0.2], fill=(255, 255, 255))
            if lid > 0:
                d.rectangle([ex - ew - 4 * S, ey - eh - 6 * S, ex + ew + 4 * S, ey - eh + (2 * eh + 6 * S) * lid],
                            fill=SKIN)
                d.line([ex - ew - 2 * S, ey - eh + (2 * eh + 6 * S) * lid, ex + ew + 2 * S, ey - eh + (2 * eh + 6 * S) * lid],
                       fill=(120, 80, 70), width=4 * S)
        if face in ("tired", "exhausted"):
            d.arc([ex - 30 * S, ey + 22 * S, ex + 30 * S, ey + 48 * S], 20, 160, fill=(150, 110, 170), width=6 * S)
    # 口
    my = hy + 95 * S
    if face in ("happy",):
        d.chord([cx - 40 * S, my - 30 * S, cx + 40 * S, my + 30 * S], 0, 180, fill=(170, 60, 70))
    elif face == "surprised":
        d.ellipse([cx - 22 * S, my - 18 * S, cx + 22 * S, my + 26 * S], fill=(170, 60, 70))
    elif face in ("tired", "exhausted", "dizzy"):
        d.arc([cx - 34 * S, my, cx + 34 * S, my + 34 * S], 200, 340, fill=(120, 60, 60), width=6 * S)
    elif face == "hungry":
        d.ellipse([cx - 16 * S, my - 6 * S, cx + 16 * S, my + 20 * S], fill=(170, 60, 70))
        d.ellipse([cx + 18 * S, my + 4 * S, cx + 30 * S, my + 30 * S], fill=(140, 200, 255))  # よだれ
    elif face == "sleep":
        d.ellipse([cx - 12 * S, my, cx + 12 * S, my + 20 * S], fill=(170, 60, 70))
    else:
        d.arc([cx - 36 * S, my - 20 * S, cx + 36 * S, my + 20 * S], 20, 160, fill=(120, 60, 60), width=7 * S)
    img = img.resize((int(w / S * size), int(h / S * size)), Image.LANCZOS)
    return img


# ---------------------------------------------------------------- 時計
def clock_face(t: float, speed: float, size: int = 420) -> Image.Image:
    S = 2
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = n / 2
    d.ellipse([8 * S, 8 * S, n - 8 * S, n - 8 * S], fill=(250, 248, 240), outline=(40, 40, 60), width=14 * S)
    for k in range(12):
        a = k / 12 * 2 * math.pi
        r1, r2 = c - 40 * S, c - (70 if k % 3 == 0 else 56) * S
        d.line([c + r1 * math.sin(a), c - r1 * math.cos(a), c + r2 * math.sin(a), c - r2 * math.cos(a)],
               fill=(40, 40, 60), width=(10 if k % 3 == 0 else 5) * S)
    m = t * speed
    for frac, length, width, col in ((m / 12, 0.45, 16, (40, 40, 60)), (m, 0.68, 10, (40, 40, 60)),
                                     (m * 12, 0.75, 4, (230, 70, 70))):
        a = frac * 2 * math.pi
        d.line([c, c, c + (c * length) * math.sin(a), c - (c * length) * math.cos(a)], fill=col, width=width * S)
    d.ellipse([c - 16 * S, c - 16 * S, c + 16 * S, c + 16 * S], fill=(230, 70, 70))
    return img.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------- 効果
def glitch(img: Image.Image, frame: int, strength: float = 1.0) -> Image.Image:
    rng = random.Random(frame // 2)
    r, g, b, a = img.split()
    off = int((6 + rng.random() * 10) * strength)
    r = ImageChops.offset(r, off, 0)
    b = ImageChops.offset(b, -off, 0)
    out = Image.merge("RGBA", (r, g, b, a))
    if rng.random() < 0.35 * strength:
        for _ in range(3):
            y = rng.randrange(0, H - 60)
            hgt = rng.randrange(10, 60)
            sl = out.crop((0, y, W, y + hgt))
            out.paste(ImageChops.offset(sl, rng.randrange(-60, 60), 0), (0, y))
    return out
