"""YouTube 用のサムネイル（1280x720）を作る。

動画の一番盛り上がる場面を背景にして、曲名を大きく・目立つように載せる。
デザインは3種類（a: 中央に大きく / b: 赤く激しく / c: グリッチ）。

  python -m musicvideo.thumbnail output/overdrive_landscape.mp3 --title OVERDRIVE
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .analyze import analyze
from .scene import FONT_CANDIDATES, SUB_FONT_CANDIDATES, NeonDriveScene, _font, _hue_matrix

TW, TH = 1280, 720


def _background(audio: Path, seed: int, hue: float = 0.0, t_offset: float = 1.5, scene: str = "neon") -> Image.Image:
    f = analyze(audio)
    hits = np.where(f.drop >= 0.999)[0]
    i = int(hits[0] + f.fps * t_offset) if len(hits) else f.n // 2
    i = min(i, f.n - 1)
    if scene == "city":
        from .scene_city import SkyCityScene
        sc = SkyCityScene(1920, 1080, f, title=" ", subtitle="", seed=seed)
    else:
        sc = NeonDriveScene(1920, 1080, f, title=" ", subtitle="", seed=seed)
    sc.post.hue[:] = hue
    f.drop[:] = 0  # 揺れ・フラッシュは入れない
    img = sc.render(i)
    img = cv2.resize(img, (TW, TH), interpolation=cv2.INTER_AREA)
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


def _gradient_text(text: str, font: ImageFont.FreeTypeFont, stops: list[tuple[float, tuple]], stroke=0):
    """縦グラデーションの文字（RGBA）"""
    bbox = font.getbbox(text, stroke_width=stroke)
    w, h = bbox[2] - bbox[0] + 20, bbox[3] - bbox[1] + 20
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((10 - bbox[0], 10 - bbox[1]), text, font=font, fill=255)
    ys = np.linspace(0, 1, h)
    pos = [p for p, _ in stops]
    cols = np.array([c for _, c in stops], np.float32)
    g = np.stack([np.interp(ys, pos, cols[:, k]) for k in range(3)], axis=1)
    rgb = np.repeat(g[:, None, :], w, axis=1).astype(np.uint8)
    img = Image.fromarray(rgb).convert("RGBA")
    img.putalpha(mask)
    return img, mask


def _glow(canvas: Image.Image, mask: Image.Image, xy, color, radius, strength=1.0):
    layer = Image.new("RGB", canvas.size, (0, 0, 0))
    m = Image.new("L", canvas.size, 0)
    m.paste(mask, xy)
    m = m.filter(ImageFilter.GaussianBlur(radius))
    layer.paste(Image.new("RGB", canvas.size, color), (0, 0), m)
    arr = np.asarray(canvas, np.float32) + np.asarray(layer, np.float32) * strength
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _fit_font(text, max_w, max_size, cands=FONT_CANDIDATES):
    size = max_size
    font = _font(cands, size)
    while font.getlength(text) > max_w and size > 30:
        size -= 6
        font = _font(cands, size)
    return font


def _darken(img: Image.Image, top=0.25, bottom=0.25, center=0.0) -> Image.Image:
    a = np.asarray(img, np.float32)
    ys = np.linspace(-1, 1, TH)[:, None, None]
    m = 1 - (center + (top - center) * np.clip(-ys, 0, 1) + (bottom - center) * np.clip(ys, 0, 1))
    return Image.fromarray(np.clip(a * m, 0, 255).astype(np.uint8))


def _badge(canvas: Image.Image, text: str, xy, fill, fg=(255, 255, 255), size=44):
    font = _font(SUB_FONT_CANDIDATES, size)
    d = ImageDraw.Draw(canvas)
    w = font.getlength(text)
    x, y = xy
    d.rounded_rectangle([x, y, x + w + 40, y + size + 26], radius=10, fill=fill)
    d.text((x + 20, y + 10), text, font=font, fill=fg)


CHROME = [(0, (40, 70, 170)), (0.42, (200, 240, 255)), (0.5, (255, 255, 255)),
          (0.53, (70, 10, 90)), (0.75, (240, 40, 140)), (1, (255, 210, 240))]
HOT = [(0, (255, 250, 200)), (0.45, (255, 170, 40)), (0.55, (255, 60, 40)), (1, (150, 0, 40))]


def design_a(bg: Image.Image, title: str, genre: str, bpm: str) -> Image.Image:
    """中央に巨大なクロム文字"""
    img = _darken(bg, top=0.45, bottom=0.35, center=0.15)
    font = _fit_font(title, TW * 0.92, 260)
    txt, mask = _gradient_text(title, font, CHROME)
    x, y = (TW - txt.width) // 2, int(TH * 0.47 - txt.height / 2)
    img = _glow(img, mask, (x, y), (255, 40, 200), 30, 1.3)
    outline = mask.filter(ImageFilter.MaxFilter(9))
    img.paste((40, 250, 255), (x, y), outline)
    img.paste(txt, (x, y), txt)
    _badge(img, f"{bpm} BPM", (40, 36), (255, 30, 90))
    sub = _font(SUB_FONT_CANDIDATES, 46)
    d = ImageDraw.Draw(img)
    s = f"{genre}  ·  ORIGINAL TRACK"
    d.text(((TW - sub.getlength(s)) / 2, y + txt.height + 6), s, font=sub, fill=(190, 250, 255))
    return img


def design_b(bg: Image.Image, title: str, genre: str, bpm: str) -> Image.Image:
    """赤く激しい：斜めの巨大文字＋左寄せ"""
    img = _darken(bg, top=0.3, bottom=0.5, center=0.2)
    font = _fit_font(title, TW * 0.78, 250)
    txt, mask = _gradient_text(title, font, HOT)
    # 少し傾ける
    txt = txt.rotate(6, resample=Image.BICUBIC, expand=True)
    mask = mask.rotate(6, resample=Image.BICUBIC, expand=True)
    x, y = 30, int(TH * 0.62 - txt.height / 2)
    img = _glow(img, mask, (x, y), (255, 40, 30), 40, 1.6)
    shadow = Image.new("RGBA", txt.size, (0, 0, 0, 0))
    shadow.putalpha(mask.point(lambda v: int(v * 0.8)))
    img.paste(shadow, (x + 12, y + 14), shadow)
    outline = mask.filter(ImageFilter.MaxFilter(11))
    img.paste((20, 0, 10), (x, y), outline)
    img.paste(txt, (x, y), txt)
    _badge(img, genre, (40, 40), (255, 255, 255), fg=(200, 0, 40), size=50)
    _badge(img, f"{bpm} BPM", (40, 128), (200, 0, 40), size=40)
    return img


def design_c(bg: Image.Image, title: str, genre: str, bpm: str) -> Image.Image:
    """グリッチ：RGB をずらした文字とノイズの帯"""
    img = _darken(bg, top=0.35, bottom=0.35, center=0.35)
    font = _fit_font(title, TW * 0.9, 250)
    _, mask = _gradient_text(title, font, CHROME)
    x, y = (TW - mask.width) // 2, int(TH * 0.5 - mask.height / 2)
    a = np.asarray(img, np.float32)
    m = np.zeros((TH, TW), np.float32)
    mm = np.asarray(mask, np.float32) / 255
    h, w = min(mm.shape[0], TH - y), min(mm.shape[1], TW - x)
    m[y:y + h, x:x + w] = mm[:h, :w]
    glow = cv2.GaussianBlur(m, (0, 0), 25)
    a += glow[..., None] * np.array([255, 40, 220]) * 1.2
    for dx, ch_col in ((-8, (0, 255, 255)), (8, (255, 0, 120))):
        sh = np.roll(m, dx, axis=1)
        a = a * (1 - sh[..., None] * 0.9) + sh[..., None] * np.array(ch_col) * 0.9
    a = a * (1 - m[..., None]) + m[..., None] * 255
    # 横のずれ（グリッチの帯）
    rng = np.random.default_rng(3)
    for _ in range(3):
        yy = int(rng.integers(y, y + h - 20))
        hh = int(rng.integers(4, 12))
        a[yy:yy + hh] = np.roll(a[yy:yy + hh], int(rng.integers(-25, 25)), axis=1)
    a[::3] *= 0.85  # 走査線
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    sub = _font(SUB_FONT_CANDIDATES, 44)
    d = ImageDraw.Draw(img)
    s = f"{genre}  ·  {bpm} BPM"
    d.text(((TW - sub.getlength(s)) / 2, y + h + 10), s, font=sub, fill=(200, 255, 255))
    return img


def make_thumbnails(audio: Path, title: str, out_prefix: Path, genre: str = "DARKSYNTH", scene: str = "neon",
                    bpm: str = "140", seed: int = 7, hue: float = 0.0) -> list[Path]:
    paths = []
    bg = _background(audio, seed, hue=hue, scene=scene)
    bg_red = _background(audio, seed, hue=22, scene=scene)
    for name, fn, b in (("a", design_a, bg), ("b", design_b, bg_red), ("c", design_c, bg)):
        p = Path(f"{out_prefix}_thumb_{name}.jpg")
        fn(b, title, genre, bpm).convert("RGB").save(p, quality=92)
        paths.append(p)
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("--title", default="OVERDRIVE")
    ap.add_argument("--genre", default="DARKSYNTH")
    ap.add_argument("--bpm", default="140")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--hue", type=float, default=0.0)
    a = ap.parse_args()
    for p in make_thumbnails(a.audio, a.title, a.audio.with_suffix(""), a.genre, a.bpm, a.seed, a.hue):
        print(p)
