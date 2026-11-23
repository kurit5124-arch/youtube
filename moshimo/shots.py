"""場面（shot）の種類。どれも t（場面が始まってからの秒数）を受け取り、動きのある絵を描く。

episodes/*.yaml の shot: {type: ..., ...} で使う。
"""
from __future__ import annotations

import math
import random
import re

from PIL import Image, ImageDraw

from .anim import (H, W, appear, card, clamp, clock_face, ease_out, emoji, font, mascot, paste_center,
                   text_sprite)

INK = (30, 30, 45)


def _float(t: float, phase: float = 0.0, amp: float = 10.0, speed: float = 1.6) -> float:
    return math.sin(t * speed + phase) * amp


# ---------------------------------------------------------------- 各場面
def shot_title(img, s, t, accent):
    """大きな文字がポンッと出る。sub があれば下に小さく。"""
    sc = appear(t, 0.0, 0.55)
    paste_center(img, text_sprite(s["text"], s.get("size", 130), (255, 255, 255), 10, INK),
                 W / 2, H / 2 - 60 + _float(t, amp=6), sc)
    if s.get("sub"):
        paste_center(img, text_sprite(s["sub"], 64, accent, 8, INK), W / 2, H / 2 + 120, appear(t, 0.5))
    if s.get("emoji"):
        paste_center(img, emoji(s["emoji"], 240), W / 2, H / 2 - 300 + _float(t, 1, 12), appear(t, 0.25))


def shot_clock(img, s, t, accent):
    """針がぐるぐる回る時計。"""
    paste_center(img, clock_face(t, s.get("speed", 2.0), 420), W / 2 + s.get("dx", 0), H / 2 - 90,
                 appear(t, 0.0, 0.6), angle=_float(t, amp=3, speed=1.1))
    if s.get("text"):
        paste_center(img, text_sprite(s["text"], 80, (255, 255, 255), 9, INK), W / 2, H / 2 + 200, appear(t, 0.5))


ICON_SPOTS = [(-400, -170), (400, -170), (-450, 120), (450, 120), (0, -420), (-300, -400), (300, -400)]


def _icons_around(img, s, t, cx, cy, start=0.3):
    """主人公のまわり（左右交互）にアイコンを出す。"""
    for k, ch in enumerate(s.get("icons", [])[: len(ICON_SPOTS)]):
        ox, oy = ICON_SPOTS[k]
        if cx + ox < 120 or cx + ox > W - 120:
            ox = -ox
        paste_center(img, emoji(ch, 150), cx + ox, cy + oy + _float(t, k, 14), appear(t, start + k * 0.25),
                     angle=_float(t, k, 8, 1.2))


def shot_mascot(img, s, t, accent):
    """主人公「あなた」＋まわりのアイコン＋見出し。"""
    side = s.get("side", "center")
    cx = {"center": W / 2, "left": W * 0.3, "right": W * 0.7}[side]
    cy = H / 2 + 60
    face = s.get("face", "normal")
    sway = _float(t, amp=4 if face != "exhausted" else 9, speed=1.2)
    m = mascot(face, t, s.get("scale", 0.95))
    paste_center(img, m, cx, cy + _float(t, amp=8, speed=2.0), appear(t, 0.0, 0.5), angle=sway)
    if face == "sleep":
        for k in range(3):
            ph = (t * 0.6 + k / 3) % 1
            paste_center(img, text_sprite("Z", 60 + k * 14, (255, 255, 255), 6, INK),
                         cx + 170 + ph * 90, cy - 230 - ph * 160, 1, alpha=1 - ph)
    if s.get("bubble"):
        bx, by = cx + 300, cy - 300
        sc = appear(t, 0.5)
        d = ImageDraw.Draw(img)
        if sc > 0.05:
            for k, (ox, oy, r) in enumerate(((-150, 150, 18), (-110, 100, 26))):
                d.ellipse([bx + ox - r * sc, by + oy - r * sc, bx + ox + r * sc, by + oy + r * sc], fill=(255, 255, 255, 235))
            paste_center(img, card(300, 230, (255, 255, 255, 235), 115), bx, by, sc)
            paste_center(img, emoji(s["bubble"], 140), bx, by - 6 + _float(t, 2, 6), sc)
    if s.get("icons"):
        _icons_around(img, s, t, cx, cy)
    if s.get("text"):
        tx = W / 2 if side == "center" else (W * 0.72 if side == "left" else W * 0.28)
        ty = 195 if side == "center" else H / 2 - 40
        sp = text_sprite(s["text"], s.get("size", 76), (255, 255, 255), 9, INK, max_w=820 if side != "center" else 1600)
        paste_center(img, sp, tx, ty, appear(t, 0.35))


