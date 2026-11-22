"""シンセウェーブ／ダークシンセ風の曲を自動作曲・合成する（numpy だけで完結）。

構成（128 BPM, Aマイナー）:
  short（約1分）: イントロ → ビルド → ドロップ → ブレイク → ドロップ2 → アウトロ
  long （約3分）: イントロ → ビルド → ドロップ → ブレイク → ビルド → ドロップ2（別メロ）
                 → ブリッジ（別のコード・ハーフタイム）→ ビルド → ラストドロップ → アウトロ
コード進行・メロディ・ドラムパターンは seed から毎回少しずつ変わります。
"""
from __future__ import annotations

import json
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SR = 44100


def mtof(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- 音源

def _polyblep(phase: np.ndarray, dt: float) -> np.ndarray:
    out = np.zeros_like(phase)
    a = phase < dt
    x = phase[a] / dt
    out[a] = x + x - x * x - 1
    b = phase > 1 - dt
    x = (phase[b] - 1) / dt
    out[b] = x * x + x + x + 1
    return out


def saw(f: float, n: int, phase0: float = 0.0) -> np.ndarray:
    """エイリアスの少ないノコギリ波"""
    dt = f / SR
    ph = (phase0 + dt * np.arange(n)) % 1.0
    return 2 * ph - 1 - _polyblep(ph, dt)


def square(f: float, n: int, phase0: float = 0.0) -> np.ndarray:
    dt = f / SR
    ph = (phase0 + dt * np.arange(n)) % 1.0
    s = np.where(ph < 0.5, 1.0, -1.0)
    s += _polyblep(ph, dt)
    s -= _polyblep((ph + 0.5) % 1.0, dt)
    return s


def lowpass(x: np.ndarray, cutoff: float, reso: float = 0.0) -> np.ndarray:
    """FFT でかける 24dB/oct 相当のローパス（reso でカットオフ付近を持ち上げる）"""
    n = len(x)
    if n < 8:
        return x
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    fr = np.fft.rfftfreq(nfft, 1 / SR)
    r = fr / max(cutoff, 20.0)
    h = 1 / (1 + r ** 4)
    if reso:
        h *= 1 + reso * np.exp(-((r - 1) ** 2) / 0.02)
    return np.fft.irfft(X * h, nfft)[:n]


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    n = len(x)
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    fr = np.fft.rfftfreq(nfft, 1 / SR)
    r = fr / cutoff
    h = r ** 4 / (1 + r ** 4)
    return np.fft.irfft(X * h, nfft)[:n]


def adsr(n: int, a=0.005, d=0.1, s=0.7, r=0.05) -> np.ndarray:
    e = np.full(n, s, dtype=np.float64)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    na = min(na, n)
    e[:na] = np.linspace(0, 1, na, endpoint=False) if na else e[:na]
    nd = min(nd, n - na)
    if nd > 0:
        e[na:na + nd] = np.linspace(1, s, nd)
    nr = min(nr, n)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def supersaw(m: float, dur: float, voices=7, detune=0.18, rng=None) -> np.ndarray:
    n = int(dur * SR)
    rng = rng or np.random.default_rng(0)
    out = np.zeros(n)
    for i in range(voices):
        d = (i - (voices - 1) / 2) / ((voices - 1) / 2) * detune
        out += saw(mtof(m + d), n, rng.random())
    return out / np.sqrt(voices)


# ---------------------------------------------------------------- ドラム

def kick(rng) -> np.ndarray:
    n = int(0.42 * SR)
    t = np.arange(n) / SR
    f = 48 + 190 * np.exp(-t * 32)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)
    body = np.tanh(body * 2.2)
    click = rng.standard_normal(n) * np.exp(-t * 300) * 0.4
    return (body + click) * 0.95


def snare(rng) -> np.ndarray:
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    noise = highpass(rng.standard_normal(n), 1800) * np.exp(-t * 14)
    tone = np.sin(2 * np.pi * (180 + 60 * np.exp(-t * 40)) * t) * np.exp(-t * 25)
    return (noise * 0.55 + tone * 0.6) * 0.7


def clap(rng) -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    env = np.zeros(n)
    for k, off in enumerate((0, 0.011, 0.022)):
        i = int(off * SR)
        env[i:] += np.exp(-(t[: n - i]) * (90 if k < 2 else 18))
    s = lowpass(highpass(rng.standard_normal(n), 900), 5000) * env
    return s * 0.45


