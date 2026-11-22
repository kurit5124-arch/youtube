#!/usr/bin/env python3
"""犯人の自白風ショート用の、不穏なオリジナル BGM を作って assets/bgm_special/ に保存する。

  python scripts/make_suspense_bgm.py

低いうなり（ドローン）＋心臓の鼓動＋ときどき鳴る不協和音（60秒）。
いつもの日替わり BGM（assets/bgm/）には混ざりません。topics.yaml の bgm: で指定して使います。
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "bgm_special"


def main(seconds: float = 60.0) -> None:
    rng = np.random.default_rng(7)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    buf = np.zeros(n)

    # 低いうなり（D1 と少しずれた音でうねらせる）
    for f, g in ((36.7, 0.5), (37.1, 0.4), (73.4, 0.15), (77.8, 0.06)):  # 77.8 = 半音上の不協和
        buf += g * np.sin(2 * np.pi * f * t + rng.uniform(0, 6))
    buf *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t)

    # 心臓の鼓動（ドクン、ドクン）
    def thump(dur=0.18, f0=60):
        m = int(dur * SR)
        tt = np.arange(m) / SR
        return np.sin(2 * np.pi * (f0 * tt + 20 * (1 - np.exp(-tt * 30)))) * np.exp(-tt * 18)

    beat = 60 / 62
    pos = 2.0
    while pos < seconds - 1:
        for off, g in ((0, 0.9), (0.28, 0.6)):
            i = int((pos + off) * SR)
            s = thump() * g
            j = min(n, i + len(s))
            buf[i:j] += s[: j - i]
        pos += beat

    # ときどき鳴る高い不協和音（チリッとした緊張感）
    for start in np.arange(6, seconds - 4, 8):
        m = int(3.5 * SR)
        tt = np.arange(m) / SR
        s = sum(np.sin(2 * np.pi * f * tt) for f in (622.3, 659.3)) * np.exp(-tt * 1.2) * 0.07
        i = int(start * SR)
        buf[i:i + m] += s[: n - i]

    # フェードと簡単な残響
    fade = np.ones(n)
    fade[: SR * 2] = np.linspace(0, 1, SR * 2)
    fade[-SR * 3:] = np.linspace(1, 0, SR * 3)
    buf *= fade
    out = buf.copy()
    for d, g in ((0.05, 0.3), (0.11, 0.2), (0.23, 0.12)):
        k = int(d * SR)
        out[k:] += buf[:-k] * g
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.85
    stereo = np.stack([out, np.roll(out, int(0.015 * SR))], axis=1)

    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / "suspense.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    mp3 = OUT / "suspense.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "160k", str(mp3)], check=True)
    wav.unlink()
    print(f"作成: {mp3}")


if __name__ == "__main__":
    main()
