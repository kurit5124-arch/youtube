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
from .future import _master, big_clap, future_chord, kick_clean, reverse_swell, saw_var, shaker, vocal_chop
from .vocals import render_lyrics

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


SECTIONS = [("intro", 4), ("verse", 8), ("build", 4), ("chorus", 8), ("drop", 8),
            ("verse2", 8), ("build2", 4), ("chorus2", 8), ("drop2", 8), ("outro", 4)]


def compose_walker(out_path: Path, seed: int = 7, bpm: float | None = None, title: str = "SNOWLIGHT",
                   key: int = -2, length: str = "long", voice: str = "en-US-AriaNeural") -> Path:
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
                put("keys", piano(root - 12, bar * 1.1), t0, 0.16, send=0.5)
                arp = [tones[0] + 12, tones[1] + 12, tones[2] + 12, tones[0] + 24]
                pat = [0, 1, 2, 3, 2, 1, 2, 1]
                for k in range(8):
                    put("keys", piano(arp[pat[k]], beat * 0.9), t0 + k * beat / 2,
                        0.11 * (0.8 + 0.2 * (k % 2 == 0)) * rng.uniform(0.85, 1.05), pan=rng.uniform(-0.3, 0.3), send=0.55)

            # パッド
            if name not in ("intro",) or b >= 2:
                bright = {"chorus": 2200, "chorus2": 2600, "drop": 3000, "drop2": 3400}.get(name, 1100)
                s = future_chord([tones[0] + 12, tones[1] + 12, tones[2] + 12, tones[0] + 24], bar * 1.05, rng,
                                 bend=False, bright=bright)
                g = {"drop": 0.2, "drop2": 0.22, "chorus": 0.12, "chorus2": 0.13}.get(name, 0.1)
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
                put("drums", K, t0, 0.45)
                put("drums", K, t0 + 2.5 * beat, 0.35)
                for k in range(8):
                    put("drums", SH[k % 3], t0 + k * beat / 2 + rng.normal(0, 0.003), 0.5 * rng.uniform(0.8, 1.1), pan=-0.3)

            # ビルド
            if name in ("build", "build2"):
                steps = [4, 8, 16, 16][b]
                for k in range(steps):
                    p = (b + k / steps) / nb
                    put("drums", SN, t0 + k * bar / steps, 0.12 + 0.5 * p, send=0.3)
                for qd in range(4):
                    put("drums", K, t0 + qd * beat, 0.3 + 0.4 * p_sec)
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
            # 声っぽいシンセの「オー」を後ろに薄く
            for p, ln, m in tr([n for _, ns in CHORUS for n in ns]):
                if ln >= 1:
                    put("lead", vocal_chop(m - 12, ln * beat, None, "o"), sec_t + p * beat, 0.1, pan=-0.3, send=0.5)

    # ボーカル
    print("  ボーカルを合成中…")
    for st, lines, kind in vocal_parts:
        for t, seg in render_lyrics(lines, beat, voice=voice, transpose=key):
            g = 1.3 if kind == "verse" else 2.0
            put("vox", seg, st + t, g, send=0.35, dly=0.25 if kind != "verse" else 0.15)
            if kind != "verse":  # サビは声を重ねて厚く（少しずらして左右に）
                put("vox", seg, st + t + 0.018, g * 0.45, pan=0.6, send=0.3)
                put("vox", seg, st + t + 0.011, g * 0.45, pan=-0.6, send=0.3)
        if kind == "chorus2":  # 2回目のサビは3度下でハモる
            harm = [(w, [(p, ln, _third_below(m)) for p, ln, m in ns]) for w, ns in lines]
            for t, seg in render_lyrics(harm, beat, voice=voice, transpose=key):
                put("vox", seg, st + t + 0.007, 0.8, pan=0.35, send=0.4)
    # アウトロ：最後のフレーズをもう一度、遠くに
    out_t = [x["start"] for x in timeline if x["name"] == "outro"][0]
    last = [(w, [(p - 24, ln, m) for p, ln, m in ns]) for w, ns in CHORUS if ns[0][0] >= 24]
    for t, seg in render_lyrics(last, beat, voice=voice, transpose=key):
        put("vox", lowpass(seg, 3500), out_t + t, 0.7, send=0.8, dly=0.4)

    # ドロップ前の一瞬の無音
    for x in timeline:
        if x["name"] in ("drop", "drop2", "chorus", "chorus2"):
            i0, i1 = int((x["start"] - beat / 2) * SR), int(x["start"] * SR)
            for k in ("drums", "bass", "keys", "pad", "lead"):
                bus[k][i0:i1] *= np.linspace(1, 0, i1 - i0)[:, None] ** 3

    # ポンピング
    for k, d in (("pad", 1.0), ("bass", 1.0), ("lead", 0.35), ("keys", 0.4), ("vox", 0.12)):
        bus[k] *= (1 - d + d * pump)[:, None]

    # ボーカルの音作り：低音を切って、少しだけ歪ませて前に出す
    for ch in range(2):
        bus["vox"][:, ch] = np.tanh(highpass(bus["vox"][:, ch], 160) * 1.4) / 1.4

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
