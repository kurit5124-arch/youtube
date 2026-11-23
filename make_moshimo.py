#!/usr/bin/env python3
"""もしもシリーズの動画（横長・アニメーション付き）を作る。

使い方:
  python make_moshimo.py moshimo/episodes/ep01_nemuranai.yaml
  python make_moshimo.py moshimo/episodes/ep01_nemuranai.yaml --preview 0 40   # 0〜40秒だけ（確認用）

自分の声を使うときは voice/<エピソード名>/01.mp3, 02.mp3 … を置く（番号＝beats の順番）。
無い行は音声合成の仮の声になります。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from moshimo import build


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", help="moshimo/episodes/*.yaml")
    ap.add_argument("--out", default="output/moshimo", help="出力フォルダ")
    ap.add_argument("--preview", nargs=2, type=float, metavar=("開始秒", "終了秒"), help="一部だけ作る")
    args = ap.parse_args()
    ep = Path(args.episode)
    suffix = f"_preview{int(args.preview[0])}-{int(args.preview[1])}" if args.preview else ""
    out = Path(args.out) / f"{ep.stem}{suffix}.mp4"
    build.build(ep, out, Path(args.out) / "work" / ep.stem, tuple(args.preview) if args.preview else None)
    print(f"[done] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
