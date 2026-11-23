"""Alan Walker「Faded」のような雰囲気の曲（メロディ・歌詞はオリジナル）＋女性ボーカル。

ジャンルの特徴として取り入れたもの:
  - 90 BPM、マイナーキー、i - VI - III - VII の切ない進行
  - ピアノのイントロとAメロ、冷たい空気感（風の音、深いリバーブ）
  - 歌のサビ → シンセのリードがメロディを奏でるドロップ、の流れ
  - 柔らかく伸びるノコギリ波のリード（音がなめらかにすべる）、強めのポンピング
構成: イントロ → Aメロ（歌）→ ビルド → サビ（歌）→ ドロップ → Aメロ2（歌）→ ビルド → サビ2（歌＋ハモり）→ ドロップ2 → アウトロ
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from .compose import SR, adsr, crash, hat, highpass, impact, lowpass, mtof, piano, riser, snare
from .future import _master, big_clap, future_chord, kick_clean, reverse_swell, saw_var, shaker
from .vocals import _phrases, render_lyrics

# A マイナー基準（あとで key で移調）
Am, F, C, G = (57, "m"), (53, "M"), (48, "M"), (55, "M")
PROG = [Am, F, C, G]
TRI = {"m": [0, 3, 7], "M": [0, 4, 7]}
A3, B3, C4, D4, E4, F4, G4, A4, B4, C5, D5, E5 = 57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74, 76

# 歌詞（オリジナル）とメロディ：(単語, [(拍位置, 長さ, 音)])。8小節 = 32拍
VERSE1 = [
    ("cold", [(0.5, .5, E4)]), ("lights", [(1, .5, E4)]), ("on", [(1.5, .5, D4)]), ("the", [(2, .5, C4)]),
    ("frozen", [(2.5, .5, D4), (3, .5, E4)]), ("sea", [(3.5, 2.5, C4)]),
    ("I", [(8.5, .5, E4)]), ("can", [(9, .5, E4)]), ("hear", [(9.5, 1, G4)]), ("you", [(10.5, .5, E4)]),
    ("calling", [(11, .5, D4), (11.5, .5, C4)]), ("me", [(12, 2.5, D4)]),
    ("through", [(16.5, .5, A4)]), ("the", [(17, .5, G4)]), ("dark", [(17.5, 1, E4)]), ("and", [(18.5, .5, D4)]),
    ("through", [(19, .5, C4)]), ("the", [(19.5, .5, D4)]), ("snow", [(20, 2.5, E4)]),
    ("every", [(24.5, .5, C4), (25, .5, D4)]), ("road", [(25.5, 1, E4)]), ("will", [(26.5, .5, D4)]),
    ("lead", [(27, .5, C4)]), ("me", [(27.5, .5, D4)]), ("home", [(28, 3, B3)]),
]
VERSE2_WORDS = [("stars", 1), ("burn", 1), ("out", 1), ("across", 2), ("the", 1), ("sky", 1),
                ("still", 1), ("I'm", 1), ("running", 2), ("through", 1), ("the", 1), ("night", 1),
                ("hold", 1), ("the", 1), ("echo", 2), ("of", 1), ("your", 1), ("voice", 1),
                ("every", 2), ("heartbeat", 2), ("is", 1), ("a", 1), ("choice", 1)]
CHORUS = [
    ("stay", [(0, 1.5, C5)]), ("with", [(1.5, .5, B4)]), ("me", [(2, 1, A4)]), ("tonight", [(3, 1, G4), (4, 3, A4)]),
    ("under", [(8, .5, C5), (8.5, .5, B4)]), ("the", [(9, .5, A4)]), ("falling", [(9.5, 1, G4), (10.5, .5, E4)]),
    ("light", [(11, 3, G4)]),
    ("if", [(16, .5, C5)]), ("the", [(16.5, .5, D5)]), ("stars", [(17, 1.5, E5)]), ("go", [(18.5, .5, D5)]),
    ("out", [(19, 3, C5)]),
    ("I", [(24, .5, G4)]), ("will", [(24.5, .5, A4)]), ("find", [(25, 1, C5)]), ("you", [(26, .5, B4)]),
    ("somehow", [(26.5, .5, A4), (27, 4, G4)]),
]
SCALE_PCS = [0, 2, 4, 5, 7, 9, 11]  # C メジャー＝A ナチュラルマイナー


def _verse2():
    """Aメロ2：Aメロ1と同じメロディに別の歌詞をのせる"""
    notes = [n for _, ns in VERSE1 for n in ns]
    out, k = [], 0
    for w, cnt in VERSE2_WORDS:
        out.append((w, notes[k:k + cnt]))
        k += cnt
    return out


def _third_below(m):
    """音階の中で3度下の音（ハモり）"""
    pcs = [p for p in range(m - 5, m) if p % 12 in SCALE_PCS]
    return pcs[-2] if len(pcs) >= 2 else m - 3


def _lead_rhythm(chorus):
    """サビのメロディをドロップ用のリードに：長い音を付点のリズムで刻む"""
    out = []
    for _, ns in chorus:
        for p, ln, m in ns:
            if ln >= 1.5:
                t, pat = p, [0.75, 0.75, 0.5]
                k = 0
                while t < p + ln - 0.01:
                    d = min(pat[k % 3], p + ln - t)
                    out.append((t, d, m))
                    t += d
                    k += 1
            else:
                out.append((p, ln, m))
    return out


def walker_lead(m, dur, prev=None):
    """柔らかく伸びるノコギリ波のリード（前の音からすべる）"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f1 = mtof(m)
    f0 = mtof(prev) if prev is not None else f1
    f = f1 + (f0 - f1) * np.exp(-t * 60)
    s = saw_var(f) + saw_var(f * 1.006, 0.3) + saw_var(f * 0.994, 0.6) + 0.4 * saw_var(f * 0.5, 0.1)
    dark, br = lowpass(s, 900), lowpass(s, 4200, reso=0.4)
    s = dark + (br - dark) * (0.55 + 0.45 * np.exp(-t * 6))
    return s / 3 * adsr(n, 0.008, 0.15, 0.75, 0.06)