def hat(rng, open_=False) -> np.ndarray:
    n = int((0.32 if open_ else 0.06) * SR)
    t = np.arange(n) / SR
    s = highpass(rng.standard_normal(n), 7500)
    s = lowpass(s, 12000)
    return s * np.exp(-t * (9 if open_ else 70)) * (0.09 if open_ else 0.08)


def crash(rng) -> np.ndarray:
    n = int(2.2 * SR)
    t = np.arange(n) / SR
    s = highpass(rng.standard_normal(n), 4000)
    return lowpass(s, 11000) * np.exp(-t * 1.8) * 0.13


def riser(rng, dur: float) -> np.ndarray:
    """ドロップ前に盛り上げるノイズ（だんだん高く・大きく）"""
    n = int(dur * SR)
    seg = 2048
    out = np.zeros(n)
    noise = rng.standard_normal(n)
    for i in range(0, n, seg):
        p = i / n
        chunk = noise[max(0, i - 512): i + seg]
        y = lowpass(chunk, 300 + 9000 * p ** 2, reso=1.5)
        out[i:i + seg] = y[-len(out[i:i + seg]):] if len(chunk) else 0
    return out * np.linspace(0, 1, n) ** 2 * 0.35


def impact(rng) -> np.ndarray:
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    f = 30 + 80 * np.exp(-t * 6)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.5)
    return np.tanh(boom * 1.5) * 0.6


# ---------------------------------------------------------------- 曲

@dataclass
class Section:
    name: str
    bars: int
    layers: set = field(default_factory=set)
    prog: int = 0       # 0 = メインのコード進行, 1 = ブリッジ用の進行
    mel: int = 0        # どのメロディを使うか
    gap: bool = False   # 次のセクションの直前に一瞬無音にする（ドロップを際立たせる）


FULL = {"pad", "arp", "kick", "snare", "hat", "ohat", "bass", "sub", "lead", "crash", "fill"}

# 約1分（ショート向け）
SECTIONS_SHORT = [
    Section("intro", 4, {"pad", "arp_f"}),
    Section("build", 4, {"pad", "arp", "hat", "bass_soft", "riser", "snare_roll"}, gap=True),
    Section("drop", 8, FULL),
    Section("break", 4, {"pad", "arp_f", "lead_soft", "riser"}, gap=True),
    Section("drop2", 8, FULL | {"lead_hi", "arp_hi"}, mel=1),
    Section("outro", 2, {"pad", "arp_f"}),
]

# 約3分（通常動画向け）：2回のドロップのあと、ブリッジで雰囲気を変えてラストドロップへ
SECTIONS_LONG = [
    Section("intro", 8, {"pad", "arp_f", "kick_f_late"}),
    Section("build", 8, {"pad", "arp", "hat", "bass_soft", "riser", "snare_roll", "kick_f"}, gap=True),
    Section("drop", 16, FULL),
    Section("break", 8, {"pad", "arp_f", "lead_soft", "bass_soft"}),
    Section("build2", 4, {"pad", "arp", "hat", "riser", "snare_roll", "bass_soft"}, gap=True),
    Section("drop2", 16, FULL | {"arp_hi"}, mel=1),
    Section("bridge", 8, {"pad", "arp", "half", "bass", "sub", "lead_soft"}, prog=1, mel=2),
    Section("build3", 4, {"pad", "arp", "hat", "riser", "snare_roll", "bass_soft"}, gap=True),
    Section("final", 16, FULL | {"lead_hi", "arp_hi"}),
    Section("outro", 4, {"pad", "arp_f", "kick_f"}),
]
SECTIONS = SECTIONS_SHORT

# ブリッジ用（F → G → Em → Am）
BRIDGE = [(53, "M"), (55, "M"), (52, "m"), (57, "m")]

# Aマイナーのコード進行（ルートのMIDI番号, 構成音）
PROGRESSIONS = [
    [(57, "m"), (53, "M"), (48, "M"), (55, "M")],   # Am F C G
    [(57, "m"), (53, "M"), (50, "m"), (52, "M")],   # Am F Dm E
    [(57, "m"), (55, "M"), (53, "M"), (52, "M")],   # Am G F E
]
TRIAD = {"m": [0, 3, 7], "M": [0, 4, 7]}
SCALE = [57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81]  # A natural minor


