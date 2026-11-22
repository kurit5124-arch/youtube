#!/usr/bin/env python3
"""学習した AI で新しいメロディとコード進行を作る。

  python ml/generate.py --out output/ai_song.json --seed 1

たくさん候補を作り、
  - 音の数がちょうどいいか
  - フックとして繰り返しがあるか（1〜2小節目と5〜6小節目が似ているか）
  - 強拍でコードの音を使っているか
  - 学習元の曲と長く一致していないか（パクりになっていないか）
で採点して、一番いいものを選ぶ。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import MusicGPT  # noqa: E402
from tokens import IDX, VOCAB, decode  # noqa: E402

CH = [i for i, t in enumerate(VOCAB) if t.startswith("CH_")]
POS = [i for i, t in enumerate(VOCAB) if t.startswith("POS_")]
PIT = [i for i, t in enumerate(VOCAB) if t.startswith("P_")]
DUR = [i for i, t in enumerate(VOCAB) if t.startswith("D_")]
NGRAM = 10  # これ以上の長さで学習元と一致したら「似すぎ」


def grammar(seq):
    """次に出してよいトークン（8小節・単音・位置は前に進むだけ）"""
    last = VOCAB[seq[-1]]
    bars = sum(1 for t in seq if VOCAB[t].startswith("CH_"))
    if last == "BOS":
        return CH
    if last.startswith("POS_"):
        return PIT
    if last.startswith("P_"):
        return DUR
    # 小節の頭か、音の長さのあと
    cur = -1
    end = 0
    for t in reversed(seq):
        v = VOCAB[t]
        if v.startswith("CH_"):
            break
        if v.startswith("POS_") and cur < 0:
            cur = int(v[4:])
    if last.startswith("D_") and cur >= 0:
        end = cur + 1
    ok = [IDX[f"POS_{p}"] for p in range(end, 16)]
    ok += CH if bars < 8 else [IDX["EOS"]]
    return ok


def melody_key(notes):
    """(音程の差, 次の音までの間隔) の並び（移調しても同じになる）"""
    out = []
    for a, b in zip(notes, notes[1:]):
        out.append((b[2] - a[2], round((b[0] - a[0]) * 4)))
    return out


def build_index(segments_path: Path):
    """学習元の全メロディの n 音の並び（n=6〜NGRAM）を集めておく"""
    idx = set()
    for s in json.load(open(segments_path)):
        _, notes = decode(s)
        k = melody_key(notes)
        for n in range(6, NGRAM + 1):
            for i in range(len(k) - n + 1):
                idx.add(hash(tuple(k[i:i + n])))
    return idx


def longest_match(notes, index):
    """学習元のどれかの曲と、何音ぶん同じ並びになっているか（6〜NGRAM で判定）"""
    k = melody_key(notes)
    best = 0
    for n in range(6, NGRAM + 1):
        if any(hash(tuple(k[i:i + n])) in index for i in range(len(k) - n + 1)):
            best = n
        else:
            break
    return best


def score(chords, notes):
    if len(chords) != 8 or not (14 <= len(notes) <= 44):
        return -1e9
    pitches = np.array([p for _, _, p in notes])
    if pitches.max() - pitches.min() > 19:
        return -1e9
    # 強拍（拍の頭）でコードの音を使っているか
    fit = []
    for pos, ln, p in notes:
        if pos % 1 == 0:
            r, q = chords[int(pos // 4)]
            pcs = {r % 12, (r + (4 if q == "M" else 3)) % 12, (r + 7) % 12}
            fit.append(p % 12 in pcs)
    fit = np.mean(fit) if fit else 0
    # フックの繰り返し：1〜2小節目と5〜6小節目のリズムと音程の似かた
    def part(b0):
        return {(round((pos - b0 * 4) * 4), p) for pos, _, p in notes if b0 * 4 <= pos < b0 * 4 + 8}
    a, b = part(0), part(4)
    rep = len(a & b) / max(1, len(a | b))
    # 音の動きの豊かさ（同じ音ばかりにならない）
    var = len(set(pitches)) / 8
    return 2.0 * fit + 2.0 * rep + min(var, 1.0) + 0.02 * len(notes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=Path(__file__).resolve().parent / "edm_gpt.pt")
    ap.add_argument("--segments", type=Path, default=Path("/home/user/data/segments.json"))
    ap.add_argument("--out", type=Path, default=Path("output/ai_song.json"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--candidates", type=int, default=48)
    ap.add_argument("--temperature", type=float, default=1.0)
    a = ap.parse_args()

    ck = torch.load(a.model, map_location="cpu")
    model = MusicGPT(**ck["config"])
    model.load_state_dict(ck["state"])
    torch.manual_seed(a.seed)
    index = build_index(a.segments) if a.segments.exists() else None

    prefix = [IDX["BOS"], IDX["CH_9m"]]  # A マイナーから始める
    cands = []
    for i in range(a.candidates):
        seq = model.sample(prefix, 400, temperature=a.temperature, top_k=12, allowed=grammar)
        chords, notes = decode(seq)
        sc = score(chords, notes)
        match = longest_match(notes, index) if index is not None else 0
        if match >= NGRAM:
            sc = -1e9  # 学習元と長く一致 → 使わない
        cands.append((sc, chords, notes, match))
    cands.sort(key=lambda c: -c[0])
    best = cands[0]
    if best[0] < -1e8:
        raise SystemExit("よい候補が出ませんでした。--candidates を増やしてください")
    # 2曲目のドロップ用：同じコード進行で別のメロディ
    alt = [c for c in cands[1:] if c[0] > -1e8]
    song = {
        "progression": [[int(r), q] for r, q in best[1]],
        "melodies": [best[2]] + [c[2] for c in alt[:2]],
        "progressions_alt": [[[int(r), q] for r, q in c[1]] for c in alt[:2]],
        "score": best[0],
        "rejected_as_too_similar": sum(1 for c in cands if c[3] >= NGRAM),
        "longest_match_with_training": best[3],
        "candidates": len(cands),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(song, open(a.out, "w"), indent=1)
    names = "C C# D D# E F F# G G# A A# B".split()
    print("コード:", " ".join(names[r % 12] + ("m" if q == "m" else "") for r, q in best[1]))
    print("メロディ:", " ".join(f"{names[p % 12]}{p // 12 - 1}" for _, _, p in best[2]))
    print(f"学習元との最長一致: {best[3]} 音の並び（{NGRAM} 以上は除外）")
    print(f"候補 {len(cands)} 個中、学習元に似すぎて除外: {song['rejected_as_too_similar']} 個 → {a.out}")


if __name__ == "__main__":
    main()
