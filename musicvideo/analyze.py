"""音声を解析して、映像のフレームごとに「低音・中音・高音の強さ」「キックの瞬間」などを出す。

どんな mp3 / wav でも使えるので、他の AI 作曲サービスで作った曲にも対応できます。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 44100


def load_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


@dataclass
class Features:
    fps: int
    n: int
    bass: np.ndarray        # 0〜1 低音の強さ（なめらか）
    mid: np.ndarray
    high: np.ndarray
    energy: np.ndarray      # 0〜1 全体の盛り上がり（ゆっくり変化）
    kick: np.ndarray        # 0〜1 キックの瞬間に1になり、すぐ減衰
    drop: np.ndarray        # 0〜1 大きく盛り上がった瞬間（ドロップ）に1、ゆっくり減衰
    spectrum: np.ndarray    # (n, bands) 0〜1 スペクトラム（バー表示用）
    beat_phase: np.ndarray  # 累積の「進み具合」（盛り上がるほど速く進む）


def _norm(x: np.ndarray, pct=98) -> np.ndarray:
    hi = np.percentile(x, pct) + 1e-9
    return np.clip(x / hi, 0, 1)


def _smooth(x: np.ndarray, attack: float, release: float) -> np.ndarray:
    y = np.zeros_like(x)
    v = 0.0
    for i, xi in enumerate(x):
        c = attack if xi > v else release
        v += (xi - v) * c
        y[i] = v
    return y


def analyze(path: Path, fps: int = 30, bands: int = 48) -> Features:
    a = load_audio(path)
    hop = SR / fps
    n = int(len(a) / hop)
    win = 4096
    window = np.hanning(win)
    pad = np.concatenate([np.zeros(win // 2), a, np.zeros(win)])
    freqs = np.fft.rfftfreq(win, 1 / SR)

    # 対数間隔のバンド（40Hz〜14kHz）
    edges = np.geomspace(40, 14000, bands + 1)
    band_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(bands)]
    band_idx = [b if len(b) else np.array([np.argmin(abs(freqs - edges[i]))]) for i, b in enumerate(band_idx)]

    spec = np.zeros((n, bands))
    bass = np.zeros(n)
    mid = np.zeros(n)
    high = np.zeros(n)
    sub = np.zeros(n)
    rms = np.zeros(n)
    m_bass = (freqs >= 35) & (freqs < 150)
    m_sub = (freqs >= 35) & (freqs < 100)
    m_mid = (freqs >= 300) & (freqs < 3000)
    m_high = (freqs >= 5000) & (freqs < 16000)
    for i in range(n):
        s = int(i * hop)
        frame = pad[s:s + win] * window
        mag = np.abs(np.fft.rfft(frame))
        bass[i] = mag[m_bass].mean()
        sub[i] = mag[m_sub].mean()
        mid[i] = mag[m_mid].mean()
        high[i] = mag[m_high].mean()
        rms[i] = np.sqrt(np.mean(frame ** 2))
        spec[i] = [mag[b].mean() for b in band_idx]

    # スペクトラムは dB にして 0〜1
    sdb = 20 * np.log10(spec + 1e-6)
    centers = np.sqrt(edges[:-1] * edges[1:])
    sdb += 4.5 * np.log2(centers / centers[0])  # 高い音ほど小さく見えるので傾きを補正
    hi = np.percentile(sdb, 99.5)
    spec = np.clip((sdb - (hi - 50)) / 50, 0, 1)

    # キック：低音の立ち上がり（オンセット）
    flux = np.maximum(np.diff(sub, prepend=sub[0]), 0)
    flux = _norm(flux, 99)
    thr = 0.3
    kick = np.zeros(n)
    v = 0.0
    last = -10
    for i in range(n):
        v *= 0.80
        if flux[i] > thr and i - last > fps * 0.2:
            v = max(v, min(1.0, 0.5 + flux[i]))
            last = i
        kick[i] = v

    energy = _smooth(_norm(rms, 95), 0.08, 0.02)
    # ドロップ：エネルギーが急に上がった瞬間
    slow = _smooth(_norm(rms, 95), 0.01, 0.01)
    jump = energy - np.roll(slow, int(fps * 0.5))
    jump[: int(fps * 0.5)] = 0
    drop = np.zeros(n)
    v = 0.0
    last = -fps * 10
    for i in range(n):
        v *= 0.93
        if jump[i] > 0.25 and i - last > fps * 8:
            v = 1.0
            last = i
        drop[i] = v

    bass_n = _smooth(_norm(bass), 0.6, 0.15)
    beat_phase = np.cumsum(0.3 + 1.7 * energy) / fps

    return Features(fps=fps, n=n, bass=bass_n, mid=_smooth(_norm(mid), 0.5, 0.15),
                    high=_smooth(_norm(high), 0.7, 0.25), energy=np.clip(energy, 0, 1),
                    kick=kick, drop=drop, spectrum=spec, beat_phase=beat_phase)
