#!/usr/bin/env python3
"""社会派テーマ用の暗め・落ち着いた BGM をプログラムで作曲して assets/bgm_dark/ に保存する。

  python scripts/make_dark_bgm.py

明るい曲が混ざらないよう、いつもの assets/bgm/ とは別のフォルダに置きます。
使うときはネタ帳に bgm: assets/bgm_dark/01_serious_ambient.mp3 のように書きます。
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_bgm import SR, chord, env, freq  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "assets" / "bgm_dark"


def dark_pad(notes, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for m in notes:
        f = freq(m)
        for det in (-0.08, 0.0, 0.08):
            ff = f * 2 ** (det / 12)
            s += np.sin(2 * np.pi * ff * t) + 0.15 * np.sin(2 * np.pi * 2 * ff * t)
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.12 * t)  # ゆっくり揺れる
    return s / (len(notes) * 3) * env(n, 1.2, 1.5) * lfo * 0.5


def drone(m, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq(m)
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 0.5 * t)) * env(n, 2.0, 2.0) * 0.22


def piano(m, dur=3.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq(m)
    s = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t) + 0.08 * np.sin(2 * np.pi * 3 * f * t)
    return s * np.exp(-t * 1.6) * env(n, 0.005, 0.3) * 0.16


def pulse():
    """心臓の鼓動のような、低くこもった「ドクン」。"""
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 55 * np.exp(-t * 6)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14) * 0.25


def add(buf, sig, pos):
    i = int(pos * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += sig[: j - i]


def serious(seconds=72, seed=3):
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(seconds * SR))
    prog = [("A", "min"), ("F", "maj"), ("D", "min"), ("E", "min")]
    bar = 6.0  # 1 コード 6 秒のゆっくりした進行
    pos, k = 0.0, 0
    while pos < seconds:
        root, kind = prog[k % len(prog)]
        notes = chord(root, kind, 3)
        add(buf, dark_pad(notes, bar + 1.5), pos)
        add(buf, drone(notes[0] - 12, bar + 1.5), pos)
        # まばらなピアノ（コードの音から）
        for beat in (0.0, 1.5, 3.0, 4.5):
            if rng.random() < 0.6:
                add(buf, piano(int(rng.choice(notes)) + 12 * int(rng.integers(1, 3))), pos + beat + rng.uniform(0, 0.15))
        # 鼓動（ドクン、ドクン）
        for beat in (0.0, 3.0):
            add(buf, pulse(), pos + beat)
            add(buf, pulse() * 0.6, pos + beat + 0.32)
        pos += bar
        k += 1
    buf *= env(len(buf), 1.5, 2.5)
    return buf / (np.max(np.abs(buf)) + 1e-9) * 0.8


def save(name, sig):
    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / f"{name}.wav"
    data = (np.clip(sig, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    mp3 = OUT / f"{name}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "2", "-b:a", "160k", str(mp3)], check=True)
    wav.unlink()
    print(f"[bgm] {mp3}")


if __name__ == "__main__":
    save("01_serious_ambient", serious())