RHYTHMS = {
    "synthwave": [
        [(0, 1.5), (1.5, 0.5), (2, 1), (3, 0.5), (3.5, 0.5)],
        [(0, 0.75), (0.75, 0.75), (1.5, 1), (2.5, 0.5), (3, 1)],
        [(0, 1), (1, 0.5), (1.5, 1.5), (3, 1)],
    ],
    # 16分の裏を突くシンコペーション多め（ノリ重視）
    "hard": [
        [(0, 0.75), (0.75, 0.75), (1.5, 0.5), (2, 0.5), (2.5, 0.75), (3.25, 0.75)],
        [(0, 0.5), (0.5, 0.25), (0.75, 0.75), (1.5, 0.5), (2, 1), (3, 0.5), (3.5, 0.5)],
        [(0, 0.75), (0.75, 0.25), (1, 0.5), (1.5, 1), (2.5, 0.5), (3, 0.75), (3.75, 0.25)],
    ],
}


def _melody(rng, prog, style="synthwave") -> list[tuple[float, float, int]]:
    """2小節×4のフック。(拍位置, 長さ[拍], MIDI) のリスト（8小節分）"""
    rhythms = RHYTHMS[style]
    out = []
    motif = None
    for bar in range(8):
        root, kind = prog[bar % 4]
        chord_tones = [root + 12 + i for i in TRIAD[kind]] + [root + 24]
        rhy = rhythms[(bar // 2) % len(rhythms)] if bar % 2 == 0 else rhythms[(bar // 2 + 1) % len(rhythms)]
        if bar % 4 == 0 and motif is None:
            motif = [int(rng.integers(0, len(chord_tones))) for _ in rhy]
        notes = []
        for k, (pos, ln) in enumerate(rhy):
            if k == 0 or rng.random() < 0.55:
                m = chord_tones[motif[k % len(motif)] % len(chord_tones)]
            else:
                # スケール内で隣の音へ
                prev = notes[-1] if notes else chord_tones[0]
                idx = min(range(len(SCALE)), key=lambda i: abs(SCALE[i] - prev))
                idx = int(np.clip(idx + rng.choice([-2, -1, 1, 2]), 0, len(SCALE) - 1))
                m = SCALE[idx]
            notes.append(m)
            out.append((bar * 4 + pos, ln, m))
    return out


def tom(rng, f0: float) -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    f = f0 * (1 + 0.6 * np.exp(-t * 30))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)
    return np.tanh(s * 1.8) * 0.6 + rng.standard_normal(n) * np.exp(-t * 60) * 0.1


STYLES = ("hard", "synthwave")
DEFAULT_BPM = {"hard": 140, "synthwave": 128}


def compose(out_path: Path, seed: int = 7, bpm: float | None = None, title: str = "NEON DRIVE",
            length: str = "short", style: str = "hard", key: int = 0) -> Path:
    """length="short" で約1分、"long" で約3分の曲を作る。
    style="hard" は速くて激しいダークシンセ、"synthwave" はゆったりめのシンセウェーブ。"""
    rng = np.random.default_rng(seed)
    hard = style == "hard"
    bpm = bpm or DEFAULT_BPM[style]
    sections = SECTIONS_LONG if length == "long" else SECTIONS_SHORT
    progs = [PROGRESSIONS[seed % len(PROGRESSIONS)], BRIDGE]
    melodies = [_melody(rng, progs[0], style), _melody(rng, progs[0], style), _melody(rng, progs[1], style)]
    # key: 半音いくつ上げ下げするか（-3 なら Aマイナー → F#マイナー）
    progs = [[(r + key, k) for r, k in p] for p in progs]
    melodies = [[(pos, ln, m + key) for pos, ln, m in mel] for mel in melodies]
    beat = 60 / bpm
    bar = beat * 4
    total_bars = sum(s.bars for s in sections)
    tail = 2.5
    N = int((total_bars * bar + tail) * SR)

    bus = {k: np.zeros(N) for k in ("drums", "bass", "music", "lead", "fx")}
    kick_env = np.zeros(N)  # サイドチェイン用
    gaps = []

    def put(name, sig, t, gain=1.0):
        i = int(t * SR)
        if i >= N:
            return
        j = min(N, i + len(sig))
        bus[name][i:j] += sig[: j - i] * gain

    def add_kick(t, gain=0.9, sig=None):
        put("drums", k_s if sig is None else sig, t, gain)
        i = int(t * SR)
        e = np.exp(-np.arange(min(int(beat * SR), N - i)) / SR * 9) * (1 if sig is None else 0.4)
        kick_env[i:i + len(e)] = np.maximum(kick_env[i:i + len(e)], e)

    k_s, sn_s, cl_s = kick(rng), snare(rng), clap(rng)
    if hard:  # 歪ませて硬く・太く
        k_s = np.tanh(k_s * 2.5) * 0.95
        layered = sn_s.copy()
        layered[: len(cl_s)] += 0.6 * cl_s[: len(sn_s)]
        sn_s = np.tanh(layered * 2.0) * 0.8
    k_f = lowpass(k_s, 250)
    hats = [hat(rng) for _ in range(4)]
    ohat = hat(rng, True)
    toms = [tom(rng, f) for f in (190, 150, 115, 90)]

    bar_i = 0
    timeline = []
    for sec in sections:
        timeline.append({"name": sec.name, "start": round(bar_i * bar, 3)})
        prog = progs[sec.prog]
        melody = melodies[sec.mel]
        for b in range(sec.bars):
            t0 = bar_i * bar
            root, kind = prog[b % 4]
            tones = [root + i for i in TRIAD[kind]]
            L = sec.layers
            prog_in_sec = b / sec.bars
            soft = sec.name in ("intro", "break", "outro")
            fill_bar = "fill" in L and b % 8 == 7

            # パッド
            if "pad" in L:
                n = int(bar * 1.05 * SR)
                s = np.zeros(n)
                for m in tones + [root + 12]:
                    s += supersaw(m, n / SR, voices=5, detune=0.12, rng=rng)
                cut = 900 if soft else 2200
                s = lowpass(s, cut) * adsr(n, 0.25, 0.3, 0.8, 0.3)
                put("music", s, t0, 0.16 if soft else 0.07)

            # アルペジオ（16分）
            if "arp" in L or "arp_f" in L:
                pat = [0, 1, 2, 3, 2, 1, 0, 2, 0, 1, 2, 3, 2, 3, 1, 2]
                seq = tones + [root + 12]
                for k in range(16):
                    m = seq[pat[k] % 4] + 12
                    d = beat / 4
                    n = int(d * 0.95 * SR)
                    s = saw(mtof(m), n) * 0.6 + square(mtof(m + 0.07), n) * 0.4
                    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * (bar_i * 16 + k) / 64)
                    cut = (500 + 1500 * lfo) if "arp_f" in L else (1500 + 3500 * lfo)
                    if sec.name.startswith("build"):
                        cut *= 0.4 + prog_in_sec
                    s = lowpass(s, cut, reso=1.2) * adsr(n, 0.002, 0.08, 0.2, 0.01)
                    g = 0.2 if "arp_f" in L else 0.11
                    put("music", s, t0 + k * d, g)
                    put("fx", s, t0 + k * d + beat * 0.75, g * 0.35)  # 付点8分ディレイ
                    if "arp_hi" in L and k % 2 == 0:
                        h = square(mtof(m + 12), n) * adsr(n, 0.002, 0.05, 0.1, 0.01)
                        put("music", lowpass(h, 6000), t0 + k * d + d, 0.04)

            # ベース（8分刻みのオクターブ）＋サブベース
            if hard and "bass" in L:
                # ローリングベース：キックの拍を空けて 16分の 2・3・4 つ目で刻む
                d = beat / 4
                for q in range(4):
                    for k in (1, 2, 3):
                        m = root - 12
                        n = int(d * 0.92 * SR)
                        raw = saw(mtof(m), n, 0.1) + saw(mtof(m + 0.12), n, 0.6) + 0.7 * square(mtof(m - 12), n)
                        tt = np.arange(n) / SR
                        fenv = np.exp(-tt * 28)
                        dark, bright = lowpass(raw, 350), lowpass(raw, 3800, reso=1.0)
                        s = dark + (bright - dark) * fenv
                        s = np.tanh(s * 3.0) * adsr(n, 0.002, 0.05, 0.8, 0.01)
                        put("bass", s, t0 + q * beat + k * d, 0.3 if k != 3 else 0.36)
            elif "bass" in L or "bass_soft" in L:
                for k in range(8):
                    m = root - 12 + (12 if k % 2 else 0)
                    d = beat / 2
                    n = int(d * 0.9 * SR)
                    s = saw(mtof(m), n) + 0.5 * square(mtof(m - 12), n)
                    cut = 500 if "bass_soft" in L else 1100
                    s = lowpass(s, cut, reso=0.8) * adsr(n, 0.003, 0.12, 0.6, 0.02)
                    put("bass", np.tanh(s * 1.5), t0 + k * d, 0.2 if "bass_soft" in L else 0.32)
            if "sub" in L:
                n = int(bar * SR)
                s = np.sin(2 * np.pi * mtof(root - 24) * np.arange(n) / SR) * adsr(n, 0.01, 0.1, 0.9, 0.05)
                put("bass", s, t0, 0.22)

            # リード
            if "lead" in L or "lead_soft" in L:
                mb = b % 8
                for pos, ln, m in melody:
                    if not (mb * 4 <= pos < (mb + 1) * 4):
                        continue
                    lp = pos % 4
                    oct_ = 12 if "lead_hi" in L and (b // 4) % 2 == 1 else 0
                    n = int(ln * beat * SR)
                    s = supersaw(m + oct_, n / SR, voices=7, detune=0.22, rng=rng)
                    s = s * (1 + 0.003 * np.sin(2 * np.pi * 5.5 * np.arange(n) / SR) * np.linspace(0, 1, n))
                    cut = 1400 if "lead_soft" in L else (7000 if hard else 5200)
                    if hard and "lead_soft" not in L:
                        s = s + 0.6 * saw(mtof(m + oct_ - 12), n)  # 1オクターブ下を重ねて太く
                        s = np.tanh(s * 1.6)
                    s = lowpass(s, cut, reso=0.6) * adsr(n, 0.005, 0.15, 0.75, 0.05)
                    put("lead", s, t0 + lp * beat, 0.1 if "lead_soft" in L else 0.16)

            # コードの刻み（裏拍のスタブ）
            if hard and "kick" in L:
                for pos16 in (2, 6, 10, 13):
                    n = int(beat / 4 * 1.6 * SR)
                    s = np.zeros(n)
                    for m in tones + [root + 12]:
                        s += supersaw(m + 12, n / SR, voices=5, detune=0.2, rng=rng)
                    s = lowpass(s, 4500, reso=0.5) * adsr(n, 0.002, 0.09, 0.15, 0.02)
                    put("music", s, t0 + pos16 * beat / 4, 0.09)
                    put("fx", s, t0 + pos16 * beat / 4 + beat * 0.75, 0.025)

            # ドラム
            if hard and sec.name.startswith("build") and b >= sec.bars - 4:
                # ビルドの最後はキックがだんだん細かくなる
                per = [4, 4, 8, 16][b - (sec.bars - 4)]
                for k in range(per):
                    add_kick(t0 + k * bar / per, 0.25 + 0.25 * (b - sec.bars + 4) / 3, k_f if per > 8 else None)
            if "kick" in L:
                for q in range(4):
                    add_kick(t0 + q * beat)
            if "kick_f" in L or ("kick_f_late" in L and b >= sec.bars // 2):
                for q in range(4):
                    add_kick(t0 + q * beat, 0.4, k_f)
            if "half" in L:  # ハーフタイム（ゆったり重いノリ）
                for q in (0, 2.5):
                    add_kick(t0 + q * beat)
                put("drums", sn_s, t0 + 2 * beat, 0.75)
                put("drums", cl_s, t0 + 2 * beat + 0.005, 0.65)
                for e8 in range(8):
                    put("drums", hats[e8 % 4], t0 + e8 * beat / 2, 0.8 if e8 % 2 else 0.5)
            if "snare" in L:
                for q in (1, 3):
                    if fill_bar and q == 3:
                        continue
                    put("drums", sn_s, t0 + q * beat, 0.7)
                    put("drums", cl_s, t0 + q * beat + 0.005, 0.6)
            if "hat" in L:
                for e8 in range(16):
                    if e8 % 2 == 0 and sec.name.startswith("build") and prog_in_sec < 0.5:
                        continue
                    if fill_bar and e8 >= 12:
                        continue
                    if hard:
                        vel = [0.45, 0.3, 1.0, 0.55][e8 % 4]
                        sw = beat / 4 * 0.12 if e8 % 2 else 0  # 少しだけハネる
                    else:
                        vel, sw = (1.0 if e8 % 4 == 2 else 0.55), 0
                    put("drums", hats[e8 % 4], t0 + e8 * beat / 4 + sw, vel)
            if "ohat" in L:
                for q in range(4):
                    put("drums", ohat, t0 + q * beat + beat / 2, 0.8)
            if fill_bar:  # 8小節ごとのタムのフィル
                for k in range(4):
                    put("drums", toms[k], t0 + 3 * beat + k * beat / 4, 0.8)
            if "snare_roll" in L and b >= sec.bars - 4:
                steps = [4, 8, 16, 16][b - (sec.bars - 4)]
                for k in range(steps):
                    p = (b - (sec.bars - 4) + k / steps) / 4
                    put("drums", sn_s, t0 + k * bar / steps, (0.15 + 0.45 * p) if hard else (0.2 + 0.6 * p))
            if "crash" in L and b % 8 == 0:
                put("fx", crash(rng), t0, 1.0)
                if b == 0:
                    put("fx", impact(rng), t0, 0.9)
            if "riser" in L and b == sec.bars - 2:
                put("fx", riser(rng, bar * 2), t0, 1.0)
            bar_i += 1
        if sec.gap:
            end = bar_i * bar
            gaps.append((end - beat / 2, end))

    # ドロップ直前の一瞬の無音（ライザーだけ残す）
    for g0, g1 in gaps:
        i, j = int(g0 * SR), int(g1 * SR)
        fade = np.linspace(1, 0, 400)
        for k in ("drums", "bass", "music", "lead"):
            bus[k][i:i + 400] *= fade
            bus[k][i + 400:j] = 0
        kick_env[i:j] = 0

    # 最後のジャーン
    end_t = total_bars * bar
    n = int(tail * SR)
    s = np.zeros(n)
    for m in [57 + key, 60 + key, 64 + key, 69 + key]:
        s += supersaw(m, tail, rng=rng)
    put("music", lowpass(s, 1500) * adsr(n, 0.01, 0.5, 0.5, 1.8), end_t, 0.08)
    put("fx", impact(rng), end_t, 0.8)
    put("fx", crash(rng), end_t, 0.8)

    # サイドチェイン（キックに合わせてポンピング）
    duck = 1 - 0.65 * kick_env
    bus["bass"] *= duck
    bus["music"] *= 1 - 0.45 * kick_env
    bus["lead"] *= 1 - 0.25 * kick_env

    mix = bus["drums"] + bus["bass"] + bus["music"] + bus["lead"] + bus["fx"]

    # リバーブ（減衰ノイズとの畳み込み）をステレオで
    ir_n = int(2.2 * SR)
    t = np.arange(ir_n) / SR
    wet_src = bus["music"] + bus["lead"] * 1.3 + bus["fx"] + bus["drums"] * 0.15
    wet_src = highpass(wet_src, 250)
    nfft = 1 << (N + ir_n).bit_length()
    W = np.fft.rfft(wet_src, nfft)
    chans = []
    for ch in range(2):
        ir = rng.standard_normal(ir_n) * np.exp(-t * 2.6)
        ir = lowpass(ir, 6000)
        ir /= np.sqrt(np.sum(ir ** 2))
        wet = np.fft.irfft(W * np.fft.rfft(ir, nfft), nfft)[:N]
        # ステレオの広がり
        dry = mix + (bus["lead"] + bus["music"]) * (0.08 if ch == 0 else -0.08)
        chans.append(dry + wet * 0.22)
    st = np.stack(chans, axis=1)

    # マスター：ソフトクリップ＋ノーマライズ
    st /= np.percentile(np.abs(st), 99.9) + 1e-9
    st = np.tanh(st * 1.1) * 0.92
    fade = int(0.05 * SR)
    st[:fade] *= np.linspace(0, 1, fade)[:, None]
    st[-int(1.0 * SR):] *= np.linspace(1, 0, int(1.0 * SR))[:, None] ** 2

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wav = out_path.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())
    if out_path.suffix.lower() != ".wav":
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "256k",
                        "-metadata", f"title={title}", str(out_path)], check=True)
        wav.unlink()
    # 映像側がドロップの瞬間を正確に知れるよう、セクションの開始時刻を保存
    out_path.with_suffix(".sections.json").write_text(
        json.dumps({"bpm": bpm, "style": style, "sections": timeline}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_path
