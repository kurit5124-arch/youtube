#!/usr/bin/env python3
"""EDM の MIDI からメロディとコードを取り出し、学習用のトークン列にする。

  python ml/prepare.py --data /path/to/data   # data/midi/... と data/train.json（MidiCaps）を使う

1曲ごとに:
  1. キー（MidiCaps の注釈）を使って、マイナーは A マイナー、メジャーは C メジャーに移調（どちらも白鍵の音階）
  2. 小節ごとに全パートの音からコード（三和音）を推定
  3. 一番高い音を担当するパートからメロディを取り出し、16分音符の格子にそろえる
  4. 8小節ずつ切り出してトークン列にする
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tokens import encode_segment  # noqa: E402

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
        "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
TEMPLATES = {}
for root in range(12):
    TEMPLATES[(root, "M")] = {root, (root + 4) % 12, (root + 7) % 12}
    TEMPLATES[(root, "m")] = {root, (root + 3) % 12, (root + 7) % 12}


def read_notes(path: Path):
    """(tracks: list[list[(start_beat, end_beat, pitch)]], drum_present)"""
    mf = mido.MidiFile(str(path))
    tpb = mf.ticks_per_beat
    tracks = {}
    for ti, tr in enumerate(mf.tracks):
        t = 0
        on = {}
        for msg in tr:
            t += msg.time
            if msg.type not in ("note_on", "note_off"):
                continue
            if msg.channel == 9:
                continue
            key = (msg.channel, msg.note)
            if msg.type == "note_on" and msg.velocity > 0:
                on[key] = t
            elif key in on:
                st = on.pop(key)
                tracks.setdefault((ti, msg.channel), []).append((st / tpb, t / tpb, msg.note))
    return [sorted(v) for v in tracks.values() if len(v) >= 16]


def chord_of_bar(notes_in_bar) -> tuple[int, str] | None:
    if not notes_in_bar:
        return None
    w = np.zeros(12)
    low = min(p for _, _, p in notes_in_bar)
    for s, e, p in notes_in_bar:
        w[p % 12] += (e - s) * (2.0 if p == low else 1.0)
    best, score = None, -1
    for k, pcs in TEMPLATES.items():
        sc = sum(w[i] for i in pcs) + 0.5 * w[k[0]]
        if sc > score:
            best, score = k, sc
    return best


def melody_track(tracks):
    best, score = None, -1e9
    for tr in tracks:
        pitches = np.array([p for _, _, p in tr])
        onsets = np.array([s for s, _, _ in tr])
        mono = 1 - np.mean(np.diff(onsets) < 1e-3) if len(onsets) > 1 else 0
        mean = pitches.mean()
        if not (55 <= mean <= 90) or len(tr) < 32:
            continue
        sc = mean + 30 * mono
        if sc > score:
            best, score = tr, sc
    return best


def process(args):
    path, key = args
    try:
        tracks = read_notes(path)
    except Exception:
        return []
    if not tracks:
        return []
    tonic, mode = key.split()
    shift = (9 - NOTE[tonic]) if mode == "minor" else (0 - NOTE[tonic])
    shift = (shift + 6) % 12 - 6  # -6..5
    tracks = [[(s, e, p + shift) for s, e, p in tr] for tr in tracks]
    mel = melody_track(tracks)
    if mel is None:
        return []
    end = max(e for tr in tracks for _, e, _ in tr)
    nbars = int(end // 4)
    allnotes = [n for tr in tracks for n in tr]
    chords = []
    for b in range(nbars):
        inb = [(max(s, 4 * b), min(e, 4 * b + 4), p) for s, e, p in allnotes if s < 4 * b + 4 and e > 4 * b]
        chords.append(chord_of_bar(inb))
    # 16分の格子にそろえ、同時に鳴る音は一番高い音だけ（スカイライン）
    grid = {}
    for s, e, p in mel:
        q = int(round(s * 4))
        d = max(1, int(round((e - s) * 4)))
        if q not in grid or p > grid[q][0]:
            grid[q] = (p, d)
    segs = []
    for b0 in range(0, nbars - 7, 4):
        notes = []
        for q in range(b0 * 16, (b0 + 8) * 16):
            if q in grid:
                p, d = grid[q]
                notes.append((q - b0 * 16, min(d, 16), p))
        if len(notes) < 16:  # メロディが少なすぎる区間は使わない
            continue
        ch = chords[b0:b0 + 8]
        if any(c is None for c in ch):
            continue
        segs.append(encode_segment(ch, notes))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("/home/user/data"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    meta = {}
    for line in open(a.data / "train.json"):
        r = json.loads(line)
        meta[r["location"]] = r["key"]
    files = json.load(open(a.data / "edm_files.json"))
    jobs = [(a.data / "midi" / f, meta[f]) for f in files if (a.data / "midi" / f).exists()]
    print(f"{len(jobs)} 曲を処理します")
    out = []
    with mp.Pool() as pool:
        for i, segs in enumerate(pool.imap_unordered(process, jobs, chunksize=16)):
            out.extend(segs)
            if i % 1000 == 0:
                print(f"  {i}/{len(jobs)} 曲  区間 {len(out)}", flush=True)
    dest = a.out or (a.data / "segments.json")
    json.dump(out, open(dest, "w"))
    print(f"[done] {len(out)} 区間 → {dest}")


if __name__ == "__main__":
    main()