def wind(rng, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = lowpass(highpass(rng.standard_normal(n), 300), 1800)
    return s * (0.5 + 0.5 * np.sin(2 * np.pi * t / 6.5)) * 0.05


def _plate_ir(rng, sec):
    """ボーカル用のプレート・リバーブ（明るすぎず、低音をにごらせない）"""
    n = int(sec * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t * 6.9 / sec)
    ir = lowpass(highpass(ir, 500), 7500)
    return ir / np.sqrt(np.sum(ir ** 2))


def _vocal_eq(x):
    """EDM のボーカル EQ：100Hz 以下カット、300Hz を少し下げ、3kHz と 10kHz 以上を持ち上げる"""
    out = np.zeros_like(x)
    n = x.shape[0]
    nfft = 1 << (n - 1).bit_length()
    f = np.fft.rfftfreq(nfft, 1 / SR)
    h = (f / 100) ** 4 / (1 + (f / 100) ** 4)
    db = -2.5 * np.exp(-np.log2(np.maximum(f, 1) / 300) ** 2 / 0.5)
    db += 2.0 * np.exp(-np.log2(np.maximum(f, 1) / 3200) ** 2 / 0.6)
    db += 3.0 / (1 + (10000 / np.maximum(f, 1)) ** 2)
    h = h * 10 ** (db / 20) / (1 + (f / 16000) ** 6)
    for ch in range(x.shape[1]):
        out[:, ch] = np.fft.irfft(np.fft.rfft(x[:, ch], nfft) * h, nfft)[:n]
    return out


def _duck_curve(env, depth=0.7):
    """声が鳴っている間は 1-depth まで下げ、止まると 0.35 秒かけて戻る"""
    hop = 441
    nb = len(env) // hop + 1
    e = np.zeros(nb * hop)
    e[: len(env)] = env
    e = e.reshape(nb, hop).max(axis=1)
    thr = np.percentile(e[e > 1e-4], 40) if np.any(e > 1e-4) else 1.0
    target = 1 - depth * np.clip(e / thr, 0, 1)
    g = np.ones(nb)
    v = 1.0
    for i in range(nb):
        c = 0.5 if target[i] < v else 0.03  # 下げるのは速く、戻すのはゆっくり
        v += (target[i] - v) * c
        g[i] = v
    return np.interp(np.arange(len(env)), np.arange(nb) * hop, g)


def _pingpong(x, d, fb=0.45):
    """左右に跳ねるこだま（だんだん暗く小さく）"""
    out = np.zeros_like(x)
    src = x.mean(axis=1)
    cur = src
    for k in range(1, 7):
        sh = np.zeros_like(src)
        sh[d * k:] = cur[:-d * k] if d * k < len(cur) else 0
        sh = lowpass(highpass(sh, 400), 5000 - 400 * k) * fb ** k
        out[:, k % 2] += sh
    return out


SECTIONS = [("intro", 4), ("verse", 8), ("build", 4), ("chorus", 8), ("drop", 8),
            ("verse2", 8), ("build2", 4), ("chorus2", 8), ("drop2", 8), ("outro", 4)]


def compose_walker(out_path: Path, seed: int = 7, bpm: float | None = None, title: str = "SNOWLIGHT",
                   key: int = -6, length: str = "long", voice: str = "en-US-JennyNeural",
                   stems: Path | None = None) -> Path:
    bpm = bpm or 90
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = beat * 4
    sections = SECTIONS
    total = sum(b for _, b in sections)
    tail = 4.0
    N = int((total * bar + tail) * SR)
    bus = {k: np.zeros((N, 2)) for k in ("drums", "bass", "keys", "pad", "lead", "vox", "fx", "verb", "delay")}
    pump = np.ones(N)

    def put(name, sig, t, gain=1.0, pan=0.0, send=0.0, dly=0.0):
        i = int(max(0, t) * SR)
        if i >= N:
            return
        if sig.ndim == 1:
            sig = np.stack([sig * np.sqrt(1 - pan), sig * np.sqrt(1 + pan)], 1)
        j = min(N, i + len(sig))
        bus[name][i:j] += sig[: j - i] * gain
        if send:
            bus["verb"][i:j] += sig[: j - i] * gain * send
        if dly:
            bus["delay"][i:j] += sig[: j - i] * gain * dly

    def duck(t, depth=0.7):
        i = int(t * SR)
        n = min(int(beat * SR), N - i)
        if n > 0:
            pump[i:i + n] = np.minimum(pump[i:i + n], 1 - depth * np.exp(-np.arange(n) / SR * 7))

    K, CL, SN = kick_clean(rng), big_clap(rng), snare(rng)
    HH = [hat(rng) for _ in range(4)]
    OH = hat(rng, True)
    SH = [shaker(rng) for _ in range(3)]

    prog = [(r + key, q) for r, q in PROG]
    tr = lambda notes: [(p, l, m + key) for p, l, m in notes]  # noqa: E731

    timeline = []
    vocal_parts = []  # (開始秒, 行, 声の種類)
    bar_i = 0
    for name, nb in sections:
        timeline.append({"name": name, "start": round(bar_i * bar, 3)})
        sec_t = bar_i * bar
        if name in ("verse", "verse2"):
            vocal_parts.append((sec_t, VERSE1 if name == "verse" else _verse2(), "verse"))
        if name in ("chorus", "chorus2"):
            vocal_parts.append((sec_t, CHORUS, name))
        for b in range(nb):
            t0 = bar_i * bar
            root, q = prog[b % 4]
            tones = [root + i for i in TRI[q]]
            p_sec = b / nb

            # 風の音（冷たい空気感）
            if name in ("intro", "verse", "verse2", "outro") and b % 2 == 0:
                put("fx", wind(rng, bar * 2), t0, 1.0, pan=rng.uniform(-0.5, 0.5))

            # ピアノ
            if name in ("intro", "verse", "verse2", "outro", "build", "build2"):
                # ペダルを踏んだまま弾くイメージ：音は小節の終わりまで響かせ、強弱はフレーズに合わせて山なりに
                swell = 0.55 + 0.25 * np.sin(np.pi * ((b % 4) + 0.5) / 4)
                kg = 1.5 if name in ("verse", "verse2") else 1.0  # 歌の合間でも音が痩せないように
                put("keys", piano(root - 12, bar + 0.3, 0.6), t0, 0.3 * kg, send=0.45)
                put("keys", piano(root - 24, bar + 0.3, 0.45), t0 + 0.012, 0.18 * kg, send=0.3)
                arp = [tones[0] + 12, tones[1] + 12, tones[2] + 12, tones[0] + 24]
                pat = [0, 1, 2, 3, 2, 1, 2, 1]
                for k in range(8):
                    m = arp[pat[k]]
                    at = t0 + k * beat / 2 + rng.normal(0, 0.006)  # 人が弾くような少しの揺れ
                    vel = float(np.clip(swell * (1.0 if k % 2 == 0 else 0.82) * rng.uniform(0.92, 1.05)
                                        + (0.08 if k == 0 else 0), 0.3, 0.95))
                    hold = bar - k * beat / 2 + 0.25  # 小節の終わりまで（ペダル）
                    put("keys", piano(m, hold, vel), at, 0.24 * kg, pan=(m - 66) / 30, send=0.5)

            # パッド
            if name not in ("intro",) or b >= 2:
                bright = {"chorus": 2200, "chorus2": 2600, "drop": 3000, "drop2": 3400}.get(name, 1100)
                s = future_chord([tones[0] + 12, tones[1] + 12, tones[2] + 12, tones[0] + 24], bar * 1.05, rng,
                                 bend=False, bright=bright)
                g = {"drop": 0.2, "drop2": 0.22, "chorus": 0.12, "chorus2": 0.13, "verse": 0.24, "verse2": 0.24}.get(name, 0.16)
                put("pad", s, t0, g, send=0.4)

            # ドラムとベース
            if name in ("chorus", "chorus2", "drop", "drop2"):
                full = name.startswith("drop")
                for qd in range(4):
                    put("drums", K, t0 + qd * beat, 0.95 if full else 0.7)
                    duck(t0 + qd * beat, 0.75 if full else 0.55)
                for qd in (1, 3):
                    put("drums", CL, t0 + qd * beat + rng.normal(0, 0.002), 0.75 if full else 0.55, send=0.45)
                for qd in range(4):
                    put("drums", OH, t0 + qd * beat + beat / 2, 0.45 if full else 0.3, pan=0.2)
                for k in range(16):
                    put("drums", SH[k % 3], t0 + k * beat / 4 + rng.normal(0, 0.003),
                        (0.8 if k % 2 else 0.45) * rng.uniform(0.8, 1.1), pan=-0.25)
                # ベース：根音を伸ばす（ポンピングで揺れる）
                n = int(bar * SR)
                tt = np.arange(n) / SR
                sub = np.sin(2 * np.pi * mtof(root - 24) * tt)
                sw = lowpass(saw_var(np.full(n, mtof(root - 12))) + saw_var(np.full(n, mtof(root - 12) * 1.005), 0.5), 400)
                put("bass", (sub * 0.7 + sw * 0.25) * adsr(n, 0.01, 0.1, 0.95, 0.05), t0, 0.55 if full else 0.4)
                if b % 4 == 3:  # 4小節ごとのフィル
                    for k in range(4):
                        put("drums", SN, t0 + 3 * beat + k * beat / 4, 0.25 + 0.15 * k, send=0.3)
                if b == 0:
                    put("fx", crash(rng), t0, 0.7, send=0.3)
                    if full:
                        put("fx", impact(rng), t0, 0.7)
            elif name in ("verse", "verse2") and b >= 4:
                put("drums", K, t0, 0.16)
                put("drums", K, t0 + 2.5 * beat, 0.12)
                for k in range(8):
                    put("drums", SH[k % 3], t0 + k * beat / 2 + rng.normal(0, 0.003), 0.5 * rng.uniform(0.8, 1.1), pan=-0.3)

            # ビルド
            if name in ("build", "build2"):
                steps = [4, 8, 16, 16][b]
                for k in range(steps):
                    p = (b + k / steps) / nb
                    put("drums", SN, t0 + k * bar / steps, 0.06 + 0.26 * p, send=0.3)
                for qd in range(4):
                    put("drums", K, t0 + qd * beat, 0.12 + 0.25 * p_sec)
                if b == nb - 2:
                    put("fx", riser(rng, bar * 2), t0, 0.8)
                if b == nb - 1:
                    rev = reverse_swell(np.concatenate([CL, np.zeros(int(0.5 * SR))]))
                    put("fx", rev, t0 + bar - len(rev) / SR, 0.6, send=0.8)
            bar_i += 1

        # ドロップのリード（サビのメロディを刻んだもの）
        if name in ("drop", "drop2"):
            prev = None
            for p, ln, m in tr(_lead_rhythm(CHORUS)):
                at = sec_t + p * beat
                put("lead", walker_lead(m, ln * beat * 0.98, prev), at, 0.3, send=0.35, dly=0.35)
                if name == "drop2":
                    put("lead", walker_lead(m + 12, ln * beat * 0.98, prev + 12 if prev else None), at, 0.12,
                        pan=0.3, send=0.4, dly=0.3)
                prev = m

    # ===== ボーカル（EDM の定番の作り方）=====
    print("  ボーカルを合成中…")
    vb = {k: np.zeros((N, 2)) for k in ("lead", "stack", "bgv", "chop")}
    vsend = np.zeros((N, 2))   # ボーカル専用の響き（プレート・リバーブ）へ
    vthrow = np.zeros((N, 2))  # ボーカル専用のこだま（ディレイ）へ

    def vput(group, seg, t, g, pan=0.0, send=0.0, throw=0.0):
        i = int(max(0, t) * SR)
        if i >= N or len(seg) == 0:
            return
        st2 = np.stack([seg * np.sqrt(1 - pan), seg * np.sqrt(1 + pan)], 1) * g
        j = min(N, i + len(st2))
        vb[group][i:j] += st2[: j - i]
        if send:
            vsend[i:j] += st2[: j - i] * send
        if throw:
            vthrow[i:j] += st2[: j - i] * throw

    ir_v = _plate_ir(rng, 2.4)
    others = [v for v in ("en-US-AriaNeural", "en-GB-SoniaNeural", "en-US-JennyNeural") if v != voice][:2]
    chorus_takes = {}
    for st, lines, kind in vocal_parts:
        chorus = kind != "verse"
        g = 0.8 if not chorus else 2.1
        lead = render_lyrics(lines, beat, voice=voice, transpose=key, vib_depth=0.05)
        for (t, seg), ph in zip(lead, _phrases(lines)):
            # Aメロは近く・控えめな響き、サビは広く
            vput("lead", seg, st + t, g, send=0.35 if not chorus else 0.5)
            # 行の最後の語だけ、こだまを大きく残す（ディレイ・スロー）
            k0 = int((ph[-1][1][0][0] * beat - t) * SR)
            tail = seg[max(0, k0):]
            i = int(max(0, st + t) * SR) + max(0, k0)
            j = min(N, i + len(tail))
            vthrow[i:j] += np.stack([tail, tail], 1)[: j - i] * g * 0.9
        if chorus:
            chorus_takes[kind] = (st, lead)
            # 逆再生の響きが、サビの最初の言葉に吸い込まれる
            t0_, seg0 = lead[0]
            n0 = int((lines[0][1][0][0] * beat - t0_) * SR)
            head = seg0[max(0, n0): max(0, n0) + int(0.5 * SR)]
            if len(head):
                wet = np.convolve(head, ir_v[: int(1.8 * SR)])[: int(2.0 * SR)]
                rev = wet[::-1] * np.linspace(0, 1, len(wet)) ** 2
                rev = highpass(rev, 300)
                rev /= np.max(np.abs(rev)) + 1e-9
                vput("bgv", rev * 0.18, st + lines[0][1][0][0] * beat - len(rev) / SR, 1.0, send=0.2)
            # 左右に別の歌い手を重ねる（ダブル）
            for v2, pan, sd in ((others[0], -0.6, 11), (others[1], 0.6, 23)):
                for t, seg in render_lyrics(lines, beat, voice=v2, transpose=key, vib_depth=0.04, seed=sd):
                    vput("stack", seg, st + t, g * 0.36, pan=pan, send=0.4)
            # 1オクターブ下の声で厚みを（小さく、真ん中に）
            low = [(w, [(p, ln, m - 12) for p, ln, m in ns]) for w, ns in lines]
            for t, seg in render_lyrics(low, beat, voice=voice, transpose=key, vib_depth=0.03, seed=31):
                vput("stack", lowpass(seg, 5000), st + t, g * 0.22, send=0.3)
            # 後ろで「オー」のコーラスがコードを支える
            for b in range(8):
                r, q = prog[b % 4]
                tones = sorted(((r + i - 57) % 12) + 57 for i in TRI[q])  # A3〜G#4 あたりの和音
                for vi, m in enumerate(tones):
                    for t, seg in render_lyrics([("oh", [(b * 4, 3.8, m - key)])], beat, voice=others[vi % 2],
                                                transpose=key, vib_depth=0.03, seed=100 + b * 3 + vi):
                        vput("bgv", lowpass(seg, 6000), st + t, 0.25, pan=(-0.7, 0.0, 0.7)[vi], send=0.9)
        if kind == "chorus2":  # 2回目のサビは3度下でハモる
            harm = [(w, [(p, ln, _third_below(m)) for p, ln, m in ns]) for w, ns in lines]
            for t, seg in render_lyrics(harm, beat, voice=others[0], transpose=key, vib_depth=0.04, seed=41):
                vput("stack", seg, st + t, 0.95, pan=0.3, send=0.45)
    # アウトロ：最後のフレーズをもう一度、遠くに
    out_t = [x["start"] for x in timeline if x["name"] == "outro"][0]
    last = [(w, [(p - 24, ln, m) for p, ln, m in ns]) for w, ns in CHORUS if ns[0][0] >= 24]
    for t, seg in render_lyrics(last, beat, voice=voice, transpose=key, seed=77, vib_depth=0.05):
        vput("lead", lowpass(seg, 3500), out_t + t, 0.6, send=0.9, throw=0.5)
    # ドロップ：直前のサビの歌声を細かく刻んで、楽器のように使う（ボーカルチョップ）
    gate_pat = [1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1]
    for x in timeline:
        if x["name"] in ("drop", "drop2"):
            src_kind = "chorus" if x["name"] == "drop" else "chorus2"
            if src_kind not in chorus_takes:
                continue
            cst, takes = chorus_takes[src_kind]
            for t, seg in takes:
                n = len(seg)
                tt = (np.arange(n) / SR + t)  # サビの頭からの秒
                step = np.floor(tt / (beat / 4)).astype(int) % 16
                gate = np.array(gate_pat)[step].astype(float)
                gate = np.convolve(gate, np.ones(220) / 220, mode="same")  # 5ミリ秒でなめらかに
                chop = highpass(lowpass(seg * gate, 7000), 250)
                vput("chop", chop, x["start"] + t, 1.6, pan=0.15, send=0.5, throw=0.3)

    # ポンピング
    for k, d in (("pad", 0.6), ("bass", 0.8), ("lead", 0.2)):
        bus[k] *= (1 - d + d * pump)[:, None]

    # ===== ボーカルの音作り =====
    # EQ：低音のノイズとこもりを削り、声のはっきりした所と空気感を持ち上げる
    for gname in ("lead", "stack", "bgv", "chop"):
        vb[gname] = _vocal_eq(vb[gname])
    # 声の大きさをそろえる（ゆっくりのコンプレッサー）
    dry = vb["lead"] + vb["stack"]
    lvl = np.sqrt(np.convolve((dry ** 2).mean(axis=1), np.ones(882) / 882, mode="same")) + 1e-7
    thr = np.percentile(lvl[lvl > 1e-4], 70) if np.any(lvl > 1e-4) else 1.0
    gain = np.where(lvl > thr, (lvl / thr) ** -0.3, 1.0)
    gain = np.convolve(gain, np.ones(13230) / 13230, mode="same")
    for gname in ("lead", "stack"):
        vb[gname] *= gain[:, None]
    # 響きとこだまは、声が鳴っている間は小さく、合間で大きく（ダッキング）
    lead_env = np.sqrt(np.convolve((vb["lead"] ** 2).mean(axis=1), np.ones(882) / 882, mode="same"))
    duck = _duck_curve(lead_env, depth=0.6)
    v_wet = np.zeros((N, 2))
    nfft = 1 << (N + len(ir_v)).bit_length()
    pre = int(0.04 * SR)  # 40ミリ秒あとから響き始める（声がにごらない）
    for ch in range(2):
        src = np.zeros(N)
        src[pre:] = (vsend[:, ch] + vb["bgv"][:, ch] * 0.5)[:-pre]
        ir = ir_v if ch == 0 else np.roll(ir_v, int(0.007 * SR))
        v_wet[:, ch] = np.fft.irfft(np.fft.rfft(src, nfft) * np.fft.rfft(ir, nfft), nfft)[:N]
    v_dly = _pingpong(vthrow + vsend * 0.3, int(beat * SR), fb=0.45)
    bus["vox"] = (vb["lead"] + vb["stack"] + vb["bgv"] + vb["chop"]
                  + (v_wet * 0.6 + v_dly * 0.85) * duck[:, None])

    # ディレイ（付点8分、左右交互）
    d = int(beat * 0.75 * SR)
    dl = np.zeros_like(bus["delay"])
    src = bus["delay"].copy()
    for k in range(1, 5):
        sh = np.zeros_like(src)
        sh[d * k:] = src[:-d * k] * (0.5 ** k)
        dl[:, k % 2] += lowpass(sh[:, k % 2], 4500)
    # リバーブ（深め）
    ir_n = int(3.4 * SR)
    t = np.arange(ir_n) / SR
    nfft = 1 << (N + ir_n).bit_length()
    wet = np.zeros_like(bus["verb"])
    for ch in range(2):
        ir = rng.standard_normal(ir_n) * np.exp(-t * 1.8)
        ir = lowpass(highpass(ir, 350), 6500)
        ir /= np.sqrt(np.sum(ir ** 2))
        wet[:, ch] = np.fft.irfft(np.fft.rfft(bus["verb"][:, ch] + dl[:, ch] * 0.5, nfft) * np.fft.rfft(ir, nfft), nfft)[:N]

    mix = sum(bus[k] for k in ("drums", "bass", "keys", "pad", "lead", "vox", "fx")) + dl * 0.35 + wet * 0.4
    if stems:  # パートごとの音（確認・ミックス用）
        np.savez_compressed(stems, **{k: bus[k].astype(np.float32) for k in ("drums", "bass", "keys", "pad", "lead", "vox", "fx")},
                            delay=(dl * 0.35).astype(np.float32), reverb=(wet * 0.4).astype(np.float32))
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
    timeline_out = [dict(x, name=("drop" if x["name"] == "drop" else "drop2" if x["name"] == "drop2" else x["name"]))
                    for x in timeline]
    out_path.with_suffix(".sections.json").write_text(json.dumps(
        {"bpm": bpm, "style": "walker", "sections": timeline_out}, indent=1), encoding="utf-8")
    return out_path
