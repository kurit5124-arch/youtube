"""アニメ風の動く画面（みんなの裁判用）。

1 フレームずつ描いて ffmpeg に流し込む。
- キャラクター（絵文字のステッカー）が声の大きさに合わせて弾む＝しゃべっているように見える
- 吹き出しの文字が 1 文字ずつ出る
- 集中線・ポップイン・画面の揺れ・「勝訴」のハンコなど、マンガ／アニメの演出
"""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import illust
from .models import Scene, VideoPlan
from .render import FPS, H, W, emoji_image, wrap

# (背景の色1, 背景の色2, 集中線の色, アクセント)
THEMES = [
    ((255, 214, 92), (255, 140, 66), (255, 246, 214), (230, 57, 70)),
    ((120, 214, 255), (88, 120, 255), (224, 244, 255), (255, 92, 141)),
    ((255, 170, 205), (190, 110, 255), (255, 232, 245), (60, 60, 200)),
    ((160, 235, 170), (40, 170, 140), (232, 255, 236), (255, 120, 40)),
]
INK = (24, 24, 32)
RED = (230, 57, 70)
BLUE = (40, 110, 230)


# ---------------------------------------------------------------- 小道具
def _ease_back(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _ease_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def envelope(audio: Path, frames: int) -> np.ndarray:
    """音声の大きさ（0〜1）をフレームごとに返す。口パク代わりの弾みに使う。"""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    hop = 16000 // FPS
    env = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)) if i * hop < len(x) else 0.0
                    for i in range(frames)])
    if env.max() > 0:
        env = env / env.max()
    return np.convolve(env, np.ones(3) / 3, mode="same")


def sticker(text: str, height: int) -> Image.Image | None:
    """絵文字を白フチ＋影つきのステッカーにする。"""
    im = emoji_image(text, height)
    if im is None:
        return None
    pad = 24
    base = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    base.alpha_composite(im, (pad, pad))
    a = base.getchannel("A").filter(ImageFilter.MaxFilter(17))
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 90))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(6)).point(lambda v: v * 0.45))
    out.alpha_composite(shadow, (6, 10))
    white = Image.new("RGBA", base.size, (255, 255, 255, 255))
    white.putalpha(a)
    out.alpha_composite(white)
    out.alpha_composite(base)
    return out


def _paste_scaled(img: Image.Image, im: Image.Image, cx: float, cy: float, sx: float, sy: float | None = None,
                  angle: float = 0.0) -> None:
    sy = sx if sy is None else sy
    if sx <= 0.01 or sy <= 0.01:
        return
    w, h = max(1, int(im.width * sx)), max(1, int(im.height * sy))
    t = im.resize((w, h), Image.BILINEAR)
    if angle:
        t = t.rotate(angle, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(t, (int(cx - t.width / 2), int(cy - t.height / 2)))


def _outlined(d: ImageDraw.ImageDraw, xy, text, font, fill=(255, 255, 255), stroke=INK, width=10, anchor="mm"):
    d.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=width, stroke_fill=stroke)


