"""イラストを描き、音の解析結果に合わせて1フレームずつ動かす。

- NeonDriveScene : プログラムで描くシンセウェーブ風イラスト（夕日・山・グリッド・車）
- ImageScene     : 好きなイラスト画像（AI で描いた絵など）を音に合わせて動かす
どちらも render(i) で i フレーム目の画像（float32, 0〜1, RGB）を返す。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .analyze import Features

FONT_CANDIDATES = [
    "assets/fonts/title.otf",
    "assets/fonts/title.ttf",
    "/usr/share/fonts/opentype/inter/InterDisplay-BlackItalic.otf",
    "/usr/share/fonts/opentype/inter/Inter-BlackItalic.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
SUB_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def _font(cands, size):
    for p in cands:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255


def _vgrad(h: int, w: int, stops: list[tuple[float, str]]) -> np.ndarray:
    ys = np.linspace(0, 1, h)
    pos = [p for p, _ in stops]
    cols = np.stack([_hex(c) for _, c in stops])
    g = np.stack([np.interp(ys, pos, cols[:, k]) for k in range(3)], axis=1).astype(np.float32)
    return np.repeat(g[:, None, :], w, axis=1)


def _blur(img: np.ndarray, sigma: float, down: int = 4) -> np.ndarray:
    """縮小してぼかしてから戻す（速い光のにじみ）"""
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, w // down), max(1, h // down)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma / down)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _pil_to_np(img: Image.Image) -> np.ndarray:
    return np.asarray(img, dtype=np.float32) / 255


def _noise(h, w, rng, scale) -> np.ndarray:
    """なめらかなノイズ（星雲用）"""
    out = np.zeros((h, w), np.float32)
    amp = 1.0
    s = scale
    for _ in range(4):
        sh, sw = max(2, int(h / s)), max(2, int(w / s))
        n = rng.random((sh, sw)).astype(np.float32)
        out += cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC) * amp
        amp *= 0.5
        s /= 2
    out -= out.min()
    return out / (out.max() + 1e-9)


def _hue_matrix(deg: float) -> np.ndarray:
    """RGB の色相を deg 度回す行列（明るさはほぼ保つ）"""
    c, s_ = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    k = 1 / 3
    sq = np.sqrt(k)
    return np.array([
        [c + (1 - c) * k, k * (1 - c) - sq * s_, k * (1 - c) + sq * s_],
        [k * (1 - c) + sq * s_, c + k * (1 - c), k * (1 - c) - sq * s_],
        [k * (1 - c) - sq * s_, k * (1 - c) + sq * s_, c + k * (1 - c)],
    ], np.float32)


class Post:
    """共通の後処理：ズーム・揺れ・色ずれ・フラッシュ・走査線・周辺減光・粒子感"""

    def __init__(self, W, H, rng):
        self.W, self.H = W, H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        self.vignette = np.clip(1.15 - 0.45 * d ** 2, 0.25, 1)[..., None].astype(np.float32)
        scan = (1 - 0.07 * (np.arange(H) % 3 == 0)).astype(np.float32)
        self.scan = scan[:, None, None]
        self.grain = [(rng.standard_normal((H // 2, W // 2)).astype(np.float32) * 0.018) for _ in range(6)]

    def set_hue_track(self, f: Features, base: float = 0.0):
        steps = [base + v for v in (0, 0, -35, 28, -60)]
        n_drop = np.cumsum(f.drop >= 0.999)
        target = np.array([steps[min(k, len(steps) - 1)] for k in n_drop], np.float32)
        hue = np.zeros_like(target)
        v = 0.0
        for k, tv in enumerate(target):
            v += (tv - v) * 0.03
            hue[k] = v
        self.hue = hue

    def __call__(self, img, i, f: Features, rng):
        W, H = self.W, self.H
        k, b, dr = f.kick[i], f.bass[i], f.drop[i]
        # ズーム（キックで少し寄る）＋揺れ（ドロップで大きく）
        zoom = 1.0 + 0.035 * k + 0.05 * dr + 0.01 * np.sin(i / f.fps * 0.4)
        shake = 6 * k * f.energy[i] + 26 * dr
        dx = shake * (rng.random() - 0.5)
        dy = shake * (rng.random() - 0.5)
        rot = 0.6 * dr * (rng.random() - 0.5)
        M = cv2.getRotationMatrix2D((W / 2, H / 2), rot, zoom)
        M[:, 2] += (dx, dy)
        img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        # 色ずれ（低音とドロップで強く）
        shift = int(2 + 10 * b * k + 22 * dr)
        if shift > 1:
            out = img.copy()
            out[:, shift:, 0] = img[:, :-shift, 0]
            out[:, :-shift, 2] = img[:, shift:, 2]
            img = out
        # フラッシュ
        if dr > 0.05:
            img = img + (dr ** 2) * 0.55
        # ドロップのたびに色味を少し変える（長い曲でも見飽きないように）
        ang = self.hue[min(i, len(self.hue) - 1)]
        if abs(ang) > 0.5:
            img = img @ _hue_matrix(ang).T
        img = img * self.vignette * self.scan
        g = self.grain[i % len(self.grain)]
        img = img + cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
        return np.clip(img, 0, 1)


class Snow:
    """降る雪（手前ほど大きく速い）。盛り上がると少し速く、風で流れる"""

    def __init__(self, W, H, rng, count=420):
        self.W, self.H = W, H
        d = rng.random(count)
        self.x, self.y, self.depth = rng.random(count) * W, rng.random(count) * H, d
        self.size, self.speed, self.ph = 1.2 + d ** 2 * 4.5, 30 + d * 110, rng.random(count) * 6.28

    def draw(self, img, t, prog):
        fall = t + prog * 0.35
        ys = (self.y + self.speed * fall) % (self.H + 20) - 10
        xs = (self.x + 25 * np.sin(t * 0.6 + self.ph) + self.speed * 0.25 * fall) % self.W
        for x, y, sz, d in zip(xs, ys, self.size, self.depth):
            a = 0.5 + 0.5 * d
            cv2.circle(img, (int(x), int(y)), max(1, int(sz)), (a, a, a * 1.05), -1, cv2.LINE_AA)


class Particles:
    """上に舞い上がる光の粒（盛り上がるほど速い）"""

    def __init__(self, W, H, rng, count=140, colors=("#ff3fd6", "#38f9ff", "#ffd166")):
        self.W, self.H = W, H
        self.x = rng.random(count) * W
        self.y0 = rng.random(count) * H
        self.speed = 40 + rng.random(count) * 160
        self.size = 1 + rng.random(count) ** 3 * 4
        self.phase = rng.random(count) * 6.28
        self.col = [tuple(float(v) for v in _hex(colors[int(c)])) for c in rng.integers(0, len(colors), count)]

    def draw(self, layer, t, prog, energy):
        H = self.H
        ys = (self.y0 - self.speed * prog * 1.6) % (H + 40) - 20
        xs = self.x + 24 * np.sin(t * 0.8 + self.phase)
        for x, y, s, c, p in zip(xs, ys, self.size, self.col, self.phase):
            a = (0.35 + 0.65 * energy) * (0.6 + 0.4 * np.sin(t * 3 + p))
            cv2.circle(layer, (int(x), int(y)), max(1, int(s * (0.8 + energy))),
                       tuple(v * a for v in c), -1, cv2.LINE_AA)


def _title_layers(W, H, title, subtitle, y_center, width_frac=0.86):
    """クロム調タイトル文字。(本体RGBA, 光る部分RGB) を返す"""
    size = int(min(W * 0.16, H * 0.1))
    font = _font(FONT_CANDIDATES, size)
    while font.getlength(title) > W * width_frac and size > 20:
        size -= 4
        font = _font(FONT_CANDIDATES, size)
    sub_font = _font(SUB_FONT_CANDIDATES, max(18, int(size * 0.24)))

    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    tw = font.getlength(title)
    bbox = font.getbbox(title)
    th = bbox[3] - bbox[1]
    x0 = (W - tw) / 2
    y0 = y_center - th / 2 - bbox[1]
    d.text((x0, y0), title, font=font, fill=255)
    m = _pil_to_np(mask)

    # クロム：上半分は空色→白、下半分は濃い紫→ピンク
    top, bot = y_center - th / 2, y_center + th / 2
    ys = np.clip((np.arange(H) - top) / max(1, bot - top), 0, 1)
    stops = [(0, "#1d3b8f"), (0.42, "#bfe9ff"), (0.5, "#ffffff"), (0.53, "#3a0a52"), (0.75, "#c2185b"), (1, "#ffd1f0")]
    pos = [p for p, _ in stops]
    cols = np.stack([_hex(c) for _, c in stops])
    g = np.stack([np.interp(ys, pos, cols[:, k]) for k in range(3)], axis=1).astype(np.float32)
    fill = np.repeat(g[:, None, :], W, axis=1)

    # 縁取り（シアン）
    edge = cv2.dilate(m, np.ones((7, 7), np.uint8)) - m
    edge = np.clip(edge, 0, 1)
    cyan = _hex("#38f9ff")
    rgb = fill * m[..., None] + cyan * edge[..., None]
    alpha = np.clip(m + edge, 0, 1)
    glow = (_hex("#ff2bd6") * cv2.dilate(m, np.ones((5, 5), np.uint8))[..., None]).astype(np.float32)

    if subtitle:
        smask = Image.new("L", (W, H), 0)
        sd = ImageDraw.Draw(smask)
        sw = sub_font.getlength(subtitle)
        sd.text(((W - sw) / 2, bot + size * 0.28), subtitle, font=sub_font, fill=255)
        sm = _pil_to_np(smask)
        rgb = rgb * (1 - sm[..., None]) + _hex("#bff8ff") * sm[..., None]
        alpha = np.maximum(alpha, sm)
        glow = glow + _hex("#38f9ff") * sm[..., None] * 0.7
    return rgb.astype(np.float32), alpha[..., None].astype(np.float32), glow


class NeonDriveScene:
    """シンセウェーブの夜道を走る車のイラスト（すべてプログラムで描画）"""

    def __init__(self, W, H, feats: Features, title="NEON DRIVE", subtitle="SYNTHWAVE  ·  ORIGINAL TRACK", seed=7,
                 hue=0.0):
        self.W, self.H, self.f = W, H, feats
        rng = np.random.default_rng(seed)
        self.rng = rng
        portrait = H > W
        self.hy = int(H * (0.55 if portrait else 0.62))  # 地平線
        hy = self.hy

        # --- 空
        sky = _vgrad(hy, W, [(0, "#03010c"), (0.35, "#140533"), (0.7, "#4a0b5e"), (0.92, "#b0186b"), (1, "#ff6a3d")])
        neb = _noise(hy, W, rng, 300)
        neb2 = _noise(hy, W, rng, 200)
        sky += (np.clip(neb - 0.45, 0, 1) * 0.5)[..., None] * _hex("#7b2cff") * (1 - np.linspace(0, 1, hy))[:, None, None]
        sky += (np.clip(neb2 - 0.55, 0, 1) * 0.45)[..., None] * _hex("#1fb6ff") * (1 - np.linspace(0, 1, hy))[:, None, None]
        self.sky = sky.astype(np.float32)
        # 星（3グループで別々にまたたく）
        self.stars = []
        for g in range(3):
            layer = np.zeros((hy, W, 3), np.float32)
            for _ in range(int(W * hy / 9000)):
                x, y = rng.integers(0, W), int(rng.random() ** 1.6 * hy * 0.85)
                r = 1 if rng.random() < 0.9 else 2
                c = (1.0, 0.9 + 0.1 * rng.random(), 1.0) if rng.random() < 0.7 else (0.6, 0.9, 1.0)
                cv2.circle(layer, (int(x), y), r, c, -1, cv2.LINE_AA)
            layer += _blur(layer, 3, 2) * 1.5
            self.stars.append(layer)

        # --- 太陽
        self.sun_r = int(W * (0.36 if portrait else 0.13))
        self.ring_len = 0.55 if portrait else 0.35
        self.sun_cy = hy - int(self.sun_r * 0.32)
        R = self.sun_r
        yy, xx = np.mgrid[-R:R, -R:R].astype(np.float32)
        disc = np.clip(R - np.sqrt(xx ** 2 + yy ** 2) + 0.5, 0, 1)
        t = (yy + R) / (2 * R)
        cols = np.stack([_hex("#fff3a0"), _hex("#ffb13d"), _hex("#ff3d7f"), _hex("#c4148a")])
        pos = [0, 0.35, 0.7, 1]
        sun_rgb = np.stack([np.interp(t, pos, cols[:, k]) for k in range(3)], axis=-1).astype(np.float32)
        self.sun_rgb, self.sun_disc, self.sun_t = sun_rgb, disc, t

        # --- 山（遠い山・近い山）
        self.mountains = []
        for depth, (col_top, col_bot, rim, hgt, rough) in enumerate([
            ("#2a0f4a", "#12061f", "#ff3fd6", 0.22, 0.55),
            ("#170828", "#07020d", "#38f9ff", 0.14, 0.6),
        ]):
            self.mountains.append(self._mountain(rng, col_top, col_bot, rim, hgt, rough, depth))

        # --- 床
        floor_h = H - hy
        self.floor = _vgrad(floor_h, W, [(0, "#2a0640"), (0.25, "#0c0218"), (1, "#020006")])

        # --- 車
        self.car = self._car()

        # --- タイトル
        ty = int(H * (0.14 if portrait else 0.09))
        self.title_rgb, self.title_a, self.title_glow = _title_layers(W, H, title, subtitle, ty)
        self.title_glow_blur = _blur(self.title_glow, 28, 4) + _blur(self.title_glow, 8, 2)

        self.particles = Particles(W, H, rng)
        self.post = Post(W, H, rng)
        self.post.set_hue_track(feats, hue)
        # 円形スペクトラムの角度
        nb = feats.spectrum.shape[1]
        self.ring_angles = np.linspace(np.pi, 1.5 * np.pi, nb)  # 左上の4分の1（右は鏡写し）

    # ------------------------------------------------------------- パーツ
    def _mountain(self, rng, top, bot, rim, hgt, rough, depth):
        W, hy = self.W, self.hy
        n = 257
        pts = np.zeros(n)
        step, amp = n - 1, 1.0
        pts[0], pts[-1] = rng.random() * 0.3, rng.random() * 0.3
        while step > 1:
            half = step // 2
            for i in range(half, n - 1, step):
                pts[i] = (pts[i - half] + pts[i + half]) / 2 + (rng.random() - 0.5) * amp
            amp *= rough
            step = half
        pts -= pts.min()
        pts /= pts.max() + 1e-9
        # 真ん中（太陽の下）は低めにして太陽を見せる
        xs = np.linspace(0, 1, n)
        valley = 1 - 0.75 * np.exp(-((xs - 0.5) ** 2) / 0.02)
        hts = pts * valley * hgt * self.H * (0.6 if self.H > self.W else 0.9)
        hts = np.maximum(hts, 6)
        poly = [(int(x * W), int(hy - h)) for x, h in zip(xs, hts)]
        mh = int(hts.max()) + 4
        top_y = hy - mh
        mask = Image.new("L", (W, mh + 1), 0)
        d = ImageDraw.Draw(mask)
        d.polygon([(x, y - top_y) for x, y in poly] + [(W, mh), (0, mh)], fill=255)
        m = _pil_to_np(mask)
        g = _vgrad(mh + 1, W, [(0, top), (1, bot)])
        # ワイヤーフレームの線
        wire = np.zeros((mh + 1, W, 3), np.float32)
        rc = tuple(float(v) for v in _hex(rim))
        for k in range(0, n - 1, 4):
            x, y = poly[k]
            cv2.line(wire, (x, y - top_y), (int(W / 2 + (x - W / 2) * 1.3), mh), tuple(v * 0.25 for v in rc), 1, cv2.LINE_AA)
        rim_l = np.zeros_like(wire)
        cv2.polylines(rim_l, [np.array([(x, y - top_y) for x, y in poly], np.int32)], False, rc, 2, cv2.LINE_AA)
        rgb = g * m[..., None] + wire * m[..., None]
        return dict(top=top_y, rgb=rgb.astype(np.float32), a=m[..., None], rim=rim_l, depth=depth)

    def _car(self):
        W, H = self.W, self.H
        cw = int(W * (0.5 if H > W else 0.26))
        ch = int(cw * 0.5)
        S = 2  # 2倍で描いて縮小（なめらかに）
        w, h = cw * S, ch * S
        body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(body)
        cx = w / 2

        def P(pts):
            return [(cx + x * w, y * h) for x, y in pts]

        # タイヤ
        d.rounded_rectangle(P([(-0.47, 0.72), (-0.31, 1.0)]), radius=8 * S, fill=(8, 6, 12, 255))
        d.rounded_rectangle(P([(0.31, 0.72), (0.47, 1.0)]), radius=8 * S, fill=(8, 6, 12, 255))
        # ボディ
        d.polygon(P([(-0.5, 0.42), (-0.47, 0.34), (-0.36, 0.3), (0.36, 0.3), (0.47, 0.34), (0.5, 0.42),
                     (0.5, 0.82), (0.46, 0.9), (-0.46, 0.9), (-0.5, 0.82)]), fill=(22, 10, 38, 255))
        # 屋根・リアガラス
        d.polygon(P([(-0.38, 0.31), (-0.27, 0.04), (0.27, 0.04), (0.38, 0.31)]), fill=(14, 6, 26, 255))
        d.polygon(P([(-0.33, 0.29), (-0.25, 0.08), (0.25, 0.08), (0.33, 0.29)]), fill=(40, 22, 80, 255))
        # スポイラー
        d.polygon(P([(-0.49, 0.33), (0.49, 0.33), (0.47, 0.37), (-0.47, 0.37)]), fill=(10, 4, 18, 255))
        # バンパー・ディフューザー
        d.rectangle(P([(-0.46, 0.74), (0.46, 0.9)]), fill=(10, 5, 16, 255))
        for k in range(-3, 4):
            d.rectangle(P([(k * 0.05 - 0.008, 0.8), (k * 0.05 + 0.008, 0.9)]), fill=(26, 14, 40, 255))
        # ナンバープレート
        d.rectangle(P([(-0.1, 0.58), (0.1, 0.68)]), fill=(30, 20, 50, 255))
        body = body.resize((cw, ch), Image.LANCZOS)
        b = _pil_to_np(body)
        rgb, a = b[..., :3], b[..., 3:4]

        # 縁の光（空の色が反射）
        am = (a[..., 0] > 0.5).astype(np.float32)
        top_edge = np.clip(am - np.roll(am, 3, axis=0), 0, 1)
        rim = top_edge[..., None] * _hex("#38f9ff") * 0.9
        side = np.clip(am - np.roll(am, 2, axis=1), 0, 1) + np.clip(am - np.roll(am, -2, axis=1), 0, 1)
        rim += side[..., None] * _hex("#ff3fd6") * 0.6
        # リアガラスの反射
        glass = np.zeros_like(rgb)
        gimg = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(gimg).polygon([(cw / 2 - 0.2 * cw, 0.27 * ch), (cw / 2 - 0.08 * cw, 0.09 * ch),
                                      (cw / 2 - 0.02 * cw, 0.09 * ch), (cw / 2 - 0.12 * cw, 0.27 * ch)], fill=90)
        glass += _pil_to_np(gimg)[..., None] * _hex("#ff7ad9")
        rgb = rgb + rim + glass

        # テールランプ（横一文字のライト）
        lamp = Image.new("L", (cw, ch), 0)
        ld = ImageDraw.Draw(lamp)
        ld.rounded_rectangle([cw * 0.05, ch * 0.45, cw * 0.95, ch * 0.52], radius=int(ch * 0.03), fill=255)
        ld.rectangle([cw * 0.04, ch * 0.45, cw * 0.17, ch * 0.58], fill=255)
        ld.rectangle([cw * 0.83, ch * 0.45, cw * 0.96, ch * 0.58], fill=255)
        lm = _pil_to_np(lamp)[..., None]
        return dict(rgb=rgb.astype(np.float32), a=a, lamp=lm, w=cw, h=ch)

    # ------------------------------------------------------------- 1フレーム
    def render(self, i: int) -> np.ndarray:
        f, W, H, hy = self.f, self.W, self.H, self.hy
        t = i / f.fps
        b, k, e, hi, dr = f.bass[i], f.kick[i], f.energy[i], f.high[i], f.drop[i]
        prog = f.beat_phase[i]
        img = np.zeros((H, W, 3), np.float32)
        neon = np.zeros((H, W, 3), np.float32)  # 光らせる線を描く層

        # 空と星
        sky = self.sky.copy()
        for g, layer in enumerate(self.stars):
            tw = 0.45 + 0.35 * np.sin(t * (1.3 + g * 0.7) + g * 2) + 0.5 * hi
            sky += layer * tw
        img[:hy] = sky

        # 円形スペクトラム（太陽の後ろ）
        spec = f.spectrum[i]
        cx, cy = W // 2, self.sun_cy
        R = self.sun_r * (1.0 + 0.06 * b + 0.04 * k)
        for a_, v in zip(self.ring_angles, spec):
            if True:
                ang = a_
                r0 = R * 1.12
                r1 = r0 + (0.02 + self.ring_len * v ** 1.5) * self.sun_r * (0.6 + 0.6 * e)
                p0 = (int(cx + np.cos(ang) * r0), int(cy + np.sin(ang) * r0))
                p1 = (int(cx + np.cos(ang) * r1), int(cy + np.sin(ang) * r1))
                c = (0.2 + 0.8 * v, 0.95 - 0.5 * v, 1.0)
                cv2.line(neon, p0, p1, c, max(2, int(W / 240)), cv2.LINE_AA)
        # スペクトラムを左右対称に
        neon[:hy, : W // 2] = np.maximum(neon[:hy, : W // 2], neon[:hy, W - W // 2:][:, ::-1])
        neon[:hy, W - W // 2:] = neon[:hy, : W // 2][:, ::-1]

        # 太陽（低音で脈打つ、縞がゆっくり流れる）
        Rs = int(self.sun_r * (1.0 + 0.06 * b + 0.04 * k))
        sun = cv2.resize(self.sun_rgb, (2 * Rs, 2 * Rs))
        disc = cv2.resize(self.sun_disc, (2 * Rs, 2 * Rs))
        tt = np.linspace(0, 1, 2 * Rs)[:, None]
        stripe_phase = (tt * 14 - prog * 0.6) % 1.0
        gap = np.clip((tt - 0.38) * 1.3, 0, 0.6)
        stripes = (stripe_phase > gap).astype(np.float32)
        stripes = cv2.GaussianBlur(stripes, (1, 3), 0)
        alpha = (disc * stripes)[..., None]
        y0, x0 = cy - Rs, cx - Rs
        ys0, ys1 = max(0, y0), min(hy, y0 + 2 * Rs)
        xs0, xs1 = max(0, x0), min(W, x0 + 2 * Rs)
        region = img[ys0:ys1, xs0:xs1]
        sa = alpha[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0]
        bright = 0.95 + 0.12 * b + 0.1 * dr
        region[:] = region * (1 - sa) + sun[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0] * sa * bright
        sun_glow = np.zeros((H, W, 3), np.float32)
        sun_glow[ys0:ys1, xs0:xs1] = sun[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0] * disc[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0, None]

        # 山
        for mt in self.mountains:
            rgb, a, rim = mt["rgb"], mt["a"], mt["rim"]
            y0 = mt["top"]
            reg = img[y0: hy + 1]
            reg[:] = reg * (1 - a) + rgb
            sun_glow[y0: hy + 1] *= 1 - a
            neon[y0: hy + 1] = neon[y0: hy + 1] * (1 - a) + rim * (0.6 + 0.8 * b)

        # 床とグリッド
        floor_h = H - hy
        img[hy:] = self.floor
        grid_c = np.array([1.0, 0.18, 0.85], np.float32) * (0.45 + 0.4 * b + 0.2 * dr)
        cam = floor_h * 0.9
        speed_phase = prog * 2.2
        for zi in range(40):
            z = (zi + 1 - (speed_phase % 1.0))
            y = hy + int(cam / z * 1.0)
            if y >= H or y <= hy:
                continue
            fade = min(1.0, (y - hy) / (floor_h * 0.08))
            th = max(1, int(1 + 3 / z))
            cv2.line(neon, (0, y), (W, y), tuple(float(v * fade) for v in grid_c), th, cv2.LINE_AA)
        nlines = 26
        for xi in range(-nlines, nlines + 1):
            x_bottom = W / 2 + xi * W / 10
            cv2.line(neon, (W // 2 + int(xi * W / 160), hy), (int(x_bottom), H), tuple(float(v) for v in grid_c), 2, cv2.LINE_AA)
        # 地平線の光
        cv2.line(neon, (0, hy), (W, hy), (1.0, 0.5, 0.9), 3, cv2.LINE_AA)
        neon[hy:] *= np.linspace(0.5, 1, floor_h)[:, None, None]

        # 光の粒
        self.particles.draw(neon, t, prog, e)

        # 光のにじみ（ブルーム）
        img += neon
        glow_src = neon + sun_glow * (0.35 + 0.35 * b)
        img += _blur(glow_src, 18, 4) * (0.8 + 0.4 * b) + _blur(glow_src, 70, 8) * (0.35 + 0.45 * e)

        # 車（ベースで少し弾む）
        car = self.car
        bounce = int(-6 * k * e - 2 * np.sin(t * 9) * e)
        cxl = W // 2 - car["w"] // 2 + int(10 * np.sin(t * 0.7))
        cyl = int(H * (0.8 if H > W else 0.74)) - car["h"] // 2 + bounce
        # 車の下の影と光
        cv2.ellipse(img, (cxl + car["w"] // 2, cyl + car["h"] - 4), (int(car["w"] * 0.55), int(car["h"] * 0.12)), 0, 0, 360, (0, 0, 0), -1, cv2.LINE_AA)
        reg = img[cyl: cyl + car["h"], cxl: cxl + car["w"]]
        reg[:] = reg * (1 - car["a"]) + car["rgb"] * car["a"]
        lamp_c = np.array([1.0, 0.08, 0.25], np.float32) * (0.8 + 0.7 * k + 0.4 * b)
        reg += car["lamp"] * lamp_c
        lamp_full = np.zeros((H, W, 3), np.float32)
        lamp_full[cyl: cyl + car["h"], cxl: cxl + car["w"]] = car["lamp"] * lamp_c
        # 路面に映るテールランプ
        refl_h = int(car["h"] * 0.6)
        ry = cyl + car["h"]
        if ry + refl_h < H:
            refl = car["lamp"][::-1][: refl_h] * lamp_c * np.linspace(0.5, 0, refl_h)[:, None, None]
            lamp_full[ry: ry + refl_h, cxl: cxl + car["w"]] += refl[: H - ry]

        img += _blur(lamp_full, 14, 2) * 1.2 + _blur(lamp_full, 50, 8) * 1.0

        # タイトル
        pulse = 0.7 + 0.5 * k + 0.6 * dr
        img = img * (1 - self.title_a) + self.title_rgb * self.title_a
        img += self.title_glow_blur * pulse

        return self.post(img, i, f, self.rng)


class ImageScene:
    """手持ちのイラスト（AI で描いた絵など）を音に合わせて動かす"""

    def __init__(self, W, H, feats: Features, image: Path, title="", subtitle="", seed=7, hue=0.0):
        self.W, self.H, self.f = W, H, feats
        self.rng = np.random.default_rng(seed)
        src = Image.open(image).convert("RGB")
        # 少し大きめに切り抜いて、ゆっくり動かす余白を作る
        scale = max(W / src.width, H / src.height) * 1.12
        src = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
        self.src = _pil_to_np(src)
        lum = self.src.mean(axis=2)
        self.bright = (self.src * np.clip((lum - 0.6) / 0.4, 0, 1)[..., None]).astype(np.float32)
        self.particles = Particles(W, H, self.rng)
        self.post = Post(W, H, self.rng)
        self.post.set_hue_track(feats, hue)
        self.bars = feats.spectrum.shape[1]
        if title:
            self.title_rgb, self.title_a, g = _title_layers(W, H, title, subtitle, int(H * 0.12))
            self.title_glow_blur = _blur(g, 28, 4) + _blur(g, 8, 2)
        else:
            self.title_a = None

    def render(self, i: int) -> np.ndarray:
        f, W, H = self.f, self.W, self.H
        t = i / f.fps
        b, k, e = f.bass[i], f.kick[i], f.energy[i]
        sh, sw = self.src.shape[:2]
        # ゆっくりパン（ケン・バーンズ）
        px = (sw - W) * (0.5 + 0.45 * np.sin(t * 0.11))
        py = (sh - H) * (0.5 + 0.45 * np.cos(t * 0.083))
        x0, y0 = int(px), int(py)
        img = self.src[y0: y0 + H, x0: x0 + W].copy()
        br = self.bright[y0: y0 + H, x0: x0 + W]
        img = img * (0.82 + 0.25 * e) + _blur(br, 30, 4) * (0.4 + 1.6 * b)

        neon = np.zeros((H, W, 3), np.float32)
        # 下のスペクトラムバー（左右対称）
        spec = f.spectrum[i]
        n = self.bars
        bw = W / (2 * n + 2)
        base = int(H * 0.93)
        for j, v in enumerate(spec):
            hgt = (0.006 + 0.11 * v ** 2) * H * (0.6 + 0.6 * e)
            c = (0.7 * v, 0.75 - 0.45 * v, 0.85)
            for x in (W / 2 + (j + 0.5) * bw, W / 2 - (j + 0.5) * bw):
                cv2.rectangle(neon, (int(x - bw * 0.35), int(base - hgt)), (int(x + bw * 0.35), base), c, -1)
        self.particles.draw(neon, t, f.beat_phase[i], e)
        img += neon + _blur(neon, 20, 4) * 0.7
        if self.title_a is not None:
            img = img * (1 - self.title_a) + self.title_rgb * self.title_a
            img += self.title_glow_blur * (0.6 + 0.5 * k + 0.6 * f.drop[i])
        return self.post(img, i, f, self.rng)
