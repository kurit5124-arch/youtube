"""オーロラの雪山と湖（すべてプログラムで描画）。

  - オーロラのカーテンが音域ごとの強さ（スペクトラム）で光り、低音で明るく、盛り上がると速く揺れる
  - 雪をかぶった山（2層）、針葉樹の森のシルエット、湖に映るオーロラ
  - 星のまたたき、流れ星、ドロップで光の帯がはじける
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .analyze import Features
from .scene import Particles, Post, Snow, _blur, _hex, _noise, _pil_to_np, _title_layers, _vgrad


class AuroraScene:
    def __init__(self, W, H, feats: Features, title="", subtitle="", seed=7, hue=0.0, snow=False, **_):
        self.W, self.H, self.f = W, H, feats
        rng = np.random.default_rng(seed)
        self.rng = rng
        portrait = H > W
        self.hy = int(H * (0.68 if portrait else 0.72))
        hy = self.hy
        self.sky = _vgrad(hy, W, [(0, "#02040f"), (0.45, "#061633"), (0.8, "#0c3550"), (1, "#1c5a6a")])
        self.stars = []
        for g in range(3):
            layer = np.zeros((hy, W, 3), np.float32)
            for _ in range(int(W * hy / 7000)):
                x, y = int(rng.integers(0, W)), int(rng.random() ** 1.5 * hy * 0.9)
                cv2.circle(layer, (x, y), 1 if rng.random() < 0.93 else 2, (0.9, 0.95, 1.0), -1, cv2.LINE_AA)
            self.stars.append(layer + _blur(layer, 3, 2))

        # オーロラは 1/4 の解像度で計算
        self.aw, self.ah = W // 4, hy // 4
        self.curtains = []
        for k in range(3):
            self.curtains.append(dict(
                base=rng.uniform(0.25, 0.55), amp=rng.uniform(0.05, 0.12), freq=rng.uniform(1.2, 2.6),
                speed=rng.uniform(0.08, 0.2) * (1 if k % 2 else -1), ph=rng.uniform(0, 6.28),
                height=rng.uniform(0.25, 0.45), rays=rng.random(self.aw) * 6.28))
        self.ax = np.linspace(0, 1, self.aw)[None, :]
        self.ay = np.linspace(0, 1, self.ah)[:, None]

        # 山と森
        self.mountains = [self._mountain(rng, d) for d in (0, 1)]
        self.forest = self._forest(rng)

        # 流れ星
        self.meteors = []
        for i in range(0, feats.n, int(feats.fps * 2)):
            if rng.random() < 0.35:
                self.meteors.append((i + int(rng.integers(0, feats.fps)), rng.uniform(0.1, 0.9) * W,
                                     rng.uniform(0.05, 0.3) * hy, rng.choice([-1, 1])))

        ty = int(H * (0.12 if portrait else 0.11))
        self.title_rgb, self.title_a, g = _title_layers(W, H, title or " ", subtitle, ty,
                                                        width_frac=0.7 if not portrait else 0.86)
        self.title_glow = _blur(g, 26, 4) + _blur(g, 8, 2)
        self.particles = Particles(W, H, rng, count=90, colors=("#b8fff0", "#d8c8ff", "#ffffff"))
        self.snow = Snow(W, H, rng) if snow else None
        self.post = Post(W, H, rng)
        self.post.set_hue_track(feats, hue)

    def _mountain(self, rng, depth):
        W, hy = self.W, self.hy
        n = 129
        pts = np.zeros(n)
        step, amp = n - 1, 1.0
        while step > 1:
            half = step // 2
            for i in range(half, n - 1, step):
                pts[i] = (pts[i - half] + pts[i + half]) / 2 + (rng.random() - 0.5) * amp
            amp *= 0.62
            step = half
        pts = (pts - pts.min()) / (np.ptp(pts) + 1e-9)
        hmax = hy * (0.42 if depth == 0 else 0.24)
        ys = hy - (0.15 + 0.85 * pts ** 1.4) * hmax
        xs = np.linspace(0, W, n)
        top = int(ys.min()) - 2
        h = hy - top + 1
        mask = Image.new("L", (W, h), 0)
        ImageDraw.Draw(mask).polygon([(x, y - top) for x, y in zip(xs, ys)] + [(W, h), (0, h)], fill=255)
        m = _pil_to_np(mask)
        body = _vgrad(h, W, [(0, "#1b2f4a" if depth == 0 else "#0e1a2c"), (1, "#060b14")])
        # 雪：尾根から少し下まで白っぽく
        ridge = np.interp(np.arange(W), xs, ys - top)
        yy = np.arange(h)[:, None]
        snowband = np.clip(1 - (yy - ridge[None, :]) / (h * (0.22 if depth == 0 else 0.12)), 0, 1) ** 1.5
        noise = _noise(h, W, rng, 40)
        snow = np.clip(snowband * (0.5 + 0.9 * noise) - 0.3, 0, 1)
        col = body * (1 - snow[..., None]) + _hex("#cfe6ff" if depth == 0 else "#9fb8d8") * snow[..., None] * 0.85
        return dict(top=top, rgb=(col * m[..., None]).astype(np.float32), a=m[..., None].astype(np.float32))

    def _forest(self, rng):
        W, hy = self.W, self.hy
        h = int(hy * 0.16)
        img = Image.new("L", (W, h), 0)
        d = ImageDraw.Draw(img)
        x = -10
        while x < W + 10:
            th = rng.uniform(0.35, 1.0) * h
            tw = th * rng.uniform(0.28, 0.4)
            for k in range(4):  # 段になった針葉樹
                y0 = h - th + k * th * 0.2
                w = tw * (0.4 + 0.2 * k)
                d.polygon([(x, y0), (x - w, y0 + th * 0.35), (x + w, y0 + th * 0.35)], fill=255)
            d.rectangle([x - 2, h - th * 0.15, x + 2, h], fill=255)
            x += tw * rng.uniform(0.6, 1.2)
        m = _pil_to_np(img)
        return dict(top=hy - h, a=m[..., None].astype(np.float32))

    def _aurora(self, t, spec, e, b, dr):
        out = np.zeros((self.ah, self.aw, 3), np.float32)
        nb = len(spec)
        band = np.interp(np.linspace(0, nb - 1, self.aw), np.arange(nb), spec)[None, :]
        band = 0.5 * (band + band[:, ::-1])  # 左右対称に
        for k, c in enumerate(self.curtains):
            sp = c["speed"] * (1 + 2.5 * e)
            curve = (c["base"] + c["amp"] * np.sin(2 * np.pi * c["freq"] * self.ax + c["ph"] + t * sp * 6)
                     + 0.03 * np.sin(2 * np.pi * 5 * self.ax - t * 0.7))
            below = self.ay - curve
            body = np.where(below < 0, np.exp(-(below / (c["height"] * (0.6 + 0.6 * b))) ** 2),
                            np.exp(-(below / 0.025) ** 2))
            rays = 0.55 + 0.45 * np.sin(c["rays"][None, :] * 7 + t * (1.5 + 3 * e))
            inten = body * rays * (0.25 + 1.1 * band) * (0.45 + 0.7 * b + 0.6 * dr)
            # 色：下が緑、上がシアン〜紫
            up = np.clip(-below / (c["height"] + 1e-6), 0, 1)
            col = (np.array([0.2, 1.0, 0.6], np.float32) * (1 - up[..., None])
                   + np.array([0.6, 0.35, 1.0], np.float32) * up[..., None])
            out += inten[..., None] * col * (0.8 if k else 1.0)
        return out

    def render(self, i: int) -> np.ndarray:
        f, W, H, hy = self.f, self.W, self.H, self.hy
        t = i / f.fps
        b, k, e, hi, dr = f.bass[i], f.kick[i], f.energy[i], f.high[i], f.drop[i]
        img = np.zeros((H, W, 3), np.float32)
        glow = np.zeros((H, W, 3), np.float32)
        sky = self.sky.copy()
        for g, layer in enumerate(self.stars):
            sky += layer * (0.4 + 0.3 * np.sin(t * (1.0 + g * 0.7) + g) + 0.4 * hi)
        img[:hy] = sky

        au = self._aurora(t, f.spectrum[i], e, b, dr)
        au = cv2.resize(au, (W, hy), interpolation=cv2.INTER_LINEAR)
        au = cv2.GaussianBlur(au, (0, 0), 3)
        img[:hy] += au
        glow[:hy] += au * 0.6

        for (fr, x0, y0, s) in self.meteors:
            age = (i - fr) / f.fps
            if 0 <= age < 0.8:
                a = 1 - age / 0.8
                p0 = (int(x0 + s * 650 * age), int(y0 + 230 * age))
                p1 = (int(x0 + s * 650 * (age - 0.1)), int(y0 + 230 * (age - 0.1)))
                cv2.line(glow, p1, p0, (a, a, a), 2, cv2.LINE_AA)

        for mt in self.mountains:
            top = mt["top"]
            reg = img[top:hy + 1]
            reg[:] = reg * (1 - mt["a"]) + mt["rgb"] * (0.85 + 0.25 * b)
            glow[top:hy + 1] *= 1 - mt["a"]
        fo = self.forest
        reg = img[fo["top"]:hy]
        reg[:] = reg * (1 - fo["a"][: hy - fo["top"]]) + np.array([0.01, 0.02, 0.04], np.float32) * fo["a"][: hy - fo["top"]]
        glow[fo["top"]:hy] *= 1 - fo["a"][: hy - fo["top"]]

        self.particles.draw(glow, t, f.beat_phase[i], e)

        # 湖面
        rh = H - hy
        src = img[max(0, hy - rh):hy][::-1]
        src = cv2.resize(src, (W, rh)) if src.shape[0] != rh else src
        yy = np.arange(rh, dtype=np.float32)
        amp = 1.0 + 4 * yy / rh + 2 * b
        mx = (np.arange(W, dtype=np.float32)[None, :] + amp[:, None] * np.sin(yy[:, None] * 0.3 - t * 2)).astype(np.float32)
        my = np.repeat(yy[:, None], W, 1).astype(np.float32)
        refl = cv2.blur(cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT), (11, 1))
        water = _vgrad(rh, W, [(0, "#0b2233"), (1, "#02060c")])
        img[hy:] = water + refl * np.linspace(0.6, 0.15, rh)[:, None, None]

        img += _blur(glow, 16, 4) * (0.7 + 0.4 * b) + _blur(glow, 60, 8) * (0.4 + 0.5 * e)
        if self.snow is not None:
            self.snow.draw(img, t, f.beat_phase[i])
        img = img * (1 - self.title_a) + self.title_rgb * self.title_a
        img += self.title_glow * (0.5 + 0.4 * k + 0.5 * dr)
        return self.post(img, i, f, self.rng)
