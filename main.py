#!/usr/bin/env python3
"""YouTube ショート動画を自動生成（＋アップロード）する。

使い方:
  python main.py                      # 今日の「今日は何の日」動画を作る
  python main.py --source topics      # topics.yaml の雑学ネタで作る
  python main.py --date 2026-12-25    # 日付を指定
  python main.py --upload             # 作ったあと YouTube に投稿
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from shorts import pipeline, sources, upload

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["auto", "today", "topics"], help="ネタの取り方（既定: config.yaml）")
    ap.add_argument("--date", help="YYYY-MM-DD（既定: 日本時間の今日）")
    ap.add_argument("--topic-index", type=int, help="topics.yaml の何番目を使うか（0始まり）")
    ap.add_argument("--topics-file", help="topics.yaml の代わりに使うネタ帳（例: discussions.yaml）")
    ap.add_argument("--story-file", help="イラスト付きストーリー動画の台本（例: stories.yaml）")
    ap.add_argument("--story-index", type=int, default=0, help="--story-file の何番目を使うか（0始まり）")
    ap.add_argument("--upload", action="store_true", help="YouTube にアップロードする")
    ap.add_argument("--allow-silent", action="store_true", help="音声合成できないとき無音で続行（動作確認用）")
    ap.add_argument("--out", default="output", help="出力フォルダ")
    ap.add_argument("--wikitext-file", help="Wikipedia を取りに行かずにこのファイルを使う（動作確認用）")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    tz = ZoneInfo(cfg.get("timezone", "Asia/Tokyo"))
    date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(tz).date()
    source = args.source or cfg.get("source", "auto")

    if args.wikitext_file:
        plan = sources.plan_today(date, cfg, Path(args.wikitext_file).read_text(encoding="utf-8"))
        source = "today"
    elif args.story_file:
        from shorts import story
        source = "story"
        st = story.load(ROOT / args.story_file)[args.story_index]
        if st.get("voice"):
            cfg = {**cfg, "voice": {**cfg.get("voice", {}), **st["voice"]}}
        # テンポを速く（場面の間を短く）
        cfg = {**cfg, "max_seconds": st.get("max_seconds", 59), "scene_gap": st.get("scene_gap", 0.2)}
        plan = story.plan_story(st, date)
    elif args.topics_file:
        source = "topics"
        tf = ROOT / args.topics_file
        topic = (yaml.safe_load(tf.read_text(encoding="utf-8")) or [])[args.topic_index or 0]
        if topic.get("voice"):  # このネタだけ声を変える（例: 落ち着いたテーマは落ち着いた声）
            cfg = {**cfg, "voice": {**cfg.get("voice", {}), **topic["voice"]}}
        plan = sources.plan_topic(date, cfg, tf, args.topic_index)
    else:
        plan = sources.make_plan(source, date, cfg, ROOT, args.topic_index)
    print(f"[plan] {plan.title}")
    for s in plan.scenes:
        print(f"   - [{s.label}] {s.narration}")

    name = f"{date.isoformat()}_{source}_{sources.slug(plan)}"
    out = Path(args.out) / f"{name}.mp4"
    os.chdir(ROOT)
    pipeline.build_video(plan, cfg, Path(args.out) / "work" / name, out, allow_silent=args.allow_silent)
    print(f"[done] {out}")

    if args.upload:
        if not upload.credentials_available():
            print("[error] YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN が設定されていません", file=sys.stderr)
            return 2
        vid = upload.upload(out, plan, cfg)
        print(f"[uploaded] https://youtube.com/shorts/{vid}")
        gh = os.environ.get("GITHUB_STEP_SUMMARY")
        if gh:
            with open(gh, "a", encoding="utf-8") as f:
                f.write(f"### 投稿しました\n- {plan.title}\n- https://youtube.com/shorts/{vid}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
