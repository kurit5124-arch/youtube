"""女性ボーカルを作る：音声合成で1語ずつ話させ、WORLD（音声分析・合成）で音程と長さをメロディに合わせて「歌わせる」。

  - 子音はそのままの長さ、母音を音符の長さまで伸ばす
  - 音程は楽譜どおり＋しゃくり（下から入る）＋なめらかなつながり＋長い音にはビブラート
  - 1語に複数の音（例: to-night）があるときは、母音の中で音程を切り替える

音声合成は Microsoft Edge の読み上げ（edge-tts、無料）。作った声は cache に保存して使い回す。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import ssl
import subprocess
from pathlib import Path

import numpy as np

SR = 44100
FP = 5.0  # WORLD のフレーム間隔（ミリ秒）
CACHE = Path(__file__).resolve().parent.parent / "output" / "voice_cache"


def tts(word: str, voice: str = "en-US-AriaNeural", rate: str = "-10%") -> np.ndarray:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{voice}|{rate}|{word}".encode()).hexdigest()[:16]
    wav = CACHE / f"{key}.wav"
    if not wav.exists():
        import edge_tts
        import edge_tts.communicate as ec
        ca = "/root/.ccr/ca-bundle.crt"
        if Path(ca).exists():
            ec._SSL_CTX = ssl.create_default_context(cafile=ca)
        mp3 = CACHE / f"{key}.mp3"

        async def run():
            c = edge_tts.Communicate(word, voice, rate=rate, proxy=os.environ.get("HTTPS_PROXY"))
            await c.save(str(mp3))
        for attempt in range(4):
            try:
                asyncio.run(run())
                break
            except Exception:
                if attempt == 3:
                    raise
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), str(wav)],
                       check=True)
        mp3.unlink()
    import wave
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768
    # 前後の無音を切る
    fr = 256
    e = np.array([np.sqrt(np.mean(x[i:i + fr] ** 2)) for i in range(0, len(x) - fr, fr)])
    on = np.where(e > e.max() * 0.03)[0]
    if len(on):
        x = x[max(0, on[0] * fr - fr): min(len(x), (on[-1] + 2) * fr)]
    return x


def sing(word_audio: np.ndarray, notes: list[tuple[float, float]], legato: float = 0.95):
    """notes: [(長さ[秒], MIDI)] → (歌声, 子音の長さ[秒]) 。子音の長さぶん早めに置くと母音が拍に乗る。"""
    import pyworld as pw
    x = word_audio
    f0, t = pw.harvest(x, SR, f0_floor=70, f0_ceil=700, frame_period=FP)
    sp = pw.cheaptrick(x, f0, t, SR)
    ap = pw.d4c(x, f0, t, SR)
    n = len(f0)
    voiced = np.where(f0 > 0)[0]
    if len(voiced) < 3:
        voiced = np.arange(n)
    v0, v1 = int(voiced[0]), int(voiced[-1])
    pre = min(v0, int(120 / FP))
    post = min(n - 1 - v1, int(140 / FP))
    v0s = v0 - pre  # 子音より前は捨てる
    total = sum(d for d, _ in notes) * legato
    n_mid = max(8, int(total * 1000 / FP) - pre - post)
    idx = np.concatenate([np.arange(v0s, v0), np.linspace(v0, v1, n_mid), np.arange(v1 + 1, v1 + 1 + post)])
    i0 = np.floor(idx).astype(int).clip(0, n - 1)
    i1 = np.minimum(i0 + 1, n - 1)
    w = (idx - i0)[:, None]
    sp2 = sp[i0] * (1 - w) + sp[i1] * w
    ap2 = ap[i0] * (1 - w) + ap[i1] * w
    vflag = f0[np.rint(idx).astype(int).clip(0, n - 1)] > 0

    # 目標の音程（半音単位）を作る
    m = len(idx)
    semis = np.zeros(m)
    start = pre
    durs = np.array([d for d, _ in notes])
    bounds = start + np.round(np.cumsum(np.concatenate([[0], durs / durs.sum()])) * n_mid).astype(int)
    for k, (d, midi) in enumerate(notes):
        a, b = bounds[k], bounds[k + 1]
        semis[a:b] = midi
    semis[:start] = notes[0][1]
    semis[start + n_mid:] = notes[-1][1]
    # なめらかなつながり（約40ms）
    ker = np.hanning(9)
    ker /= ker.sum()
    semis = np.convolve(np.pad(semis, 4, mode="edge"), ker, mode="valid")
    # しゃくり（各音の頭で少し下から）とビブラート
    tt = np.arange(m) * FP / 1000
    for k, (d, midi) in enumerate(notes):
        a, b = bounds[k], bounds[k + 1]
        loc = tt[a:b] - tt[a]
        semis[a:b] += -0.35 * np.exp(-loc / 0.05) * (1 if k == 0 else 0.5)
        if d > 0.45:
            depth = 0.22 * np.clip((loc - 0.22) / 0.25, 0, 1)
            semis[a:b] += depth * np.sin(2 * np.pi * 5.4 * loc)
    f0n = 440.0 * 2 ** ((semis - 69) / 12)
    f0n[~vflag] = 0
    y = pw.synthesize(f0n, np.ascontiguousarray(sp2), np.ascontiguousarray(ap2), SR, frame_period=FP)
    fade = min(len(y) // 4, int(0.03 * SR))
    y[-fade:] *= np.linspace(1, 0, fade)
    y[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    peak = np.max(np.abs(y)) + 1e-9
    return y / peak * 0.8, pre * FP / 1000


def render_lyrics(lines, beat: float, voice="en-US-AriaNeural", transpose: int = 0):
    """lines: [(単語, [(拍位置, 長さ[拍], MIDI), ...]), ...] → [(開始秒, 音)]"""
    out = []
    for word, notes in lines:
        audio = tts(word, voice)
        seg, lead = sing(audio, [(ln * beat, m + transpose) for _, ln, m in notes])
        out.append((notes[0][0] * beat - lead, seg))
    return out
