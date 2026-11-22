"""メロディとコードをトークン（単語のような番号）に変換する。

8小節の区間 = [BOS] + 小節ごとに [CHORD_x] + 音ごとに [POS_p, PITCH_m, DUR_d] + [EOS]
  - CHORD : 根音(0-11) × 長/短 の 24 種類（白鍵の音階に移調済み）
  - POS   : 小節内の位置（16分 0〜15）
  - PITCH : 音の高さ（MIDI 55〜86 に折りたたむ）
  - DUR   : 長さ（16分 1〜16）
"""
from __future__ import annotations

PITCH_LO, PITCH_HI = 55, 86

VOCAB = ["PAD", "BOS", "EOS"]
VOCAB += [f"CH_{r}{q}" for r in range(12) for q in ("M", "m")]
VOCAB += [f"POS_{p}" for p in range(16)]
VOCAB += [f"P_{m}" for m in range(PITCH_LO, PITCH_HI + 1)]
VOCAB += [f"D_{d}" for d in range(1, 17)]
IDX = {t: i for i, t in enumerate(VOCAB)}


def fold(p: int) -> int:
    while p < PITCH_LO:
        p += 12
    while p > PITCH_HI:
        p -= 12
    return p


def encode_segment(chords, notes) -> list[int]:
    """chords: 8個の (root, 'M'|'m')、notes: (16分の位置[0..127], 長さ, MIDI)"""
    seq = [IDX["BOS"]]
    for bar in range(8):
        r, q = chords[bar]
        seq.append(IDX[f"CH_{r % 12}{q}"])
        for pos, d, p in notes:
            if bar * 16 <= pos < bar * 16 + 16:
                seq += [IDX[f"POS_{pos - bar * 16}"], IDX[f"P_{fold(p)}"], IDX[f"D_{max(1, min(16, d))}"]]
    seq.append(IDX["EOS"])
    return seq


def decode(seq: list[int]):
    """トークン列 → (chords[8], notes[(beat_pos, beat_len, midi)])"""
    chords, notes = [], []
    bar = -1
    i = 0
    toks = [VOCAB[t] for t in seq]
    while i < len(toks):
        t = toks[i]
        if t.startswith("CH_"):
            bar += 1
            body = t[3:]
            chords.append((int(body[:-1]), body[-1]))
        elif t.startswith("POS_") and i + 2 < len(toks) and toks[i + 1].startswith("P_") and toks[i + 2].startswith("D_"):
            pos = int(t[4:])
            p = int(toks[i + 1][2:])
            d = int(toks[i + 2][2:])
            notes.append(((bar * 16 + pos) / 4, d / 4, p))
            i += 2
        elif t == "EOS":
            break
        i += 1
    return chords, notes
