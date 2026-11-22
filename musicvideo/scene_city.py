"""夜空と海辺の街のイラスト（すべてプログラムで描画）を、音に合わせて動かす。

  - パステルの夕焼け〜夜空、流れる雲（奥と手前で速さが違う）、またたく星
  - 大きな月とまわりの円形スペクトラム（低音で脈打つ）
  - ビルのシルエット：窓の明かりがキックに合わせて点滅、屋上の赤いランプ
  - 水面に街と空が映り、ゆらゆら揺れる
  - ドロップで花火が一斉に上がり、盛り上がっている間はビートに合わせて上がる
  - 静かなところでは流れ星
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .analyze import Features
from .scene import Particles, Post, _blur, _hex, _noise, _pil_to_np, _title_layers, _vgrad

PASTEL = ["#ff8fd8", "#8fe9ff", "#fff08f", "#b48fff", "#8fffc1", "#ffb28f"]


class SkyCityScene:
    def __init__(self, W, H, feats: Features, title="AFTERGLOW", subtitle="", seed=7, hue=0.0):
        self.W, self.H, self.f = W, H, feats
        rng = np.random.default_rng(seed)
        self.rng = rng
        portrait = H > W
        self.hy = int(H * (0.70 if portrait else 0.74))  # 水平線（街の足もと）
        hy = self.hy

        # --- 空
        sky = _vgrad(hy, W, [(0, "#0d0826"), (0.3, "#24124f"), (0.58, "#5b2a86"), (0.8, "#c2569b"),
                             (0.93, "#ff9c8a"), (1, "#ffd0a0")])
        neb = _noise(hy, W, rng, 260)
        fade = (1 - np.linspace(0, 1, hy))[:, None, None]
        sky += (np.clip(neb - 0.5, 0, 1) * 0.35)[..., None] * _hex("#6b5bff") * fade
        self.sky = sky.astype(np.float32)
        self.stars = []
        for g in range(3):
            layer = np.zeros((hy, W, 3), np.float32)
            for _ in range(int(W * hy / 8000)):
                x, y = int(rng.integers(0, W)), int(rng.random() ** 1.8 * hy * 0.75)
                c = (1.0, 0.95, 1.0) if rng.random() < 0.7 else (0.75, 0.9, 1.0)
                cv2.circle(layer, (x, y), 1 if rng.random() < 0.92 else 2, c, -1, cv2.LINE_AA)
            self.stars.append(layer + _blur(layer, 3, 2) * 1.2)

        # --- 月
        self.moon_r = int(min(W, H) * (0.12 if portrait else 0.13))
        self.moon_c = (int(W * (0.5 if portrait else 0.78)), int(hy * (0.36 if portrait else 0.46)))
        R = self.moon_r
        yy, xx = np.mgrid[-R:R, -R:R].astype(np.float32)
        d = np.sqrt(xx ** 2 + yy ** 2)
        disc = np.clip(R - d + 0.5, 0, 1)
        crater = _noise(2 * R, 2 * R, rng, R / 2.5)
        shade = 0.9 + 0.1 * (crater - 0.5) * 2 - 0.12 * (d / R) ** 3
        moon = np.stack([shade * 0.98, shade * 0.86, shade * 0.95], -1).astype(np.float32) * 0.92
        self.moon_rgb, self.moon_a = moon, disc[..., None]
        nb = feats.spectrum.shape[1]
        self.ring_angles = np.linspace(-np.pi / 2, np.pi / 2, nb)  # 右半分（左は鏡写し）

        # --- 雲（3層。横に長く作ってスクロール）
        self.clouds = []
        for k, (yc, hgt, thr, light, dark, alpha, speed) in enumerate([
            (0.40, 0.42, 0.50, "#ffc2e0", "#5a3285", 0.6, 4),
            (0.62, 0.40, 0.52, "#ffd6c2", "#6e3a88", 0.8, 9),
            (0.84, 0.30, 0.55, "#ffe2c8", "#874783", 0.9, 16),
        ]):
            ch = int(hy * hgt)
            cw = W * 2
            n = _noise(ch, cw, rng, 180 + 60 * k)
            # 横につながるように端をなじませる
            n = 0.5 * (n + n[:, ::-1])
            band = np.exp(-((np.linspace(-1, 1, ch)) ** 2) / 0.45)[:, None]
            m = np.clip((n * band - thr * 0.6) / 0.18, 0, 1)
            m = cv2.GaussianBlur(m, (0, 0), 3)
            lit = np.clip(m - np.roll(cv2.GaussianBlur(m, (0, 0), 10), 14, axis=0) * 0.9, 0, 1)
            rgb = _hex(dark) * m[..., None] + (_hex(light) - _hex(dark)) * (lit ** 0.7)[..., None]
            self.clouds.append(dict(y=int(hy * yc - ch / 2), rgb=rgb.astype(np.float32),
                                    a=(m * alpha)[..., None].astype(np.float32), speed=speed))

        # --- 街
        self.city = [self._city(rng, depth) for depth in (0, 1)]

        # --- 花火の予定表（ドロップ＋盛り上がっている間のキック）
        self.fireworks = self._schedule(rng)
        # --- 流れ星
        self.meteors = []
        for i in range(0, feats.n, int(feats.fps * 2.5)):
            if feats.energy[i] < 0.45 and rng.random() < 0.55:
                self.meteors.append((i + int(rng.integers(0, feats.fps)), rng.uniform(0.15, 0.85) * W,
                                     rng.uniform(0.05, 0.35) * hy, rng.uniform(0.6, 1.0)))

        ty = int(H * (0.12 if portrait else 0.11))
        self.title_rgb, self.title_a, g = _title_layers(W, H, title, subtitle, ty, width_frac=0.7 if not portrait else 0.86)
        self.title_glow = _blur(g, 26, 4) + _blur(g, 8, 2)
        self.particles = Particles(W, H, rng, count=110, colors=("#ffd1f0", "#c7f3ff", "#fff3b0"))
        self.post = Post(W, H, rng)
        self.post.set_hue_track(feats, hue)

    # ------------------------------------------------------------- パーツ
    def _city(self, rng, depth):
        W, hy = self.W, self.hy
        maxh = int(hy * (0.26 if depth == 0 else 0.2))
        img = Image.new("RGBA", (W, maxh + 1), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        win_layers = [Image.new("RGB", (W, maxh + 1)) for _ in range(3)]
        wds = [ImageDraw.Draw(w) for w in win_layers]
        body = (58, 36, 104) if depth == 0 else (22, 14, 46)
        lamps = []
        x = -20
        while x < W:
            bw = int(rng.integers(40, 120) if depth == 0 else rng.integers(55, 150))
            bh = int(maxh * rng.uniform(0.3, 1.0) ** (1.2 if depth == 0 else 1.6))
            if abs(x + bw / 2 - self.moon_c[0]) < self.moon_r * 0.8 and depth == 1:
                bh = int(bh * 0.6)
            top = maxh - bh
            d.rectangle([x, top, x + bw, maxh], fill=body + (255,))
            if rng.random() < 0.35:  # 段になった屋上
                sw = int(bw * rng.uniform(0.3, 0.6))
                sx = x + (bw - sw) // 2
                sh = int(rng.integers(10, 40))
                d.rectangle([sx, top - sh, sx + sw, top], fill=body + (255,))
                top -= sh
            if rng.random() < 0.3:  # アンテナ
                ax = x + bw // 2
                ah = int(rng.integers(15, 45))
                d.line([ax, top, ax, top - ah], fill=body + (255,), width=3)
                lamps.append((ax, top - ah))
            # 窓
            if depth == 1 or rng.random() < 0.6:
                ws = 9 if depth == 1 else 7
                for wy in range(maxh - bh + 10, maxh - 6, ws + 6):
                    for wx in range(x + 6, x + bw - 6, ws + 4):
                        if rng.random() < (0.32 if depth == 1 else 0.22):
                            col = PASTEL[int(rng.integers(0, len(PASTEL)))] if rng.random() < 0.25 else "#ffe9b0"
                            c = tuple(int(v * 255) for v in _hex(col))
                            wds[int(rng.integers(0, 3))].rectangle([wx, wy, wx + ws - 3, wy + ws], fill=c)
            x += bw + int(rng.integers(0, 12))
        arr = _pil_to_np(img)
        wins = [(_pil_to_np(w) * arr[..., 3:4]).astype(np.float32) for w in win_layers]
        return dict(top=hy - maxh, rgb=arr[..., :3].copy(), a=arr[..., 3:4].copy(), wins=wins, lamps=lamps,
                    glow=[_blur(w, 8, 2) for w in wins])

    def _schedule(self, rng):
        f = self.f
        W, hy = self.W, self.hy
        shows = []
        hits = np.where(f.drop >= 0.999)[0]
        for h in hits:  # ドロップの瞬間に一斉に
            for k in range(5):
                shows.append(self._firework(rng, h + k * 3, W * (0.15 + 0.7 * k / 4) + rng.normal(0, 40)))
        last = -100
        count = 0
        for i in range(1, f.n):
            if f.kick[i] > 0.9 and f.kick[i - 1] < 0.9 and f.energy[i] > 0.6:
                count += 1
                if count % 3 == 0 and i - last > f.fps * 0.8:
                    shows.append(self._firework(rng, i, rng.uniform(0.1, 0.9) * W))
                    last = i
        return shows

    def _firework(self, rng, frame, x):
        hy = self.hy
        n = int(rng.integers(60, 110))
        ang = rng.uniform(0, 2 * np.pi, n)
        sp = rng.uniform(0.55, 1.0, n) * rng.uniform(380, 560)
        col = _hex(PASTEL[int(rng.integers(0, len(PASTEL)))])
        col2 = _hex(PASTEL[int(rng.integers(0, len(PASTEL)))])
        cols = np.where((rng.random(n) < 0.7)[:, None], col, col2)
        return dict(frame=frame, x=x, y=rng.uniform(0.18, 0.45) * hy, vx=np.cos(ang) * sp, vy=np.sin(ang) * sp,
                    cols=cols, rise=0.55, life=1.9)

    # ------------------------------------------------------------- 1フレーム
    def render(self, i: int) -> np.ndarray:
        f, W, H, hy = self.f, self.W, self.H, self.hy
        t = i / f.fps
        b, k, e, hi, dr = f.bass[i], f.kick[i], f.energy[i], f.high[i], f.drop[i]
        prog = f.beat_phase[i]
        img = np.zeros((H, W, 3), np.float32)
        glow = np.zeros((H, W, 3), np.float32)

        sky = self.sky.copy()
        for g, layer in enumerate(self.stars):
            sky += layer * (0.45 + 0.35 * np.sin(t * (1.1 + g * 0.6) + g * 2) + 0.4 * hi)
        img[:hy] = sky

        # 流れ星
        for (fr, x0, y0, s) in self.meteors:
            age = (i - fr) / f.fps
            if 0 <= age < 0.9:
                p0 = (int(x0 + 700 * s * age), int(y0 + 260 * s * age))
                p1 = (int(x0 + 700 * s * (age - 0.12)), int(y0 + 260 * s * (age - 0.12)))
                a = (1 - age / 0.9)
                cv2.line(glow, p1, p0, (a, a * 0.95, a), 2, cv2.LINE_AA)

        # 月と円形スペクトラム
        cx, cy = self.moon_c
        R = self.moon_r
        Rs = int(R * (1 + 0.05 * b + 0.03 * k))
        spec = f.spectrum[i]
        for a_, v in zip(self.ring_angles, spec):
            for sgn in (1, -1):
                ang = a_ if sgn == 1 else np.pi - a_
                r0 = Rs * 1.18
                r1 = r0 + (0.03 + 0.7 * v ** 1.6) * R * (0.6 + 0.6 * e)
                c = (0.85 + 0.15 * v, 0.7 + 0.25 * (1 - v), 1.0)
                cv2.line(glow, (int(cx + np.cos(ang) * r0), int(cy + np.sin(ang) * r0)),
                         (int(cx + np.cos(ang) * r1), int(cy + np.sin(ang) * r1)), c, max(2, W // 400), cv2.LINE_AA)
        moon = cv2.resize(self.moon_rgb, (2 * Rs, 2 * Rs))
        ma = cv2.resize(self.moon_a, (2 * Rs, 2 * Rs))[..., None]
        y0, x0 = cy - Rs, cx - Rs
        reg = img[y0:y0 + 2 * Rs, x0:x0 + 2 * Rs]
        reg[:] = reg * (1 - ma) + moon * ma * (0.95 + 0.1 * b)
        mg = np.zeros((H, W, 3), np.float32)
        mg[y0:y0 + 2 * Rs, x0:x0 + 2 * Rs] = ma * np.array([1.0, 0.8, 0.95], np.float32)
        glow += _blur(mg, 30, 4) * (0.15 + 0.2 * b)

        # 雲（月の光で少し明るくなる）
        for ci, cl in enumerate(self.clouds):
            off = int((t * cl["speed"] * 3 + prog * cl["speed"] * 0.5) % W)
            rgb = cl["rgb"][:, off:off + W]
            a = cl["a"][:, off:off + W]
            y = cl["y"]
            hgt = min(rgb.shape[0], hy - y)
            reg = img[y:y + hgt]
            reg[:] = reg * (1 - a[:hgt]) + rgb[:hgt] * a[:hgt] * (0.85 + 0.25 * b)

        # 街（奥→手前）
        for depth, c in enumerate(self.city):
            top = c["top"]
            reg = img[top:hy + 1]
            reg[:] = reg * (1 - c["a"]) + c["rgb"] * c["a"]
            for gi, (wl, wg) in enumerate(zip(c["wins"], c["glow"])):
                # 3つのグループが拍に合わせて順番に強く光る
                phase = (prog * 2 + gi / 3) % 1.0
                lvl = 0.55 + 0.25 * np.sin(2 * np.pi * phase) + (0.6 * k if gi == int(prog * 2) % 3 else 0.15 * k)
                lvl *= 0.75 + 0.35 * e
                reg += wl * lvl
                glow[top:hy + 1] += wg * lvl * 0.8
            for (lx, ly) in c["lamps"]:
                on = (np.sin(t * 3 + lx) > 0.2)
                if on:
                    cv2.circle(glow, (lx, top + ly), 3, (1.0, 0.25, 0.3), -1, cv2.LINE_AA)

        # 花火
        fw = np.zeros((H, W, 3), np.float32)
        g_ = 140.0
        for s in self.fireworks:
            age = (i - s["frame"]) / f.fps
            if age < 0 or age > s["rise"] + s["life"]:
                continue
            if age < s["rise"]:  # 打ち上げ
                p = age / s["rise"]
                y = hy - (hy - s["y"]) * (1 - (1 - p) ** 2)
                cv2.circle(fw, (int(s["x"]), int(y)), 3, (1.0, 0.95, 0.85), -1, cv2.LINE_AA)
                continue
            ta = age - s["rise"]
            drag = (1 - np.exp(-2.2 * ta)) / 2.2
            xs = s["x"] + s["vx"] * drag
            ys = s["y"] + s["vy"] * drag + 0.5 * g_ * ta ** 2
            ta2 = max(0.0, ta - 0.07)
            drag2 = (1 - np.exp(-2.2 * ta2)) / 2.2
            xs2 = s["x"] + s["vx"] * drag2
            ys2 = s["y"] + s["vy"] * drag2 + 0.5 * g_ * ta2 ** 2
            fade = (1 - ta / s["life"]) ** 1.5
            twinkle = 0.7 + 0.3 * np.sin(ta * 40 + np.arange(len(xs)))
            for x1, y1, x2, y2, c, tw in zip(xs, ys, xs2, ys2, s["cols"], twinkle):
                col = tuple(float(v) * fade * tw for v in c)
                cv2.line(fw, (int(x2), int(y2)), (int(x1), int(y1)), col, 3, cv2.LINE_AA)
            if ta < 0.15:  # はじけた瞬間の光
                cv2.circle(glow, (int(s["x"]), int(s["y"])), int(60 * (1 - ta / 0.15)) + 1, (1, 0.9, 0.95), -1, cv2.LINE_AA)
        fw[hy:] = 0
        img += fw
        glow += fw * 1.5

        # 光の粒
        self.particles.draw(glow, t, prog, e)

        # 水面：上の景色を逆さまに映して、ゆらゆら
        rh = H - hy
        src = img[hy - rh:hy][::-1].copy() if hy >= rh else img[:hy][::-1].copy()
        src = cv2.resize(src, (W, rh)) if src.shape[0] != rh else src
        yy = np.arange(rh, dtype=np.float32)
        amp = 1.0 + 5 * (yy / rh) + 3 * b
        mx = (np.arange(W, dtype=np.float32)[None, :] + amp[:, None] * np.sin(yy[:, None] * (0.35 - 0.2 * yy[:, None] / rh)
                                                                              - t * 2.2)).astype(np.float32)
        my = np.repeat(yy[:, None], W, 1).astype(np.float32)
        refl = cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        refl = cv2.blur(refl, (15, 1))  # 水面らしく横ににじませる
        water = _vgrad(rh, W, [(0, "#3a1f63"), (1, "#0a0618")])
        img[hy:] = water + refl * np.linspace(0.55, 0.15, rh)[:, None, None] * np.array([0.9, 0.85, 1.0], np.float32)
        gsrc = glow[hy - rh:hy][::-1] if hy >= rh else glow[:hy][::-1]
        gsrc = cv2.resize(gsrc, (W, rh)) if gsrc.shape[0] != rh else gsrc
        glow[hy:] += cv2.remap(gsrc, mx, my, cv2.INTER_LINEAR) * np.linspace(0.4, 0.05, rh)[:, None, None]
        cv2.line(img, (0, hy), (W, hy), (1.0, 0.75, 0.85), 1, cv2.LINE_AA)

        # 光のにじみ
        img += glow * 0.6 + _blur(glow, 16, 4) * (0.8 + 0.4 * b) + _blur(glow, 60, 8) * (0.5 + 0.5 * e)

        # タイトル
        img = img * (1 - self.title_a) + self.title_rgb * self.title_a
        img += self.title_glow * (0.5 + 0.4 * k + 0.5 * dr)
        return self.post(img, i, f, self.rng)
