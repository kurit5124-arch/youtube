"""明るくてエモいフューチャーベース系 EDM（マシュメロのような雰囲気）を作曲・合成する。

特定の曲は真似せず、ジャンルの特徴を取り入れている:
  - メジャーキー、7th/9th の入った「エモい」コード、王道進行（IV-V-iii-vi）
  - 人が作るようなメロディ：ペンタトニック中心、1小節の動機をくり返して発展（問い→答え）、息つぎの休符
    （たくさん候補を作り、学習した AI に「本物の EDM らしさ」を採点させて一番自然なものを選ぶ）
  - ドロップは「ワウッ」と曲がって刻まれるコード＋声っぽいシンセ（ボーカルチョップ風）＋ベル系リード
  - ハーフタイムのドラム、残響の厚いクラップ、ハイハットの連打、指パッチン、シェイカー、人間らしい揺れ
  - 静かなAメロ → 盛り上がるサビ前 → ドロップ → ピアノの泣きのブレイク → さらに大きいラストドロップ
"""
from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

from .compose import SR, adsr, clap, crash, hat, highpass, impact, kick, lowpass, mtof, piano, riser, snare

# ---------------------------------------------------------------- 和音

QUAL = {"M7": [0, 4, 7, 11], "add9": [0, 4, 7, 14], "m7": [0, 3, 7, 10], "m9": [0, 3, 7, 10, 14], "M": [0, 4, 7]}
C, D, E, F, G, A = 48, 50, 52, 53, 55, 57  # C メジャー（あとで key で移調）
VERSE = [(A, "m7"), (F, "M7"), (C, "add9"), (G, "add9")]            # vi IV I V
DROP = [(F, "M7"), (G, "add9"), (E, "m7"), (A, "m9")]               # IV V iii vi（王道進行）
PRE = [(F, "M7"), (G, "add9"), (E, "m7"), (A, "m7"), (D, "m7"), (E, "m7"), (F, "M7"), (G, "add9")]
PENTA = [0, 2, 4, 7, 9]


def triad(ch):
    r, q = ch
    return (r % 12, "m" if 3 in QUAL[q] and 4 not in QUAL[q] else "M")


def chord_pcs(ch, tensions=True):
    r, q = ch
    ivs = QUAL[q] if tensions else QUAL[q][:3]
    return {(r + i) % 12 for i in ivs}


# ---------------------------------------------------------------- 音源

def saw_var(freq: np.ndarray, phase0=0.0) -> np.ndarray:
    ph = (phase0 + np.cumsum(freq) / SR) % 1.0
    dt = np.clip(freq / SR, 1e-6, 0.5)
    s = 2 * ph - 1
    a = ph < dt
    x = ph[a] / dt[a]
    s[a] -= x + x - x * x - 1
    b = ph > 1 - dt
    x = (ph[b] - 1) / dt[b]
    s[b] -= x * x + x + x + 1
    return s


def future_chord(notes, dur, rng, bend=True, bright=6500):
    """ワウッと音程が上がって入る、左右に広いスーパーソウの和音 → (n, 2)"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    env_bend = 2 ** ((-0.7 * np.exp(-t * 22)) / 12) if bend else np.ones(n)
    out = np.zeros((n, 2))
    for m in notes:
        f = mtof(m)
        for ch in range(2):
            for d in (-0.14, -0.05, 0.06, 0.15):
                dd = d * (1 if ch == 0 else -1) + rng.normal(0, 0.01)
                out[:, ch] += saw_var(f * 2 ** (dd / 12) * env_bend, rng.random())
    out /= np.sqrt(len(notes) * 4)
    for ch in range(2):
        dark, br = lowpass(out[:, ch], 900), lowpass(out[:, ch], bright, reso=0.3)
        fe = np.exp(-t * 7)
        out[:, ch] = dark + (br - dark) * (0.35 + 0.65 * fe)
    return out * adsr(n, 0.006, 0.18, 0.75, 0.04)[:, None]


FORMANTS = {"a": (800, 1150, 2900), "o": (450, 800, 2830), "e": (400, 2000, 2550), "u": (325, 700, 2530)}


def formant(x, vowel):
    n = len(x)
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    fr = np.fft.rfftfreq(nfft, 1 / SR)
    h = np.full_like(fr, 0.08)
    for k, f0 in enumerate(FORMANTS[vowel]):
        bw = 90 + 60 * k
        h += (1.0 / (k + 1) ** 0.6) * np.exp(-((fr - f0) ** 2) / (2 * bw ** 2))
    return np.fft.irfft(X * h, nfft)[:n]


def vocal_chop(m, dur, prev=None, vowel="a"):
    """声っぽいシンセ（前の音からなめらかにすべる）"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f1 = mtof(m)
    f0 = mtof(prev) if prev is not None else f1
    glide = f1 + (f0 - f1) * np.exp(-t * 45)
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.clip((t - 0.15) * 4, 0, 1)
    src = saw_var(glide * vib) + 0.5 * saw_var(glide * vib * 1.003, 0.3)
    s = formant(src, vowel) * 3.0
    return s * adsr(n, 0.01, 0.1, 0.85, 0.05)


