#!/usr/bin/env python3
"""かっこいい曲を自動作曲し、イラストを音に合わせて動かしたミュージックビデオを作る。

使い方:
  python make_music_video.py                         # 作曲 → イラスト → 縦型MV（ショート向け）
  python make_music_video.py --seed 3                # 別の曲・別の景色にする
  python make_music_video.py --landscape             # 横型 1920x1080・約3分（通常動画向け）
  python make_music_video.py --title "MIDNIGHT RUN"  # タイトル文字を変える
  python make_music_video.py --audio song.mp3        # 手持ちの曲（Suno などで作った曲）を使う
  python make_music_video.py --image art.png         # 手持ちのイラスト（AIで描いた絵など）を動かす
  python make_music_video.py --preview 8             # 最初の8秒だけ作って確認
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from musicvideo.analyze import analyze
from musicvideo.compose import compose
from musicvideo.render import render_video
from musicvideo.thumbnail import make_thumbnails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", choices=["hard", "synthwave"], default="hard",
                    help="曲の雰囲気 hard=速くて激しいダークシンセ（既定） / synthwave=ゆったりめ")
    ap.add_argument("--title", help="画面に出す曲名（既定: hard は OVERDRIVE、synthwave は NEON DRIVE）")
    ap.add_argument("--subtitle", help="曲名の下の小さい文字")
    ap.add_argument("--seed", type=int, default=7, help="作曲と景色のパターン（数字を変えると別の曲に）")
    ap.add_argument("--bpm", type=float, help="テンポ（既定: hard=140, synthwave=128）")
    ap.add_argument("--length", choices=["short", "long"],
                    help="曲の長さ short=約1分 / long=約3分（既定: 縦型は short、横型は long）")
    ap.add_argument("--audio", type=Path, help="自分の曲を使う（mp3/wav）。省略すると自動作曲")
    ap.add_argument("--image", type=Path, help="自分のイラストを動かす。省略するとプログラムで描く")
    ap.add_argument("--landscape", action="store_true", help="横型 1920x1080 にする（既定は縦型 1080x1920）")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--preview", type=float, help="最初の N 秒だけ描画する（確認用）")
    ap.add_argument("--workers", type=int, help="並列数（既定: CPU 数）")
    ap.add_argument("--out", type=Path, default=Path("output"), help="出力フォルダ")
    args = ap.parse_args()
    genre = "DARKSYNTH" if args.style == "hard" else "SYNTHWAVE"
    args.title = args.title or ("OVERDRIVE" if args.style == "hard" else "NEON DRIVE")
    args.subtitle = args.subtitle or f"{genre}  ·  ORIGINAL TRACK"

    W, H = (1920, 1080) if args.landscape else (1080, 1920)
    slug = "".join(c if c.isalnum() else "_" for c in args.title.lower()).strip("_") or "music_video"
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if args.audio:
        audio = args.audio
        print(f"[1/3] 曲: {audio}")
    else:
        audio = args.out / f"{slug}{'_landscape' if args.landscape else ''}.mp3"
        length = args.length or ("long" if args.landscape else "short")
        print(f"[1/3] 作曲中…（{args.style}, seed={args.seed}, {length}）")
        compose(audio, seed=args.seed, bpm=args.bpm, title=args.title, length=length, style=args.style)
        print(f"      → {audio}")

    print("[2/3] 音を解析中…")
    feats = analyze(audio, fps=args.fps)

    kind = "image" if args.image else "neon"
    opts = dict(title=args.title, subtitle=args.subtitle, seed=args.seed)
    if args.image:
        opts["image"] = args.image
    suffix = "_landscape" if args.landscape else ""
    video = args.out / f"{slug}{suffix}.mp4"
    thumb = args.out / f"{slug}{suffix}_thumb.jpg"
    print(f"[3/3] 映像を描画中…（{W}x{H}, {args.fps}fps）")
    render_video(audio, feats, video, W, H, kind=kind, opts=opts, seconds=args.preview,
                 workers=args.workers, thumbnail=thumb)

    if not args.image:
        print("[+] サムネイルを作成中…（a/b/c の3種類）")
        bpm = f"{args.bpm or (140 if args.style == 'hard' else 128):g}"
        make_thumbnails(audio, args.title, args.out / f"{slug}{suffix}", genre=genre, bpm=bpm, seed=args.seed)

    meta = {
        "title": f"{args.title} | {genre.title()} Original Track",
        "description": (
            f"{args.title} — プログラムで自動作曲したオリジナルの{genre.title()}曲と、"
            "音に合わせて動くネオンのイラスト。\n\n#synthwave #darksynth #retrowave"
            + ("" if args.landscape else " #shorts")
        ),
        "tags": ["synthwave", "retrowave", "music visualizer", "original music", "neon"],
        "video": str(video),
        "audio": str(audio),
        "thumbnail": str(thumb),
    }
    (args.out / f"{slug}{suffix}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {video}（{time.time() - t0:.0f}秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