def shot_equal(img, s, t, accent):
    """左 ＝ 右（比べる）。"""
    sign = s.get("sign", "≒")
    for k, key in enumerate(("left", "right")):
        it = s[key]
        x = W * (0.27 if k == 0 else 0.73)
        start = 0.15 + k * float(s.get("delay", 0.9))
        sc = appear(t, start, 0.5)
        paste_center(img, card(600, 560), x, H / 2 - 30, sc)
        if sc > 0.05:
            paste_center(img, emoji(it.get("emoji", "❓"), 220), x, H / 2 - 140 + _float(t, k, 8), sc)
            paste_center(img, text_sprite(it["text"], it.get("size", 62), INK, 0, max_w=540), x, H / 2 + 110, sc)
    paste_center(img, text_sprite(sign, 150, accent, 10, INK), W / 2, H / 2 - 30,
                 appear(t, 0.15 + float(s.get("delay", 0.9)) * 0.6, 0.4))
    if s.get("text"):
        paste_center(img, text_sprite(s["text"], 64, (255, 255, 255), 8, INK), W / 2, 195, appear(t, 0.1))


_NUM = re.compile(r"\d[\d,]*")


def shot_big(img, s, t, accent):
    """大きな数字・言葉。count: true なら数字が0から増えていく。"""
    text = s["text"]
    if s.get("count"):
        m = _NUM.search(text)
        if m:
            target = int(m.group().replace(",", ""))
            cur = int(round(target * ease_out(t / float(s.get("count_secs", 1.6)))))
            text = text[: m.start()] + f"{cur:,}" + text[m.end():]
    sc = appear(t, 0.0, 0.5)
    if s.get("emoji"):
        paste_center(img, emoji(s["emoji"], 200), W / 2, 230 + _float(t, amp=10), appear(t, 0.1))
    paste_center(img, text_sprite(text, s.get("size", 190), accent, 12, INK), W / 2, H / 2 + 10, sc)
    if s.get("sub"):
        paste_center(img, text_sprite(s["sub"], 70, (255, 255, 255), 8, INK), W / 2, H / 2 + 200, appear(t, 0.7))


def shot_chapter(img, s, t, accent):
    """「1日目」などの区切り。帯がシュッと横切る。"""
    p = ease_out(t / 0.5)
    d = ImageDraw.Draw(img)
    bh = 300
    x1 = -W + p * W * 1.0
    d.polygon([(x1, H / 2 - bh / 2), (x1 + W + 120, H / 2 - bh / 2), (x1 + W, H / 2 + bh / 2), (x1 - 120, H / 2 + bh / 2)],
              fill=accent + (255,))
    paste_center(img, text_sprite(s["text"], 170, INK), W / 2 + (1 - p) * -300, H / 2 - 10, 1.0 if p > 0.3 else 0)
    if s.get("sub"):
        paste_center(img, text_sprite(s["sub"], 60, (255, 255, 255), 7, INK), W / 2, H / 2 + 230, appear(t, 0.5))
    if s.get("emoji"):
        paste_center(img, emoji(s["emoji"], 170), W / 2 - 520, H / 2 - 10 + _float(t, amp=8), appear(t, 0.4))


def shot_icons(img, s, t, accent):
    """アイコンを横に並べて、順番にポンッと出す（下に短い説明）。"""
    items = s["items"]
    n = len(items)
    gap = min(520, (W - 200) / max(n, 1))
    for k, it in enumerate(items):
        x = W / 2 + (k - (n - 1) / 2) * gap
        st = 0.2 + k * float(s.get("stagger", 0.6))
        sc = appear(t, st)
        paste_center(img, emoji(it["emoji"], 230), x, H / 2 - 60 + _float(t, k, 10), sc, angle=_float(t, k, 5, 1.1))
        if it.get("text"):
            paste_center(img, text_sprite(it["text"], 56, (255, 255, 255), 7, INK, max_w=int(gap - 30)),
                         x, H / 2 + 140, sc)
    if s.get("text"):
        paste_center(img, text_sprite(s["text"], 72, (255, 255, 255), 9, INK), W / 2, 195, appear(t, 0.0))


def shot_list(img, s, t, accent):
    """チェックつきの箇条書き。1行ずつ出る。"""
    items = s["items"]
    if s.get("title"):
        paste_center(img, text_sprite(s["title"], 76, (255, 255, 255), 9, INK), W / 2, 195, appear(t, 0.0))
    paste_center(img, card(1300, 140 * len(items) + 80), W / 2, H / 2 + 50, appear(t, 0.1, 0.4))
    top = H / 2 + 50 - (140 * len(items)) / 2 + 70
    for k, it in enumerate(items):
        st = 0.5 + k * float(s.get("stagger", 0.9))
        a = ease_out((t - st) / 0.35) if t >= st else 0
        y = top + k * 140
        paste_center(img, emoji("✅", 80), W / 2 - 540, y, a)
        sp = text_sprite(it, 62, INK, 0, max_w=1050, align="left")
        if a > 0:
            paste_center(img, sp, W / 2 - 480 + sp.width / 2 + (1 - a) * 60, y, 1.0, alpha=a)