def bell(m, dur):
    """明るいベル（マレット）系のリード"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = mtof(m)
    s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2.0 * f * t) * np.exp(-t * 6)
         + 0.25 * np.sin(2 * np.pi * 3.01 * f * t) * np.exp(-t * 10))
    return s * np.exp(-t * 3.2) * adsr(n, 0.002, 0.0, 1.0, 0.03)


def pluck(m, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    raw = saw_var(np.full(n, mtof(m))) + 0.6 * saw_var(np.full(n, mtof(m) * 1.004), 0.4)
    dark, br = lowpass(raw, 500), lowpass(raw, 4200, reso=0.6)
    return (dark + (br - dark) * np.exp(-t * 18)) * np.exp(-t * 4) * adsr(n, 0.002, 0, 1, 0.02)


def bass808(m, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = mtof(m) * (1 + 0.5 * np.exp(-t * 40))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR)
    s = np.tanh(s * 1.6) * adsr(n, 0.003, 0.3, 0.75, 0.06)
    return s


def kick_clean(rng):
    k = kick(rng)
    return np.tanh(k * 1.4) * 0.95


def snap(rng):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    s = lowpass(highpass(rng.standard_normal(n), 1800), 4500)
    return s * np.exp(-t * 55) * 0.5


def shaker(rng):
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    s = highpass(rng.standard_normal(n), 6000)
    env = np.minimum(t / 0.012, 1) * np.exp(-t * 45)
    return s * env * 0.12


def big_clap(rng):
    c = clap(rng)
    sn = snare(rng)
    out = sn * 0.6
    out[: len(c)] += c * 1.1
    return np.tanh(out * 1.3) * 0.85


def reverse_swell(sig):
    return sig[::-1] * np.linspace(0, 1, len(sig)) ** 2


# ---------------------------------------------------------------- メロディ（人の作曲のやり方）

RHYTHMS = [  # 1小節の動機（16分の位置, 長さ）
    [(0, 2), (3, 3), (6, 2), (8, 2), (10, 2), (12, 4)],
    [(0, 3), (3, 3), (6, 4), (10, 2), (12, 2), (14, 2)],
    [(2, 2), (4, 2), (6, 2), (8, 3), (11, 5)],
    [(0, 2), (2, 2), (4, 4), (10, 2), (12, 4)],
    [(0, 3), (3, 3), (6, 2), (8, 2), (11, 3), (14, 2)],
    [(0, 2), (2, 1), (3, 3), (6, 2), (8, 4), (12, 2), (14, 2)],
]
ANSWERS = [  # 問いに答えて伸ばす小節
    [(0, 2), (3, 3), (6, 10)],
    [(0, 3), (3, 3), (6, 2), (8, 8)],
    [(0, 2), (2, 2), (4, 12)],
    [(0, 2), (2, 2), (4, 2), (6, 10)],
]


def _snap(target, pcs, lo, hi):
    cands = [m for m in range(lo, hi + 1) if m % 12 in pcs]
    return min(cands, key=lambda m: (abs(m - target), m))


def _penta(deg, base=60):
    return base + 12 * (deg // 5) + PENTA[deg % 5]


def make_hook(rng, chords, lo=67, hi=84):
    """8小節のフック：A(動機+答え) → A'(同じ形をコードに合わせてずらす) → A(くり返し) → B(山場→着地)"""
    R = RHYTHMS[int(rng.integers(len(RHYTHMS)))]
    Q = ANSWERS[int(rng.integers(len(ANSWERS)))]
    Q2 = ANSWERS[int(rng.integers(len(ANSWERS)))]
    # 動機の音の動き（ペンタトニックの段）：前半は上がって後半は下がる山型が基本
    k = len(R)
    shape = [0]
    for i in range(1, k):
        up = i < k * 0.6
        step = int(rng.choice([1, 1, 2, 0, -1] if up else [-1, -1, -2, 0, 1]))
        shape.append(shape[-1] + step)
    ans_shape = [0] + [int(rng.choice([-1, 0, 1, -2])) for _ in range(len(Q) - 1)]
    start = int(rng.integers(7, 10))  # ペンタトニックの段（7≒G4〜A4あたり）

    notes = []

    def bar_notes(bar, rhythm, shp, deg0, final=False):
        ch = chords[bar % len(chords)]
        tones = chord_pcs(ch)
        penta_pcs = {p % 12 for p in PENTA} | chord_pcs(ch, tensions=False)
        prev = notes[-1][2] if notes else None
        for (pos, ln), d in zip(rhythm, shp):
            target = _penta(deg0 + d)
            strong = pos in (0, 8) or ln >= 4
            m = _snap(target, tones if strong else penta_pcs, lo, hi)
            if prev is not None and abs(m - prev) > 7:
                m = _snap(prev + np.sign(m - prev) * 4, tones if strong else penta_pcs, lo, hi)
            notes.append((bar * 4 + pos / 4, ln / 4, m))
            prev = m
        if final:  # 最後は和音の根音か3度に着地
            p, ln, m = notes[-1]
            r = ch[0] % 12
            notes[-1] = (p, ln, _snap(m, {r, (r + QUAL[ch[1]][1]) % 12}, lo, hi))

    bar_notes(0, R, shape, start)
    bar_notes(1, Q, [shape[-1] + s for s in ans_shape], start)
    bar_notes(2, R, shape, start - 1)          # 同じ形を少し下げて（コードに合わせて）くり返す
    bar_notes(3, Q2, [shape[-1] - 1 + s for s in ans_shape], start - 1, final=True)
    first4 = list(notes)
    for p, ln, m in first4[: len(R) + len(Q)]:  # 5〜6小節目は1〜2小節目をそのままくり返す（覚えやすさ）
        notes.append((p + 16, ln, m))
    bar_notes(6, R, [s + 2 for s in shape], start)  # 7小節目で一番高く（山場）
    bar_notes(7, [(0, 2), (2, 2), (4, 12)], [3, 2, 0], start, final=True)
    return notes


