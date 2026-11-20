#!/usr/bin/env python3
"""著作権フリーのオリジナル BGM をプログラムで作曲して assets/bgm/ に保存する。

  python scripts/make_bgm.py

明るめのポップ / ゆったり lo-fi / 軽快 の3曲を作ります（各60秒）。
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "bgm"

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def chord(root: str, kind: str, octave: int = 4) -> list[int]:
    base = 12 * (octave + 1) + NOTE[root]
    steps = {"maj": [0, 4, 7], "min": [0, 3, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10]}[kind]
    return [base + s for s in steps]


def env(n: int, a: float, r: float) -> np.ndarray:
    e = np.ones(n)
    na, nr = int(a * SR), int(r * SR)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def pad(notes, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for m in notes:
        f = freq(m)
        for det in (-0.12, 0.12):  # 少しずらして厚みを出す
            ff = f * 2 ** (det / 12)
            s += 0.6 * np.sin(2 * np.pi * ff * t) + 0.2 * np.sin(2 * np.pi * 2 * ff * t)
    return s / len(notes) * env(n, 0.25, 0.4) * 0.35


def pluck(m, dur, bright=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq(m)
    s = np.sin(2 * np.pi * f * t) + 0.35 * bright * np.sin(2 * np.pi * 2 * f * t) + 0.1 * bright * np.sin(2 * np.pi * 3 * f * t)
    return s * np.exp(-t * 6) * env(n, 0.003, 0.02) * 0.3


def bass(m, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq(m)
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)) * env(n, 0.01, 0.08) * 0.45


def kick():
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 25) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14) * 0.8


def hat(rng):
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    s = rng.standard_normal(n)
    s = np.diff(s, prepend=0)  # 高い音だけ残す
    return s * np.exp(-t * 80) * 0.08


def snare(rng):
    n = int(0.18 * SR)
    t = np.arange(n) / SR
    return (rng.standard_normal(n) * 0.5 + np.sin(2 * np.pi * 190 * t)) * np.exp(-t * 22) * 0.25


def add(buf, sig, pos):
    i = int(pos * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += sig[: j - i]


def song(name, bpm, prog, arp_pattern, drums, seconds=60, seed=0, swing=0.0, bright=1.0):
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = beat * 4
    buf = np.zeros(int(seconds * SR) + SR)
    nbars = int(seconds / bar)
    for b in range(nbars):
        root, kind = prog[b % len(prog)]
        notes = chord(root, kind)
        t0 = b * bar
        add(buf, pad(notes, bar), t0)
        add(buf, bass(notes[0] - 24, beat * 1.8), t0)
        add(buf, bass(notes[0] - 24, beat * 1.8), t0 + beat * 2)
        for k, idx in enumerate(arp_pattern):
            if idx is None:
                continue
            pos = t0 + k * beat / 2 + (swing * beat / 2 if k % 2 else 0)
            add(buf, pluck(notes[idx % len(notes)] + 12 * (idx // len(notes)) + 12, beat * 0.9, bright), pos)
        if drums and b >= 1:  # 1小節目はドラムなしで始める
            for q in range(4):
                if q in (0, 2):
                    add(buf, kick(), t0 + q * beat)
                if q in (1, 3) and drums == "full":
                    add(buf, snare(rng), t0 + q * beat)
            for e in range(8):
                add(buf, hat(rng), t0 + e * beat / 2 + (swing * beat / 2 if e % 2 else 0))
    buf = buf[: int(seconds * SR)]
    buf *= env(len(buf), 1.0, 2.5)
    # 簡単なリバーブ（ディレイを重ねる）
    out = buf.copy()
    for d, g in ((0.031, 0.25), (0.047, 0.2), (0.089, 0.15), (0.13, 0.1)):
        k = int(d * SR)
        out[k:] += buf[:-k] * g
    out /= np.max(np.abs(out)) + 1e-9
    out *= 0.85
    stereo = np.stack([out, np.roll(out, int(0.012 * SR))], axis=1)  # 少し左右に広げる

    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    mp3 = OUT / f"{name}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "160k", str(mp3)], check=True)
    wav.unlink()
    print(f"作成: {mp3}")


if __name__ == "__main__":
    # 明るいポップ（C → G → Am → F）
    song("01_bright_pop", 110, [("C", "maj"), ("G", "maj"), ("A", "min"), ("F", "maj")],
         [0, 1, 2, 1, 3, 2, 1, 2], drums="full", seed=1)
    # ゆったり lo-fi（Fmaj7 → Em7 → Dm7 → Cmaj7）
    song("02_chill_lofi", 82, [("F", "maj7"), ("E", "min7"), ("D", "min7"), ("C", "maj7")],
         [0, None, 2, 3, None, 1, 2, None], drums="full", seed=2, swing=0.25, bright=0.4)
    # 軽快（D → A → Bm → G）
    song("03_light_step", 124, [("D", "maj"), ("A", "maj"), ("B", "min"), ("G", "maj")],
         [0, 2, 1, 2, 0, 2, 3, 2], drums="kick", seed=3, bright=0.8)
