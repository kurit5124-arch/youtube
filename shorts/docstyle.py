"""ドキュメンタリー風のスライドを描く（未来の日常シリーズ用）。

時刻（label が "06:30" の形）に合わせて空の色が変わり、上半分に未来の街並み、
下半分に時刻・場所・字幕を出す。粒子感とビネットで映像っぽく見せる。
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import Scene, VideoPlan

W, H = 1080, 1920
HORIZON = 1120          # 街並みの地面の高さ
ACCENT = (255, 190, 92)
TEXT_W = 860            # 右側のショートのボタンにかからない幅

# (時, 空の上の色, 空の下の色, 窓の明かりの割合)
SKY = [
    (0, (8, 10, 28), (24, 26, 58), 0.55),
    (5, (24, 30, 70), (214, 120, 98), 0.35),
    (7, (88, 140, 200), (250, 200, 150), 0.12),
    (12, (60, 130, 210), (170, 210, 240), 0.05),
    (16, (70, 110, 190), (240, 180, 120), 0.12),
    (18, (40, 40, 100), (240, 120, 80), 0.35),
    (20, (14, 16, 44), (54, 40, 90), 0.6),
    (24, (8, 10, 28), (24, 26, 58), 0.55),
]


def _hour(label: str) -> float:
    m = re.match(r"(\d{1,2}):(\d{2})", label or "")
    return int(m[1]) + int(m[2]) / 60 if m else 21.0


def _mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _sky(hour: float):
    for (h0, t0, b0, l0), (h1, t1, b1, l1) in zip(SKY, SKY[1:]):
        if h0 <= hour <= h1:
            t = (hour - h0) / (h1 - h0)
            return _mix(t0, t1, t), _mix(b0, b1, t), l0 + (l1 - l0) * t
    return SKY[0][1], SKY[0][2], SKY[0][3]


def _city(img: Image.Image, rng: random.Random, top, bottom, lit: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    # 空
    for y in range(HORIZON):
        d.line([(0, y), (W, y)], fill=_mix(top, bottom, y / HORIZON))
    # 星（暗いときだけ）
    if lit > 0.3:
        for _ in range(90):
            x, y = rng.randrange(W), rng.randrange(HORIZON - 500)
            d.point((x, y), fill=(255, 255, 255, rng.randint(60, 200)))
    far = _mix(bottom, (20, 24, 40), 0.55)
    near = _mix(bottom, (8, 10, 18), 0.85)
    # 遠くのビル（かすむ）
    x = -40
    while x < W:
        bw, bh = rng.randint(50, 120), rng.randint(180, 520)
        d.rectangle([x, HORIZON - bh, x + bw, HORIZON], fill=far + (255,))
        x += bw + rng.randint(4, 20)
    # 未来っぽい塔（リング付き）
    tx = rng.randint(260, 820)
    d.polygon([(tx - 26, HORIZON), (tx - 8, HORIZON - 820), (tx + 8, HORIZON - 820), (tx + 26, HORIZON)], fill=near + (255,))
    for k, ry in enumerate((HORIZON - 640, HORIZON - 700)):
        d.ellipse([tx - 120 + k * 30, ry - 16, tx + 120 - k * 30, ry + 16], outline=ACCENT + (200,), width=5)
    d.ellipse([tx - 7, HORIZON - 840, tx + 7, HORIZON - 826], fill=(255, 80, 80, 255))
    # 手前のビルと窓
    x = -30
    while x < W:
        bw, bh = rng.randint(80, 170), rng.randint(120, 430)
        y0 = HORIZON - bh
        d.rectangle([x, y0, x + bw, HORIZON], fill=near + (255,))
        if rng.random() < 0.3:  # 屋上の緑
            d.rectangle([x + 6, y0 - 10, x + bw - 6, y0], fill=(60, 140, 90, 255))
        for wy in range(y0 + 16, HORIZON - 10, 26):
            for wx in range(x + 10, x + bw - 14, 22):
                if rng.random() < lit:
                    d.rectangle([wx, wy, wx + 10, wy + 12], fill=(255, 214, 140, rng.randint(150, 240)))
        x += bw + rng.randint(2, 10)
    # 空を飛ぶドローン（光の点と軌跡）
    for _ in range(rng.randint(3, 6)):
        x, y = rng.randint(60, W - 60), rng.randint(260, HORIZON - 560)
        ln = rng.randint(40, 110)
        d.line([(x - ln, y + ln // 6), (x, y)], fill=(255, 255, 255, 70), width=3)
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(140, 230, 255, 230))
    # 地面
    for y in range(HORIZON, H):
        d.line([(0, y), (W, y)], fill=_mix((10, 11, 18), (2, 2, 6), (y - HORIZON) / (H - HORIZON)))
    # 地面に映る街の光
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rectangle([0, HORIZON - 10, W, HORIZON + 60], fill=ACCENT + (int(40 + 60 * lit),))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))


def _finish(img: Image.Image, rng: random.Random) -> Image.Image:
    # ビネット
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse([-260, -200, W + 260, H + 200], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(220))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    img = Image.composite(img, dark, v)
    # フィルムの粒子
    noise = Image.effect_noise((W // 2, H // 2), 40).resize((W, H)).convert("RGBA")
    noise.putalpha(18)
    return Image.alpha_composite(img.convert("RGBA"), noise)


def _wrap(text: str, font, max_w: int) -> list[str]:
    from .render import wrap
    return wrap(text, font, max_w)


def _fit(text: str, font_path: str, max_w: int, max_lines: int, start: int, minimum: int = 40):
    size = start
    while True:
        f = ImageFont.truetype(font_path, size)
        lines = _wrap(text, f, max_w)
        if len(lines) <= max_lines or size <= minimum:
            return f, lines
        size -= 4


def _text(d, xy, text, font, fill=(255, 255, 255), anchor="la", shadow=True):
    x, y = xy
    if shadow:
        d.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 200), anchor=anchor)
    d.text((x, y), text, font=font, fill=fill, anchor=anchor)


def draw(plan: VideoPlan, scene: Scene, idx: int, total: int, font_path: str, out: Path) -> None:
    rng = random.Random(plan.seed * 31 + idx)
    top, bottom, lit = _sky(_hour(scene.label) if scene.kind in ("doc", "interview") else 21.0)
    img = Image.new("RGBA", (W, H))
    _city(img, random.Random(plan.seed), top, bottom, lit)  # 街並みは 1 本の中で同じ形にする
    img = _finish(img, rng)
    d = ImageDraw.Draw(img, "RGBA")
    f = lambda s: ImageFont.truetype(font_path, s)  # noqa: E731
    x0 = 80

    # 上部：シリーズ名とフィクション表記
    _text(d, (x0, 205), "FUTURE DOCUMENTARY", f(34), fill=ACCENT)
    _text(d, (x0, 252), plan.subheader, f(44))
    d.rounded_rectangle([W - 330, 200, W - 70, 252], radius=10, outline=(255, 255, 255, 170), width=3)
    d.text((W - 200, 226), "フィクション", font=f(30), fill=(255, 255, 255, 220), anchor="mm")

    if scene.kind == "hook":
        _text(d, (W // 2, 640), scene.label, f(260), fill=(255, 255, 255), anchor="mm")
        d.line([(W / 2 - 160, 790), (W / 2 + 160, 790)], fill=ACCENT, width=6)
        font, lines = _fit(scene.text, font_path, TEXT_W, 3, 104)
        y = 1230
        for ln in lines:
            _text(d, (W // 2, y), ln, font, anchor="mm")
            y += int(font.size * 1.3)
        if scene.sub:
            _text(d, (W // 2, y + 40), scene.sub, f(46), fill=(220, 220, 230), anchor="mm")
    elif scene.kind == "outro":
        font, lines = _fit(scene.text, font_path, TEXT_W, 4, 96)
        y = 1260
        for ln in lines:
            _text(d, (W // 2, y), ln, font, anchor="mm")
            y += int(font.size * 1.3)
        _text(d, (W // 2, y + 50), scene.sub or "コメントで教えてください", f(44), fill=ACCENT, anchor="mm")
    else:
        # 時刻と場所
        if scene.label:
            _text(d, (x0, 1180), scene.label, f(120), fill=(255, 255, 255))
        y = 1330
        if scene.kind == "interview":
            nf = f(42)
            nw = nf.getlength(scene.sub) + 50
            d.rectangle([x0, y, x0 + nw, y + 66], fill=ACCENT + (240,))
            d.text((x0 + 25, y + 33), scene.sub, font=nf, fill=(20, 20, 25), anchor="lm")
            font, lines = _fit(f"「{scene.text}」", font_path, TEXT_W, 4, 72)
        else:
            if scene.sub:
                d.rectangle([x0, y + 8, x0 + 10, y + 58], fill=ACCENT)
                _text(d, (x0 + 30, y + 33), scene.sub, f(46), fill=(235, 235, 240), anchor="lm")
            font, lines = _fit(scene.text, font_path, TEXT_W, 4, 68)
        y += 110
        lh = int(font.size * 1.4)
        box_h = len(lines) * lh + 40
        d.rectangle([x0 - 20, y - 20, x0 + TEXT_W + 20, y - 20 + box_h], fill=(0, 0, 0, 120))
        for ln in lines:
            _text(d, (x0, y), ln, font)
            y += lh

    # 何枚目か（細いバー）
    seg = TEXT_W / total
    for i in range(total):
        d.rectangle([x0 + i * seg + 3, 1720, x0 + (i + 1) * seg - 3, 1728],
                    fill=ACCENT + (255,) if i <= idx else (255, 255, 255, 70))
    img.convert("RGB").save(out)