def adapt(notes, chords, shift=0, lo=55, hi=84):
    """メロディを別のコード進行に合わせ直す（Aメロ用など）"""
    out = []
    for p, ln, m in notes:
        ch = chords[int(p // 4) % len(chords)]
        pcs = chord_pcs(ch) if (p % 1 == 0 or ln >= 1) else ({x % 12 for x in PENTA} | chord_pcs(ch, False))
        out.append((p, ln, _snap(m + shift, pcs, lo, hi)))
    return out


def _check_in_key(notes, key):
    """メロディにキーの外の音（半音ずれた音）が混ざっていないか確かめる"""
    scale = {(x + key) % 12 for x in (0, 2, 4, 5, 7, 9, 11)}
    bad = [(p, m) for p, _, m in notes if m % 12 not in scale]
    if bad:
        raise ValueError(f"キーの外の音が混ざっています: {bad}")


def model_score(notes, chords, model=None):
    """学習した AI に、このメロディがどれだけ「本物の EDM らしいか」を採点させる（平均の対数確率）"""
    if model is None:
        return 0.0
    import torch
    from tokens import encode_segment
    seq = encode_segment([triad(c) for c in (chords * 2)[:8]],
                         [(int(round(p * 4)), int(round(ln * 4)), m) for p, ln, m in notes])
    x = torch.tensor([seq[:-1]])
    y = torch.tensor([seq[1:]])
    with torch.no_grad():
        lp = torch.log_softmax(model(x), -1)[0, torch.arange(y.shape[1]), y[0]]
    return float(lp.mean())


def load_model():
    path = Path(__file__).resolve().parent.parent / "ml" / "edm_gpt.pt"
    if not path.exists():
        return None
    try:
        import torch
        sys.path.insert(0, str(path.parent))
        from model import MusicGPT
        ck = torch.load(path, map_location="cpu")
        mdl = MusicGPT(**ck["config"])
        mdl.load_state_dict(ck["state"])
        mdl.eval()
        return mdl
    except Exception as e:  # torch が無くても動くように
        print(f"  (AI の採点は使いません: {e})")
        return None


def musical_score(h):
    """音楽的な良さ：音の動きの豊かさ、同じ音の連続の少なさ、ほどよい音域、なめらかさ"""
    ps = np.array([m for _, _, m in h])
    d = np.diff(ps)
    distinct = len(set(ps))
    rng_ = ps.max() - ps.min()
    repeats = np.sum(d == 0)
    zigzag = np.sum((d[:-1] * d[1:] < 0) & (np.abs(d[:-1]) <= 3) & (np.abs(d[1:]) <= 3))  # 行って戻るだけの動き
    steps = np.mean((np.abs(d) > 0) & (np.abs(d) <= 4))  # 隣の音へのなめらかな動き
    leaps = np.sum(np.abs(d) > 7)
    return (0.5 * min(distinct, 8) - 0.6 * repeats - 0.25 * zigzag + 2.0 * steps - 1.0 * leaps
            - 0.4 * max(0, rng_ - 14) - 0.4 * max(0, 8 - rng_))


def choose_hook(seed, chords, candidates=200):
    """候補をたくさん作り、①学習した AI で「EDM らしくない」ものを落とし、②音楽的に良いものを選ぶ"""
    rng = np.random.default_rng(seed)
    mdl = load_model()
    hooks = [make_hook(rng, chords) for _ in range(candidates)]
    if mdl is not None:
        ai = np.array([model_score(h, chords, mdl) for h in hooks])
        keep = ai >= np.percentile(ai, 60)  # AI の評価で上位 40% だけ残す
        hooks = [h for h, k in zip(hooks, keep) if k]
    best = max(hooks, key=musical_score)
    return best, mdl is not None


# ---------------------------------------------------------------- 曲

SECTIONS = [  # (名前, 小節数)
    ("intro", 4), ("verse", 8), ("pre", 8), ("drop", 16), ("break", 8), ("build", 8), ("drop2", 16), ("outro", 4),
]


def compose_future(out_path: Path, seed: int = 7, bpm: float | None = None, title: str = "AFTERGLOW",
                   key: int = -4, length: str = "long") -> Path:
    bpm = bpm or 140
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = beat * 4
    sections = SECTIONS if length == "long" else [("pre", 4), ("drop", 8), ("break", 4), ("drop2", 8), ("outro", 2)]
    total = sum(b for _, b in sections)
    tail = 3.0
    N = int((total * bar + tail) * SR)
    bus = {k: np.zeros((N, 2)) for k in ("drums", "bass", "chords", "lead", "fx", "verb")}
    pump = np.ones(N)

    hook, used_ai = choose_hook(seed, DROP)
    # Aメロ用：移調する前（C メジャーのまま）にコードへ合わせ直してから、まとめて移調する
    verse_mel = adapt([(p, ln, m - 12) for p, ln, m in hook if p < 16], VERSE, lo=52 - key, hi=72 - key)
    hook = [(p, ln, m + key) for p, ln, m in hook]
    verse_mel = [(p, ln, m + key) for p, ln, m in verse_mel]
    _check_in_key(hook + verse_mel, key)

    def put(name, sig, t, gain=1.0, pan=0.0, jitter=0.0, send=0.0):
        if jitter:
            t += rng.normal(0, jitter)
        i = int(max(0, t) * SR)
        if i >= N:
            return
        if sig.ndim == 1:
            lg, rg = np.sqrt(0.5 * (1 - pan)), np.sqrt(0.5 * (1 + pan))
            sig = np.stack([sig * lg * 1.414, sig * rg * 1.414], 1)
        j = min(N, i + len(sig))
        bus[name][i:j] += sig[: j - i] * gain
        if send:
            bus["verb"][i:j] += sig[: j - i] * gain * send

    def duck(t, depth, dur):
        i = int(t * SR)
        n = min(int(dur * SR), N - i)
        if n <= 0:
            return
        e = 1 - depth * np.exp(-np.arange(n) / SR * 9)
        pump[i:i + n] = np.minimum(pump[i:i + n], e)

    K = kick_clean(rng)
    CL = big_clap(rng)
    SN = snare(rng)
    HH = [hat(rng) for _ in range(4)]
    OH = hat(rng, True)
    SP = snap(rng)
    SH = [shaker(rng) for _ in range(3)]

    def chords_of(name):
        c = {"intro": VERSE, "verse": VERSE, "pre": PRE, "drop": DROP, "break": DROP, "build": PRE,
             "drop2": DROP, "outro": DROP}[name]
        return [(r + key, q) for r, q in c]

    def voicing(ch, lo=58, hi=79):
        r, q = ch
        vs = sorted({r + 12 + i for i in QUAL[q]} | {r + 24 + i for i in QUAL[q][:3]})
        vs = [v for v in vs if lo <= v <= hi] or [r + 12 + i for i in QUAL[q]]
        return vs

    timeline = []
    bar_i = 0
    for name, nb in sections:
        timeline.append({"name": name, "start": round(bar_i * bar, 3)})
        prog = chords_of(name)
        for b in range(nb):
            t0 = bar_i * bar
            ch = prog[b % len(prog)]
            root = ch[0]
            p_sec = b / nb
            last = b == nb - 1
            vo = voicing(ch)

            if name == "intro":
                s = future_chord(vo, bar, rng, bend=False, bright=1200)
                put("chords", s, t0, 0.4 * (0.5 + 0.5 * p_sec), send=0.5)
                if b == nb - 1:
                    put("fx", riser(rng, bar), t0, 0.6)

            if name in ("verse",):
                # ピアノのコード＋プラックのメロディ（静かに）
                for pos, ln in ((0, 1.5), (1.5, 1.5), (3, 1.0)):
                    for m in [root - 12] + vo[:4]:
                        put("chords", piano(m, ln * beat * 1.5), t0 + pos * beat, 0.09, pan=rng.uniform(-0.3, 0.3), send=0.3)
                pb = (b % 4) * 4
                for p, ln, m in verse_mel:
                    if pb <= p < pb + 4:
                        put("lead", pluck(m, ln * beat + 0.2), t0 + (p - pb) * beat, 0.22, send=0.35)
                # 軽いビート：キック1・3、指パッチン2・4、シェイカー
                for q in (0, 2):
                    put("drums", K, t0 + q * beat, 0.55)
                for q in (1, 3):
                    put("drums", SP, t0 + q * beat, 0.8, jitter=0.003, send=0.4)
                for k in range(16):
                    put("drums", SH[k % 3], t0 + k * beat / 4, (0.9 if k % 2 else 0.5) * rng.uniform(0.8, 1.1),
                        pan=0.3, jitter=0.003)
                put("bass", bass808(root - 12, beat * 3.5), t0, 0.35)

            if name in ("pre", "build"):
                # だんだん盛り上がる：コードが厚くなり、スネアが細かく、低音が抜けていく
                s = future_chord(vo, bar, rng, bend=False, bright=1500 + 4500 * p_sec)
                put("chords", s, t0, 0.18 + 0.12 * p_sec, send=0.4)
                arp = sorted(vo)
                for k in range(8):
                    m = arp[k % len(arp)] + (12 if k >= 4 and p_sec > 0.5 else 0)
                    put("lead", pluck(m, beat / 2), t0 + k * beat / 2, 0.16 + 0.1 * p_sec, pan=(-0.4 if k % 2 else 0.4), send=0.3)
                for q in range(4):
                    put("drums", K, t0 + q * beat, 0.5 + 0.35 * p_sec)
                steps = [4, 4, 8, 8, 16, 16, 32, 32][min(7, b * 8 // nb)]
                for k in range(steps):
                    p = (b + k / steps) / nb
                    ratio = 1 + 0.7 * p ** 2
                    sig = np.interp(np.arange(0, len(SN) - 1, ratio), np.arange(len(SN)), SN)
                    put("drums", sig, t0 + k * bar / steps, 0.12 + 0.5 * p, jitter=0.002, send=0.3)
                put("bass", bass808(root - 12, bar * 0.95), t0, 0.3 * (1 - p_sec))
                if b == nb - 2:
                    put("fx", riser(rng, bar * 2), t0, 0.9)
                if last:
                    rev = reverse_swell(np.concatenate([CL, np.zeros(int(0.4 * SR))]))
                    put("fx", rev, t0 + bar - len(rev) / SR, 0.7, send=0.8)

            if name in ("drop", "drop2"):
                big = name == "drop2"
                # フューチャーベースのコード（刻み）
                chop = [(0, 3), (3, 3), (6, 2), (8, 3), (11, 3), (14, 2)]
                for pos, ln in chop:
                    s = future_chord(vo + ([vo[0] - 12] if big else []), ln / 4 * beat * 1.1, rng, bend=pos in (0, 8))
                    put("chords", s, t0 + pos / 4 * beat, 0.32, send=0.25)
                # ボーカルチョップ風のリード＋ベル
                prev = None
                for p, ln, m in hook:
                    pb = (b % 8) * 4
                    if pb <= p < pb + 4:
                        at = t0 + (p - pb) * beat
                        vowel = "a" if int(p * 2) % 4 < 2 else "o"
                        put("lead", vocal_chop(m, ln * beat * 0.95, prev, vowel), at, 0.26, send=0.35)
                        put("lead", bell(m + 12, ln * beat + 0.3), at, 0.07 if not big else 0.11, pan=0.25, send=0.4)
                        if big:
                            put("lead", vocal_chop(m - 12, ln * beat * 0.95, None, "o"), at, 0.12, pan=-0.2, send=0.2)
                        prev = m
                # 808 ベース（ハーフタイム）
                for pos, ln in ((0, 1.5), (1.5, 1.0), (2.5, 1.5)):
                    put("bass", bass808(root - 12 if pos != 1.5 else root, ln * beat), t0 + pos * beat, 0.42)
                # ハーフタイムのドラム：キック 1・2&、クラップ 3
                for q in (0, 1.5) + ((2.75,) if b % 2 else ()):
                    put("drums", K, t0 + q * beat, 0.95)
                    duck(t0 + q * beat, 0.75, beat)
                put("drums", CL, t0 + 2 * beat, 0.85, send=0.55)
                duck(t0 + 2 * beat, 0.5, beat)
                for q in range(4):
                    duck(t0 + q * beat, 0.35, beat)
                # ハイハット 8分＋小節の終わりに連打（トラップロール）
                for k in range(8):
                    put("drums", HH[k % 4], t0 + k * beat / 2, (0.8 if k % 2 else 0.55) * rng.uniform(0.85, 1.1),
                        pan=0.2, jitter=0.002)
                if b % 2 == 1:
                    n_roll = 6 if b % 4 == 1 else 8
                    for k in range(n_roll):
                        put("drums", HH[k % 4], t0 + 3 * beat + k * beat / n_roll, 0.35 + 0.4 * k / n_roll, pan=0.2)
                if big:
                    for q in range(4):
                        put("drums", OH, t0 + q * beat + beat / 2, 0.35, pan=-0.2)
                if b % 8 == 0:
                    put("fx", crash(rng), t0, 0.9, send=0.3)
                    if b == 0:
                        put("fx", impact(rng), t0, 0.8)

            if name == "break":
                # 泣きのブレイク：ピアノとパッドだけ、フックをゆっくりピアノで
                for m in [root - 12, root] + vo:
                    put("chords", piano(m, bar * 1.2), t0, 0.09, send=0.6)
                s = future_chord(vo, bar, rng, bend=False, bright=900)
                put("chords", s, t0, 0.1 * (0.5 + p_sec), send=0.6)
                for p, ln, m in hook:
                    pb = (b % 8) * 4
                    if pb <= p < pb + 4:
                        put("lead", piano(m, ln * beat * 2), t0 + (p - pb) * beat, 0.16, send=0.6)
                if b >= nb - 2:
                    put("bass", bass808(root - 12, bar), t0, 0.2)

            if name == "outro":
                s = future_chord(vo, bar, rng, bend=False, bright=1400 - 250 * b)
                put("chords", s, t0, 0.2 * (1 - p_sec * 0.6), send=0.6)
                for p, ln, m in hook:
                    if b * 4 <= p < b * 4 + 4:
                        put("lead", bell(m + 12, ln * beat + 0.4), t0 + (p - b * 4) * beat, 0.1, send=0.7)
            bar_i += 1

    # 最後の余韻
    end = total * bar
    fin = [(F + key, "M7")]
    s = future_chord(voicing(fin[0]), tail, rng, bend=True, bright=3000)
    put("chords", s * np.linspace(1, 0, len(s))[:, None] ** 1.5, end, 0.25, send=0.8)

    # ドロップ前の一瞬の無音
    for nm, st in [(x["name"], x["start"]) for x in timeline]:
        if nm in ("drop", "drop2"):
            i0, i1 = int((st - beat / 2) * SR), int(st * SR)
            for k in ("drums", "bass", "chords", "lead"):
                bus[k][i0:i1] *= np.linspace(1, 0, i1 - i0)[:, None] ** 3

    # サイドチェイン（ポンピング）
    bus["chords"] *= pump[:, None]
    bus["bass"] *= (0.4 + 0.6 * pump)[:, None]
    bus["lead"] *= (0.75 + 0.25 * pump)[:, None]

    # ステレオのリバーブ
    ir_n = int(2.6 * SR)
    t = np.arange(ir_n) / SR
    src = bus["verb"]
    nfft = 1 << (N + ir_n).bit_length()
    wet = np.zeros_like(src)
    for ch in range(2):
        ir = rng.standard_normal(ir_n) * np.exp(-t * 2.3)
        ir = lowpass(highpass(ir, 300), 7000)
        ir /= np.sqrt(np.sum(ir ** 2))
        wet[:, ch] = np.fft.irfft(np.fft.rfft(src[:, ch], nfft) * np.fft.rfft(ir, nfft), nfft)[:N]

    mix = bus["drums"] + bus["bass"] + bus["chords"] + bus["lead"] + bus["fx"] + wet * 0.35
    mix = _master(mix)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wav = out_path.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    if out_path.suffix.lower() != ".wav":
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "256k",
                        "-metadata", f"title={title}", str(out_path)], check=True)
        wav.unlink()
    out_path.with_suffix(".sections.json").write_text(json.dumps(
        {"bpm": bpm, "style": "future", "sections": timeline, "melody_ranked_by_ai": used_ai}, indent=1), encoding="utf-8")
    return out_path


def _master(x: np.ndarray) -> np.ndarray:
    """音を潰さずに音量をそろえる（ゆるいコンプ＋先読みリミッター）"""
    x = x / (np.percentile(np.abs(x), 99.5) + 1e-9) * 0.5
    blk = 128
    nb = len(x) // blk + 1
    pad = np.zeros((nb * blk, 2))
    pad[: len(x)] = x
    peak = np.abs(pad).max(axis=1).reshape(nb, blk).max(axis=1)
    peak = np.maximum(peak, np.roll(peak, -1))  # 少し先読み
    ceil = 0.95
    target = np.minimum(1.0, ceil / (peak + 1e-9))
    g = np.ones(nb)
    v = 1.0
    rel = 1 - np.exp(-blk / (SR * 0.12))
    for i in range(nb):
        v = target[i] if target[i] < v else v + (target[i] - v) * rel
        g[i] = v
    gain = np.interp(np.arange(len(x)), np.arange(nb) * blk + blk / 2, g)
    y = x * gain[:, None]
    y = np.tanh(y * 1.05) / np.tanh(1.05)
    fade = int(0.03 * SR)
    y[:fade] *= np.linspace(0, 1, fade)[:, None]
    return y * 0.97
