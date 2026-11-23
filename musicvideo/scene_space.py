"""宇宙（すべてプログラムで描画）。

  - 星雲と3層の星（奥ほどゆっくり流れる）
  - 輪のある大きな惑星（表面の模様がゆっくり回る、低音で輪が光る）と、まわりを回る小さな月
  - 惑星のまわりの円形スペクトラム
  - ドロップで星が放射状に伸びる「ワープ」、彗星
"""
from __future__ import annotations

import cv2
import numpy as np

from .analyze import Features
from .scene import Particles, Post, _blur, _hex, _noise, _title_layers

PALETTES = [  # (星雲1, 星雲2, 惑星の明るい色, 惑星の暗い色, 輪)
    ("#5b2bd6", "#ff4fa8", "#ffd2a1", "#7a3b6b", "#ffe6c7"),
    ("#1f7ad6", "#30e3c0", "#bfe8ff", "#24427a", "#d8f4ff"),
    ("#d6512b", "#ffb14f", "#ffe0a8", "#8a3a22", "#fff0d0"),
]


class SpaceScene:
    def __init__(self, W, H, feats: Features, title="", subtitle="", seed=7, hue=0.0, **_):
        self.W, self.H, self.f = W, H, feats
        rng = np.random.default_rng(seed)
        self.rng = rng
        portrait = H > W
        pal = PALETTES[int(rng.integers(len(PALETTES)))]
        n1, n2 = _noise(H, W, rng, 380), _noise(H, W, rng, 220)
        bg = np.zeros((H, W, 3), np.float32) + _hex("#03020a")
        bg += (np.clip(n1 - 0.45, 0, 1) ** 1.5 * 1.4)[..., None] * _hex(pal[0])
        bg += (np.clip(n2 - 0.55, 0, 1) ** 1.5 * 1.6)[..., None] * _hex(pal[1])
        self.bg = bg.astype(np.float32)
        # 星（3層、奥ほど遅い）：位置を持っておき、ワープのときは放射状に伸ばす
        self.stars = []
        for d in range(3):
            n = int(W * H / (9000 - 2500 * d))
            st = dict(x=rng.random(n) * W, y=rng.random(n) * H, b=rng.uniform(0.4, 1.0, n),
                      speed=(6, 16, 40)[d], size=(1, 1, 2)[d])
            layer = np.zeros((H, W, 3), np.float32)  # 先に描いておき、横にずらして使う（速い）
            for xi, yi, bb in zip(st["x"], st["y"], st["b"]):
                cv2.circle(layer, (int(xi), int(yi)), st["size"], (bb, bb, bb), -1, cv2.LINE_AA)
            st["layer"] = layer
            self.stars.append(st)
        # 惑星
        self.pr = int(min(W, H) * (0.26 if portrait else 0.3))
        self.pc = (int(W * (0.5 if portrait else rng.uniform(0.3, 0.42))), int(H * (0.55 if portrait else 0.6)))
        R = self.pr
        tex = _noise(2 * R, 8 * R, rng, R / 3)
        bands = 0.5 + 0.5 * np.sin(np.linspace(0, 1, 2 * R)[:, None] * 18 + tex * 4)
        self.tex = bands.astype(np.float32)  # 横に長い模様（回転させる）
        yy, xx = np.mgrid[-R:R, -R:R].astype(np.float32)
        d = np.sqrt(xx ** 2 + yy ** 2) / R
        self.disc = np.clip((1 - d) * R + 0.5, 0, 1)
        light = np.clip(0.25 + 0.9 * (-(xx * 0.6 + yy * 0.5) / R + 0.4), 0, 1.2)  # 左上から光
        self.light = (light * self.disc).astype(np.float32)
        # 球に見えるよう、模様の横位置を球面に合わせて縮める
        self.u = (np.arcsin(np.clip(xx / R / np.sqrt(np.clip(1 - (yy / R) ** 2, 1e-4, 1)), -1, 1)) / np.pi + 0.5)
        self.v = ((yy + R) / (2 * R)).astype(np.float32)
        self.col_hi, self.col_lo, self.col_ring = _hex(pal[2]), _hex(pal[3]), _hex(pal[4])
        self.tilt = rng.uniform(-0.35, -0.15)
        nb = feats.spectrum.shape[1]
        self.ring_angles = np.linspace(-np.pi / 2, np.pi / 2, nb)
        self.comets = [i for i in np.where(feats.drop >= 0.999)[0]]

        ty = int(H * (0.12 if portrait else 0.11))
        self.title_rgb, self.title_a, g = _title_layers(W, H, title or " ", subtitle, ty,
                                                        width_frac=0.7 if not portrait else 0.86)
        self.title_glow = _blur(g, 26, 4) + _blur(g, 8, 2)
        self.particles = Particles(W, H, rng, count=80, colors=(pal[1], pal[4], "#ffffff"))
        self.post = Post(W, H, rng)
        self.post.set_hue_track(feats, hue)

    def _ring(self, layer, cx, cy, R, front, color, width):
        """惑星の輪（楕円）。front=True なら手前半分だけ"""
        for k in range(6):
            rr = R * (1.45 + 0.09 * k)
            axes = (int(rr), int(rr * 0.22))
            ang = np.degrees(self.tilt)
            a0, a1 = (0, 180) if front else (180, 360)
            c = tuple(float(v) * (0.55 + 0.1 * (k % 3)) for v in color)
            cv2.ellipse(layer, (cx, cy), axes, ang, a0, a1, c, width, cv2.LINE_AA)

    def render(self, i: int) -> np.ndarray:
        f, W, H = self.f, self.W, self.H
        t = i / f.fps
        b, k, e, hi, dr = f.bass[i], f.kick[i], f.energy[i], f.high[i], f.drop[i]
        prog = f.beat_phase[i]
        img = self.bg * (0.85 + 0.2 * b)
        img = img.copy()
        glow = np.zeros((H, W, 3), np.float32)

        # 星（ワープ：盛り上がりとドロップで放射状に伸びる）
        cx, cy = W / 2, H / 2
        warp = dr  # ドロップの瞬間だけ
        for d_, s in enumerate(self.stars):
            off = int(s["speed"] * prog * 3) % W
            img += np.roll(s["layer"], -off, axis=1) * (0.75 + 0.25 * np.sin(t * (1.5 + d_)) + 0.3 * hi)
            if warp > 0.08 and d_ == 2:
                x = (s["x"] - off) % W
                L = warp * 0.14
                for xi, yi, bb in zip(x, s["y"], s["b"]):
                    c = bb * 0.6
                    cv2.line(glow, (int(xi), int(yi)), (int(xi + (xi - cx) * L), int(yi + (yi - cy) * L)),
                             (c, c, c), 1, cv2.LINE_AA)

        # 惑星
        R0 = self.pr
        R = int(R0 * (1 + 0.03 * b))
        pcx, pcy = self.pc
        self._ring(glow, pcx, pcy, R, False, self.col_ring * (0.6 + 0.8 * b), 3)
        # スペクトラム（惑星のまわり）
        spec = f.spectrum[i]
        for a_, v in zip(self.ring_angles, spec):
            for sgn in (1, -1):
                ang = a_ if sgn == 1 else np.pi - a_
                r0 = R * 1.08
                r1 = r0 + (0.02 + 0.45 * v ** 1.6) * R * (0.6 + 0.6 * e)
                c = tuple(float(x) for x in (self.col_ring * (0.5 + 0.5 * v)))
                cv2.line(glow, (int(pcx + np.cos(ang) * r0), int(pcy + np.sin(ang) * r0)),
                         (int(pcx + np.cos(ang) * r1), int(pcy + np.sin(ang) * r1)), c, 2, cv2.LINE_AA)
        # 表面
        off = (t * 0.02 + prog * 0.004) % 1.0
        uu = ((self.u * 0.5 + off) % 1.0) * (self.tex.shape[1] - 1)
        vv = self.v * (self.tex.shape[0] - 1)
        surf = cv2.remap(self.tex, uu.astype(np.float32), vv.astype(np.float32), cv2.INTER_LINEAR)
        col = self.col_lo + (self.col_hi - self.col_lo) * surf[..., None]
        planet = col * self.light[..., None]
        planet = cv2.resize(planet, (2 * R, 2 * R))
        disc = cv2.resize(self.disc, (2 * R, 2 * R))[..., None]
        y0, x0 = pcy - R, pcx - R
        ys0, ys1, xs0, xs1 = max(0, y0), min(H, y0 + 2 * R), max(0, x0), min(W, x0 + 2 * R)
        reg = img[ys0:ys1, xs0:xs1]
        pa = disc[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
        reg[:] = reg * (1 - pa) + planet[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0] * pa
        glow[ys0:ys1, xs0:xs1] *= 1 - pa  # 惑星の後ろのものは隠す
        # 大気の縁の光
        rim = np.zeros((H, W, 3), np.float32)
        cv2.circle(rim, (pcx, pcy), R, tuple(float(v) for v in self.col_ring), 3, cv2.LINE_AA)
        glow += rim * (0.5 + 0.6 * b)
        self._ring(glow, pcx, pcy, R, True, self.col_ring * (0.6 + 0.8 * b), 3)
        # まわりを回る小さな月
        ang = t * 0.25
        mx, my = pcx + np.cos(ang) * R * 2.1, pcy + np.sin(ang) * R * 0.5
        cv2.circle(img, (int(mx), int(my)), max(4, R // 12), (0.85, 0.85, 0.9), -1, cv2.LINE_AA)

        # 彗星（ドロップで横切る）
        for c0 in self.comets:
            age = (i - c0) / f.fps
            if 0 <= age < 2.5:
                x = W * (1.1 - age / 2.2)
                y = H * (0.15 + 0.1 * age)
                for kk in range(30):
                    a = (1 - kk / 30) * (1 - age / 2.5)
                    cv2.circle(glow, (int(x + kk * 14), int(y - kk * 2)), max(1, 6 - kk // 6), (a, a * 0.95, a), -1, cv2.LINE_AA)

        self.particles.draw(glow, t, prog, e)
        img += glow * 0.8 + _blur(glow, 14, 4) * (0.8 + 0.4 * b) + _blur(glow, 60, 8) * (0.4 + 0.5 * e)
        img = img * (1 - self.title_a) + self.title_rgb * self.title_a
        img += self.title_glow * (0.5 + 0.4 * k + 0.5 * dr)
        return self.post(img, i, f, self.rng)