def _speed_lines(theme, seed: int, strength: float) -> Image.Image:
    """集中線の背景。"""
    c1, c2, line, _ = theme
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(0, H, 4):
        t = y / H
        d.rectangle([0, y, W, y + 4], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    rng = random.Random(seed)
    cx, cy = W / 2, H * 0.42
    r = 2400
    n = 90
    for i in range(n):
        a = (i + rng.random() * 0.6) / n * 2 * math.pi
        w = rng.uniform(0.004, 0.018) * strength
        inner = rng.uniform(300, 520)
        pts = [(cx + math.cos(a - w) * r, cy + math.sin(a - w) * r),
               (cx + math.cos(a + w) * r, cy + math.sin(a + w) * r),
               (cx + math.cos(a) * inner, cy + math.sin(a) * inner)]
        d.polygon(pts, fill=line)
    # スクリーントーン風のドット
    tone = Image.new("L", (W, H), 0)
    td = ImageDraw.Draw(tone)
    for y in range(0, H, 28):
        for x in range((y // 28 % 2) * 14, W, 28):
            td.ellipse([x - 3, y - 3, x + 3, y + 3], fill=40)
    img.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0), tone)
    return img


def _bubble(d: ImageDraw.ImageDraw, box, tail_to=None, fill=(255, 255, 255), outline=INK):
    x0, y0, x1, y1 = box
    if tail_to:
        tx, ty = tail_to
        mx = min(max(tx, x0 + 90), x1 - 90)
        base_y = y1 if ty > y1 else y0
        d.polygon([(mx - 45, base_y), (mx + 45, base_y), (tx, ty)], fill=fill, outline=outline, width=8)
    d.rounded_rectangle(box, radius=56, fill=fill, outline=outline, width=8)
    if tail_to:  # しっぽと吹き出しのつなぎ目の線を消す
        tx, ty = tail_to
        mx = min(max(tx, x0 + 90), x1 - 90)
        base_y = y1 if ty > y1 else y0
        d.line([(mx - 37, base_y), (mx + 37, base_y)], fill=fill, width=12)


_PUNCT = set("、。，．！？!?「」『』（）()・…ー〜 　\n")
_SMALL = set("ゃゅょっぁぃぅぇぉャュョッァィゥェォ")


def _read_weight(ch: str) -> float:
    """1 文字を読み上げるのにかかるおおよその長さ（かな 1 文字 = 1）。"""
    if ch in _PUNCT:
        return 0.0
    if ch in _SMALL:
        return 0.5
    if "\u4e00" <= ch <= "\u9fff" or ch == "々":
        return 1.8   # 漢字は 2 音くらい
    if ch.isdigit():
        return 1.3
    if ch.isascii():
        return 1.2
    return 1.0


class _TextBlock:
    """吹き出しの中の文字（1 文字ずつ表示）。"""

    def __init__(self, text: str, font_path: str, max_w: int, max_h: int, start: int = 78, minimum: int = 40):
        size = start
        while True:
            self.font = ImageFont.truetype(font_path, size)
            self.lines = wrap(text, self.font, max_w)
            self.lh = int(size * 1.32)
            if len(self.lines) * self.lh <= max_h or size <= minimum:
                break
            size -= 4
        self.total = sum(len(s) for s in self.lines)
        w = np.cumsum([_read_weight(c) for c in "".join(self.lines)]) if self.total else np.zeros(0)
        self._cum = w / w[-1] if self.total and w[-1] > 0 else np.linspace(0, 1, self.total)

    def shown_at(self, progress: float) -> int:
        """読み上げの進み具合（0〜1）に合わせて、何文字目まで出すか。"""
        if progress >= 0.999:
            return self.total
        return int(np.searchsorted(self._cum, progress, side="right"))

    @property
    def height(self) -> int:
        return len(self.lines) * self.lh

    def draw(self, d, cx: float, top: float, shown: int, fill=INK):
        left_n = shown
        y = top + self.lh / 2
        for ln in self.lines:
            part = ln[:max(0, left_n)]
            left_n -= len(ln)
            # 行の位置は全文で決めておき、文字が増えても左右に動かないようにする
            x0 = cx - self.font.getlength(ln) / 2
            if part:
                d.text((x0, y), part, font=self.font, fill=fill, anchor="lm")
            y += self.lh


# ---------------------------------------------------------------- 立ち絵
class Character:
    """ナレーター（ずんだもん など）の立ち絵。口を閉じた絵と開いた絵があれば口パクする。"""

    def __init__(self, cc: dict):
        self.height = int(cc.get("height", 600))
        self.closed = self._load(cc.get("image"))
        self.open = self._load(cc.get("mouth_open")) or self.closed
        self.flip = bool(cc.get("flip", False))

    def _load(self, path: str | None) -> Image.Image | None:
        if not path or not Path(path).exists():
            return None
        im = Image.open(path).convert("RGBA")
        box = im.getbbox()
        im = im.crop(box) if box else im
        im = im.resize((max(1, round(im.width * self.height / im.height)), self.height), Image.LANCZOS)
        return im

    @property
    def ok(self) -> bool:
        return self.closed is not None

    def draw(self, img: Image.Image, t: float, env: float, enter: float = 1.0) -> None:
        im = self.open if env > 0.28 else self.closed
        if self.flip:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        # 立ち絵は画面の右下。下の方はショートの文字と重なるので少し下にはみ出させる
        breathe = math.sin(t * 2.4) * 6
        x = W - im.width * 0.78 + (1 - _ease_out(enter)) * 500
        y = H - self.height + 120 - breathe - env * 10
        img.alpha_composite(im, (int(x), int(y)))


_CHAR_CACHE: dict[str, Character] = {}


def character(cfg: dict) -> Character | None:
    cc = cfg.get("character") or {}
    if not cc.get("enabled", True) or not cc.get("image"):
        return None
    key = repr(sorted(cc.items()))
    if key not in _CHAR_CACHE:
        _CHAR_CACHE[key] = Character(cc)
    ch = _CHAR_CACHE[key]
    return ch if ch.ok else None


# ---------------------------------------------------------------- 1 場面ぶんの描画
class SceneAnimator:
    def _typed(self, b: "_TextBlock", t: float, delay: float = 0.15) -> int:
        if self.progress is not None:
            # 字幕は声より少しだけ先に出すと読みやすい（0.15 秒）
            i = min(int((t + 0.15) * FPS), len(self.progress) - 1)
            return b.shown_at(float(self.progress[i]))
        return int(b.total * min(1.0, max(0.0, (t - delay) / self.type_until)))

    def __init__(self, plan: VideoPlan, scene: Scene, idx: int, total: int, font_path: str, dur: float,
                 narrator: Character | None = None, env=None):
        self.plan, self.s, self.idx, self.total, self.fp, self.dur = plan, scene, idx, total, font_path, dur
        self.narrator = narrator
        rng = random.Random(plan.seed)
        self.theme = THEMES[rng.randrange(len(THEMES))]
        strong = scene.kind in ("hook", "verdict") or scene.reveal
        self.bgs = [_speed_lines(self.theme, plan.seed * 100 + idx * 7 + k, 1.6 if strong else 1.0)
                    for k in range(3)]
        self.f = lambda n: ImageFont.truetype(font_path, n)  # noqa: E731
        self.role = "left" if "原告" in scene.label else "right" if "被告" in scene.label else "center"
        big = 300 if scene.kind in ("hook", "outro") else 250
        self.char = sticker(scene.emoji, big) if scene.emoji else None
        text = scene.text.strip("「」")
        if scene.choices:
            self.block = _TextBlock(text, font_path, 780, 220, start=70)
        elif scene.kind in ("hook", "outro"):
            self.block = None
        else:
            self.block = _TextBlock(text, font_path, 800, 320 if narrator else 380, start=76)
        self.type_until = max(0.6, (dur - 0.4) * 0.75)  # 声の情報が無いとき、この秒数で全文が出る
        self.progress = None
        if env is not None and len(env):
            voiced = (np.asarray(env) > 0.1).astype(float)
            if voiced.sum() > 0:
                self.progress = np.cumsum(voiced) / voiced.sum()
        self.art = scene.art or {}
        if self.art:
            self.bg_art, self.front_art = illust.background(self.art.get("bg", "home"), plan.seed)
            self.cast = self.art.get("cast", [])
            self.fx = {k: sticker(c["fx"], 120) for k, c in enumerate(self.cast) if c.get("fx")}
            self.block = _TextBlock(scene.text.strip("「」"), font_path, 840, 320, start=66) if scene.text else None

    def _header(self, d):
        _outlined(d, (W // 2, 250), self.plan.header, self.f(96), fill=(255, 255, 255), width=12)
        tag = self.plan.subheader
        tf = self.f(54)
        tw = tf.getlength(tag) + 70
        d.rounded_rectangle([W / 2 - tw / 2, 330, W / 2 + tw / 2, 410], radius=40, fill=INK)
        d.text((W // 2, 370), tag, font=tf, fill=(255, 255, 255), anchor="mm")

    def _label(self, img, t):
        if not self.s.label or self.s.kind == "hook":
            return
        col = RED if self.role == "left" else BLUE if self.role == "right" else self.theme[3]
        f = self.f(62)
        w = int(f.getlength(self.s.label) + 80)
        tag = Image.new("RGBA", (w + 20, 120), (0, 0, 0, 0))
        td = ImageDraw.Draw(tag)
        td.rectangle([14, 18, w + 14, 108], fill=INK)
        td.rectangle([4, 8, w + 4, 98], fill=col)
        td.text((w // 2 + 4, 53), self.s.label, font=f, fill=(255, 255, 255), anchor="mm")
        k = _ease_back(t / 0.3)
        x = {"left": 60 + w / 2, "right": W - 60 - w / 2}.get(self.role, W / 2)
        _paste_scaled(img, tag, x - (1 - k) * (600 if self.role == "left" else -600 if self.role == "right" else 0),
                      500, 1.0, angle=-4 if self.role != "right" else 4)

    # --- イラストの場面
    def _illust_frame(self, i: int, env: float) -> Image.Image:
        t = i / FPS
        img = self.bg_art.copy()
        talk = env * (1 if t < self.dur - 0.2 else 0)
        speaker = self.art.get("speaker")
        for k, c in enumerate(self.cast):
            enter = 1.0 if self.idx == 0 else _ease_back((t - k * 0.12) / 0.35)
            if enter <= 0:
                continue
            speaking = speaker == k and talk > 0.25
            blink = (t + k * 1.3) % 3.4 < 0.12
            im = illust.person(c.get("who", "man"), c.get("expr", "neutral"), speaking, blink, bool(c.get("bike")))
            if c.get("flip"):
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            sc = float(c.get("scale", 1.0)) * enter
            hop = (talk * 18 if speaker == k else 0) + illust.bob(t, k)
            jitter = random.uniform(-10, 10) if c.get("expr") == "shock" and t < 0.5 else 0
            cx = c.get("x", 0.5) * W + jitter
            feet = c.get("y", illust.FLOOR_Y)
            w, h = int(im.width * sc), int(im.height * sc)
            if w < 2 or h < 2:
                continue
            img.alpha_composite(illust.shadow(int(w * 0.7)), (int(cx - w * 0.35), int(feet - 30)))
            img.alpha_composite(im.resize((w, h), Image.BILINEAR), (int(cx - w / 2), int(feet - h - hop)))
            fx = self.fx.get(k)
            if fx is not None:
                _paste_scaled(img, fx, cx + w * 0.38, feet - h - hop + 60 + math.sin(t * 6) * 8, enter * 0.9)
        if self.front_art is not None:
            img.alpha_composite(self.front_art)
        d = ImageDraw.Draw(img)
        self._header(d)
        self._label(img, t)
        if self.block:  # 字幕（上の方の吹き出し。1 文字ずつ出る）
            b = self.block
            top = 560
            k = 1.0 if self.idx == 0 else _ease_back((t - 0.05) / 0.3)
            if k > 0:
                layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                ld = ImageDraw.Draw(layer)
                box = [70, top, W - 70, top + b.height + 80]
                tail = None
                if speaker is not None and speaker < len(self.cast):
                    tail = (self.cast[speaker].get("x", 0.5) * W, box[3] + 90)
                _bubble(ld, box, tail)
                shown = b.total if self.idx == 0 else self._typed(b, t)
                b.draw(ld, W / 2, top + 40, shown)
                if abs(k - 1) < 1e-3:
                    img.alpha_composite(layer)
                else:
                    ccx, ccy = W / 2, (box[1] + box[3]) / 2
                    _paste_scaled(img, layer, ccx * (1 - k) + W * k / 2, ccy * (1 - k) + H * k / 2, k)
        big = self.art.get("big")
        if big:  # 大きな数字・言葉をドンと出す
            k = 0.85 + 0.15 * _ease_out(t / 0.3) if self.idx == 0 else _ease_out((t - 0.25) / 0.25)
            if k > 0:
                f = self.f(170)
                while f.getlength(big) > 900 and f.size > 80:
                    f = self.f(f.size - 10)
                layer = Image.new("RGBA", (W, 320), (0, 0, 0, 0))
                _outlined(ImageDraw.Draw(layer), (W // 2, 160), big, f, fill=tuple(self.art.get("big_color", (255, 70, 70))),
                          stroke=(255, 255, 255), width=16)
                _paste_scaled(img, layer, W / 2, self.art.get("big_y", 1060), 2.2 - 1.2 * k, angle=-3)
        out = img.convert("RGB")
        if self.art.get("cta"):
            self._cta(img, t)
        out = img.convert("RGB") if self.art.get("cta") else out
        if (big and (0.0 if self.idx == 0 else 0.25) < t < 0.7) or self.art.get("shake") and t < 0.45:
            amp = 16 * (1 - min(1, (t % 0.45) / 0.45))
            out = out.transform(out.size, Image.AFFINE, (1, 0, random.uniform(-amp, amp), 0, 1, random.uniform(-amp, amp)),
                                fillcolor=(0, 0, 0))
        return out

    def _word_time(self, word: str, fallback: float) -> float:
        """字幕の中の word を読み上げ終わる時刻（声の進みから逆算）。"""
        b = self.block
        text = "".join(b.lines) if b else ""
        pos = text.find(word)
        if pos < 0 or self.progress is None:
            return self.dur * fallback
        need = pos + len(word)
        for i in range(len(self.progress)):
            if b.shown_at(float(self.progress[i])) >= need:
                return i / FPS
        return self.dur * fallback

    def _cta(self, img: Image.Image, t: float) -> None:
        """「チャンネル登録」「高評価」のボタン。指がタップして登録済みになる。"""
        k = _ease_back((t - 0.2) / 0.35)
        if k <= 0:
            return
        t_sub, t_like = self._word_time("登録", 0.5), self._word_time("高評価", 0.68)
        tapped = t > t_sub + 0.1
        y = self.art.get("cta_y", 1060)
        layer = Image.new("RGBA", (W, 240), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        bx0, bx1 = 90, 640
        ld.rounded_rectangle([bx0 + 8, 30, bx1 + 8, 170], radius=70, fill=(0, 0, 0, 90))
        ld.rounded_rectangle([bx0, 20, bx1, 160], radius=70, fill=(120, 120, 128) if tapped else (230, 33, 23),
                             outline=INK, width=6)
        ld.text(((bx0 + bx1) / 2, 90), "登録済み" if tapped else "チャンネル登録", font=self.f(60),
                fill=(255, 255, 255), anchor="mm")
        lx0, lx1 = 680, 990
        ld.rounded_rectangle([lx0 + 8, 30, lx1 + 8, 170], radius=70, fill=(0, 0, 0, 90))
        ld.rounded_rectangle([lx0, 20, lx1, 160], radius=70, fill=(255, 255, 255), outline=INK, width=6)
        thumb = emoji_image("👍", 84)
        if thumb is not None:
            pop = 1 + 0.25 * max(0.0, 1 - abs(t - t_like - 0.1) / 0.2) if t > t_like - 0.1 else 1.0
            th = thumb.resize((int(thumb.width * pop), int(thumb.height * pop)))
            layer.alpha_composite(th, (int(lx0 + 95 - th.width / 2), int(90 - th.height / 2)))
        ld.text((lx0 + 215, 90), "高評価", font=self.f(50), fill=INK, anchor="mm")
        _paste_scaled(img, layer, W / 2, y, k)
        # 指（タップする手）
        hand = emoji_image("👆", 120)
        if hand is not None and t_sub - 0.7 < t < t_like + 0.9:
            if t < t_sub:
                hx, hy = (bx0 + bx1) / 2 + 60, y + 150 + (t_sub - t) * 230
            elif t < t_like:
                q = (t - t_sub) / (t_like - t_sub)
                hx, hy = (bx0 + bx1) / 2 + 60 + q * ((lx0 + 95) - (bx0 + bx1) / 2 - 60), y + 150
            else:
                hx, hy = lx0 + 95, y + 150
            press = 0.88 if (t_sub < t < t_sub + 0.15) or (t_like < t < t_like + 0.15) else 1.0
            _paste_scaled(img, hand, hx, hy, press)

    def frame(self, i: int, env: float) -> Image.Image:
        if self.art:
            return self._illust_frame(i, env)
        t = i / FPS
        s = self.s
        bg = self.bgs[(i // 3) % 3].convert("RGBA")  # 線が少しずつ揺れる（アニメの「ゆらぎ」）
        img = bg.copy()
        d = ImageDraw.Draw(img)
        self._header(d)
        talk = env * (1 if t < self.dur - 0.2 else 0)
        if self.narrator:
            self.narrator.draw(img, t + self.idx * 3.1, talk, enter=t / 0.4 if self.idx == 0 else 1.0)
            d = ImageDraw.Draw(img)
        self._label(img, t)

        if s.kind == "hook":
            self._hook(img, d, t, talk)
        elif s.choices:
            self._choices(img, d, t, talk)
        elif s.kind == "outro":
            self._outro(img, d, t, talk)
        else:
            self._talk(img, d, t, talk)

        out = img.convert("RGB")
        # 登場の瞬間に画面を揺らす
        if s.kind == "hook" and t < 0.45 or (s.reveal and 0.6 < t < 0.95):
            amp = 18 * (1 - (t % 0.45) / 0.45)
            out = out.transform(out.size, Image.AFFINE, (1, 0, random.uniform(-amp, amp), 0, 1,
                                                         random.uniform(-amp, amp)), fillcolor=self.theme[1])
        return out

    # --- 種類ごとの描き方
    def _hook(self, img, d, t, talk):
        if self.char:
            k = _ease_back(t / 0.4)
            bob = math.sin(t * 6) * 10
            _paste_scaled(img, self.char, W / 2, 820 + bob - talk * 25, k * (1 + talk * 0.05), k * (1 - talk * 0.03))
        k = _ease_out((t - 0.15) / 0.3)
        if k > 0:
            title = self.s.text
            f = self.f(120)
            while f.getlength(title) > 960 and f.size > 60:
                f = self.f(f.size - 6)
            layer = Image.new("RGBA", (W, 240), (0, 0, 0, 0))
            _outlined(ImageDraw.Draw(layer), (W // 2, 120), title, f, fill=(255, 255, 255), width=14)
            _paste_scaled(img, layer, W / 2, 1230, 1.6 - 0.6 * k)
        ft = self.f(58)
        tag = self.s.label
        w = ft.getlength(tag) + 60
        d.rectangle([W / 2 - w / 2, 1360, W / 2 + w / 2, 1440], fill=self.theme[3])
        d.text((W // 2, 1400), tag, font=ft, fill=(255, 255, 255), anchor="mm")

    def _talk(self, img, d, t, talk):
        # キャラクター
        cx = {"left": 270, "right": W - 270}.get(self.role, W / 2)
        cy = (1170 if self.narrator else 1290) if self.role != "center" else 780
        if self.char:
            k = _ease_back(t / 0.35)
            bob = math.sin(t * 5 + self.idx) * 8
            _paste_scaled(img, self.char, cx, cy + bob - talk * 30, k * (1 + talk * 0.06), k * (1 - talk * 0.04),
                          angle=math.sin(t * 9) * talk * 6)
        # 吹き出し
        b = self.block
        if self.role == "center":
            top = 1010
            box = [80, top, W - 80, top + b.height + 90]
            tail = (W / 2, 930) if self.char else None
        else:
            top = 600 if self.narrator else 640
            box = [80, top, W - 80, top + b.height + 90]
            tail = (cx, cy - 140)
        k = _ease_back((t - 0.1) / 0.3)
        if k <= 0:
            return
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        _bubble(ld, box, tail)
        shown = self._typed(b, t, 0.2)
        b.draw(ld, W / 2, box[1] + 45, shown)
        if abs(k - 1) < 1e-3:
            img.alpha_composite(layer)
        else:
            ccx, ccy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            region = layer.crop((0, 0, W, H))
            _paste_scaled(img, region, W / 2 + (ccx - W / 2) * (1 - k), H / 2 + (ccy - H / 2) * (1 - k), k)

    def _choices(self, img, d, t, talk):
        s, b = self.s, self.block
        box = [80, 600, W - 80, 600 + b.height + 90]
        _bubble(d, box)
        shown = b.total if s.reveal or s.kind == "verdict" else int(b.total * min(1.0, max(0.0, t / 0.8)))
        b.draw(d, W / 2, box[1] + 45, shown)
        y0 = box[3] + 70
        for n, ch in enumerate(s.choices):
            col = RED if n == 0 else BLUE
            delay = 0.5 + n * 0.25 if not s.reveal else 0
            k = _ease_back((t - delay) / 0.35)
            if k <= 0:
                continue
            win = s.reveal and s.answer == n
            lose = s.reveal and s.answer is not None and s.answer != n
            pulse = 1 + (0.03 * math.sin(t * 8 + n) if not s.reveal else 0)
            panel = Image.new("RGBA", (920, 200), (0, 0, 0, 0))
            pd = ImageDraw.Draw(panel)
            fillc = (200, 200, 205) if lose else col
            pd.rounded_rectangle([14, 18, 914, 194], radius=40, fill=INK)
            pd.rounded_rectangle([4, 6, 904, 182], radius=40, fill=fillc, outline=INK, width=8)
            f = self.f(76)
            while f.getlength(ch) > 800 and f.size > 40:
                f = self.f(f.size - 4)
            _outlined(pd, (454, 94), ch, f, fill=(255, 255, 255), width=6)
            sx = (1 - k) * (-900 if n == 0 else 900)
            _paste_scaled(img, panel, W / 2 + sx, y0 + n * 240 + 100, pulse * (1.06 if win else 1.0))
            if win:
                self._stamp(img, t, W / 2 + 330, y0 + n * 240 + 20)

    def _stamp(self, img, t, x, y):
        k = (t - 0.6) / 0.25
        if k <= 0:
            return
        word = self.s.badge or "勝訴"
        f = self.f(92)
        w = int(f.getlength(word) + 70)
        st = Image.new("RGBA", (w + 20, 160), (0, 0, 0, 0))
        sd = ImageDraw.Draw(st)
        sd.rounded_rectangle([10, 10, w + 10, 150], radius=18, outline=RED, width=12, fill=(255, 255, 255, 230))
        sd.text((w // 2 + 10, 80), word, font=f, fill=RED, anchor="mm")
        scale = 2.4 - 1.4 * _ease_out(k)
        _paste_scaled(img, st, x, y, scale, angle=-14)

    def _outro(self, img, d, t, talk):
        if self.char:
            k = _ease_back(t / 0.35)
            _paste_scaled(img, self.char, W / 2, 760 + math.sin(t * 6) * 12 - talk * 25, k * (1 + talk * 0.05))
        y = 1080
        for ln in self.s.text.split("\n"):
            _outlined(d, (W // 2, y), ln, self.f(104), fill=(255, 255, 255), width=12)
            y += 140
        for n, (letter, col) in enumerate((("A", RED), ("B", BLUE))):
            r = 90 * (1 + 0.08 * math.sin(t * 7 + n * math.pi))
            x = W / 2 + (-170 if n == 0 else 170)
            d.ellipse([x - r, 1560 - r, x + r, 1560 + r], fill=col, outline=INK, width=8)
            _outlined(d, (x, 1560), letter, self.f(110), width=6)


def render_segment(plan: VideoPlan, scene: Scene, idx: int, total: int, font_path: str,
                   audio: Path, dur: float, out: Path, cfg: dict | None = None) -> None:
    frames = max(1, int(round(dur * FPS)))
    env = envelope(audio, frames)
    anim = SceneAnimator(plan, scene, idx, total, font_path, dur, character(cfg or {}), env)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(audio),
         "-filter_complex", "[1:a]apad,aresample=44100,aformat=channel_layouts=stereo[a]",
         "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", str(out)],
        stdin=subprocess.PIPE,
    )
    try:
        for i in range(frames):
            proc.stdin.write(anim.frame(i, float(env[i])).tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("アニメの書き出しに失敗しました")