def shot_brain(img, s, t, accent):
    """脳のゴミ出し。mode: clean（ゴミが流れ出ていく）／dirty（ゴミがたまっていく）"""
    cx, cy = W / 2, H / 2 + 20
    paste_center(img, emoji("🧠", 380), cx, cy + _float(t, amp=8), appear(t, 0.0, 0.5))
    rng = random.Random(7)
    d = ImageDraw.Draw(img)
    dirty = s.get("mode") == "dirty"
    for k in range(46):
        ang = rng.uniform(0, 2 * math.pi)
        sp = rng.uniform(0.25, 0.6)
        ph = rng.random()
        col = rng.choice([(150, 120, 90), (120, 140, 90), (170, 150, 110)])
        if dirty:
            show = clamp((t - k * 0.12) / 0.3)
            if show <= 0:
                continue
            rr = rng.uniform(40, 160)
            x, y = cx + rr * math.cos(ang), cy - 20 + rr * 0.8 * math.sin(ang)
            r = 9 + 4 * show
            d.ellipse([x - r, y - r, x + r, y + r], fill=col + (int(230 * show),))
        else:
            p = (t * sp + ph) % 1
            rr = 90 + p * 600
            x, y = cx + rr * math.cos(ang), cy - 20 + rr * 0.8 * math.sin(ang)
            r = 10 * (1 - p) + 3
            d.ellipse([x - r, y - r, x + r, y + r], fill=(120, 200, 255, int(220 * (1 - p))))
    if s.get("text"):
        paste_center(img, text_sprite(s["text"], 72, (255, 255, 255), 9, INK), W / 2, 195, appear(t, 0.3))


def shot_warning(img, s, t, accent):
    """注意（黄色と黒の帯）。"""
    sc = appear(t, 0.0)
    w, h = 1400, 360
    c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([0, 0, w, h], radius=36, fill=(255, 214, 10))
    off = (t * 80) % 80
    for x in range(-80, w + 80, 80):
        d.polygon([(x + off, 0), (x + off + 40, 0), (x + off - 10, 50), (x + off - 50, 50)], fill=INK)
        d.polygon([(x + off, h - 50), (x + off + 40, h - 50), (x + off - 10, h), (x + off - 50, h)], fill=INK)
    paste_center(img, c, W / 2, H / 2, sc)
    paste_center(img, text_sprite(s["text"], 74, INK, 0, max_w=1250), W / 2, H / 2, sc)
    paste_center(img, emoji("⚠️", 150), W / 2, H / 2 - 290 + _float(t, amp=8), appear(t, 0.3))


def shot_newspaper(img, s, t, accent):
    """古い新聞風の記事。year と headline。"""
    sc = appear(t, 0.0, 0.6)
    w, h = 1100, 760
    c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, w, h], fill=(242, 232, 205))
    d.rectangle([30, 30, w - 30, h - 30], outline=(90, 80, 60), width=4)
    d.line([60, 190, w - 60, 190], fill=(90, 80, 60), width=6)
    d.text((w / 2, 110), s.get("paper", "THE DAILY NEWS"), font=font(70), fill=(60, 50, 40), anchor="mm")
    hl = text_sprite(s["headline"], 78, (40, 30, 25), 0, max_w=w - 140)
    c.alpha_composite(hl, (int(w / 2 - hl.width / 2), 240))
    rng = random.Random(3)
    for k in range(9):
        y = 260 + hl.height + k * 34
        if y > h - 70:
            break
        d.rectangle([80, y, 80 + rng.randint(600, 940), y + 14], fill=(170, 160, 140))
    paste_center(img, c.resize((990, 684)), W / 2 + 120, H / 2 - 20, sc, angle=-4 + _float(t, amp=1, speed=0.8))
    if s.get("year"):
        paste_center(img, text_sprite(s["year"], 110, accent, 10, INK), 330, 230, appear(t, 0.4))


SHOTS = {
    "title": shot_title, "clock": shot_clock, "mascot": shot_mascot, "equal": shot_equal, "big": shot_big,
    "chapter": shot_chapter, "icons": shot_icons, "list": shot_list, "brain": shot_brain,
    "warning": shot_warning, "newspaper": shot_newspaper,
}


def draw(img: Image.Image, shot: dict, t: float, accent) -> None:
    fn = SHOTS.get(shot.get("type", "title"))
    if fn is None:
        raise ValueError(f"知らない場面の種類です: {shot.get('type')}（使えるもの: {', '.join(SHOTS)}）")
    fn(img, shot, t, accent)
