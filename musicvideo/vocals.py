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


_ANALYSIS: dict = {}


def analyze_word(word: str, voice: str):
    """WORLD で「声の高さ・声色・息っぽさ」に分ける（キャッシュ）"""
    key = (word, voice)
    if key not in _ANALYSIS:
        import pyworld as pw
        x = tts(word, voice)
        f0, t = pw.harvest(x, SR, f0_floor=70, f0_ceil=700, frame_period=FP)
        sp = pw.cheaptrick(x, f0, t, SR)
        ap = pw.d4c(x, f0, t, SR)
        voiced = np.where(f0 > 0)[0]
        if len(voiced) < 3:
            voiced = np.arange(len(f0))
        v0, v1 = int(voiced[0]), int(voiced[-1])
        # 母音の部分の大きさ（語ごとの音量をそろえるため）
        power = float(np.mean(np.log(np.sum(sp[v0:v1 + 1], axis=1) + 1e-12)))
        _ANALYSIS[key] = dict(f0=f0, sp=sp, ap=ap, v0=v0, v1=v1, power=power)
    return _ANALYSIS[key]


def _phrases(lines, gap_beats=0.6):
    """歌詞を息つぎ（休符）ごとのフレーズに分ける"""
    out, cur = [], []
    last_end = None
    for word, notes in lines:
        st = notes[0][0]
        if cur and last_end is not None and st - last_end > gap_beats:
            out.append(cur)
            cur = []
        cur.append((word, notes))
        last_end = notes[-1][0] + notes[-1][1]
    if cur:
        out.append(cur)
    return out


def sing_phrase(phrase, beat, voice, transpose=0, vib_depth=0.18, seed=0):
    """フレーズ全体をひと息で歌う（語と語の間も声がつながり、音程はなめらかにすべる）。
    戻り値: (開始秒, 音)"""
    import pyworld as pw
    rng = np.random.default_rng(seed)
    words = [(w, [(p * beat, ln * beat, m + transpose) for p, ln, m in ns]) for w, ns in phrase]
    info = [analyze_word(w, voice) for w, _ in words]
    target_pow = np.mean([a["power"] for a in info])
    maxpre = int(120 / FP)
    t_start = words[0][1][0][0] - (maxpre + 4) * FP / 1000
    t_end = words[-1][1][-1][0] + words[-1][1][-1][1] + 0.35
    nfr = int((t_end - t_start) * 1000 / FP) + 1
    nb = info[0]["sp"].shape[1]
    SP = np.full((nfr, nb), 1e-12)
    AP = np.ones((nfr, nb))
    V = np.zeros(nfr, bool)
    fr = lambda sec: int(round((sec - t_start) * 1000 / FP))  # noqa: E731

    for wi, ((w, notes), a) in enumerate(zip(words, info)):
        f0, sp, ap, v0, v1 = a["f0"], a["sp"], a["ap"], a["v0"], a["v1"]
        n = len(f0)
        pre = min(v0, maxpre)
        post = min(n - 1 - v1, int(110 / FP))
        start = fr(notes[0][0])
        # 次の語の子音が始まるところまで母音を伸ばす（レガート）。休符があれば音符の長さまで
        end_note = fr(notes[-1][0] + notes[-1][1])
        if wi + 1 < len(words):
            nxt = words[wi + 1][1][0][0]
            nxt_pre = min(info[wi + 1]["v0"], maxpre)
            end_note = min(max(end_note, fr(nxt) - nxt_pre), fr(nxt) - nxt_pre)
        mid_end = max(start + 6, end_note - post)
        n_mid = mid_end - start
        idx = np.concatenate([np.arange(v0 - pre, v0), np.linspace(v0, v1, n_mid), np.arange(v1 + 1, v1 + 1 + post)])
        i0 = np.floor(idx).astype(int).clip(0, n - 1)
        i1 = np.minimum(i0 + 1, n - 1)
        wgt = (idx - i0)[:, None]
        sp2 = sp[i0] * (1 - wgt) + sp[i1] * wgt
        ap2 = ap[i0] * (1 - wgt) + ap[i1] * wgt
        sp2 *= np.exp(target_pow - a["power"])  # 音量をそろえる
        vflag = f0[np.rint(idx).astype(int).clip(0, n - 1)] > 0
        s0 = start - pre
        s1 = min(nfr, s0 + len(idx))
        L = s1 - s0
        # 重なるところはなめらかにつなぐ
        xf = np.ones(L)
        k = min(4, L)
        xf[:k] = np.linspace(0.3, 1, k)
        old = SP[s0:s1]
        blend = (old > 1e-10).any(axis=1)[:, None] & (xf[:, None] < 1)
        SP[s0:s1] = np.where(blend, old * (1 - xf[:, None]) + sp2[:L] * xf[:, None], sp2[:L])
        AP[s0:s1] = ap2[:L]
        V[s0:s1] |= vflag[:L]
        # 声の終わりは少しずつ小さく（息が抜けるように）
        if wi + 1 == len(words) or fr(words[wi + 1][1][0][0]) - s1 > 8:
            tail = min(L, 14)
            SP[s1 - tail:s1] *= np.linspace(1, 0.05, tail)[:, None] ** 2

    # 目標の音程（半音）：音符どおり、次の音へはなめらかにすべる
    semis = np.full(nfr, np.nan)
    for _, notes in words:
        for p, ln, m in notes:
            semis[fr(p):fr(p + ln)] = m
    idxs = np.where(~np.isnan(semis))[0]
    semis = np.interp(np.arange(nfr), idxs, semis[idxs])
    ker = np.hanning(17)
    ker /= ker.sum()
    semis = np.convolve(np.pad(semis, 8, mode="edge"), ker, mode="valid")  # 約80msのポルタメント
    tt = np.arange(nfr) * FP / 1000
    # 長い音にだけ、少し遅れてかかるビブラート
    for _, notes in words:
        for p, ln, m in notes:
            if ln > 0.55:
                a, b = fr(p), fr(p + ln)
                loc = tt[a:b] - tt[a]
                rate = 5.0 + rng.uniform(-0.3, 0.3)
                depth = vib_depth * np.clip((loc - 0.3) / 0.35, 0, 1)
                semis[a:b] += depth * np.sin(2 * np.pi * rate * loc)
    # ごくわずかな揺らぎ（人の声らしさ）
    drift = np.convolve(rng.standard_normal(nfr), np.hanning(41) / np.hanning(41).sum(), mode="same")
    semis += drift * 0.06
    f0n = np.where(V, 440.0 * 2 ** ((semis - 69) / 12), 0.0)
    y = pw.synthesize(f0n, np.ascontiguousarray(SP), np.ascontiguousarray(AP), SR, frame_period=FP)
    # なめらかな音量（短いトゲを抑える）
    env = np.sqrt(np.convolve(y ** 2, np.ones(441) / 441, mode="same")) + 1e-6
    target = np.convolve(env, np.ones(2205) / 2205, mode="same")
    y = y * np.clip(target / env, 0.5, 1.5) ** 0.5
    y /= np.percentile(np.abs(y), 99.7) + 1e-9
    return t_start, y * 0.7


def render_lyrics(lines, beat: float, voice="en-US-AriaNeural", transpose: int = 0, vib_depth=0.18, seed=0):
    """lines: [(単語, [(拍位置, 長さ[拍], MIDI), ...]), ...] → [(開始秒, 音)]（フレーズごと）"""
    return [sing_phrase(ph, beat, voice, transpose, vib_depth, seed + k) for k, ph in enumerate(_phrases(lines))]
