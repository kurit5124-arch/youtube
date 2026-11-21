#!/usr/bin/env python3
"""「みんなの裁判」ショートを自動で作って投稿する。

使い方:
  python saiban.py                 # 動画を作るだけ（履歴は更新しない）
  python saiban.py --upload        # 前回の判決を集計 → 新しい事件の動画を投稿 → 履歴を更新
  python saiban.py --stock         # Claude を使わず saiban/cases.yaml の事件を使う
  python saiban.py --no-verdict    # 前回の判決発表を入れない
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from shorts import note, pipeline, upload
from shorts import saiban as sb

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upload", action="store_true", help="YouTube に投稿して履歴を更新する")
    ap.add_argument("--stock", action="store_true", help="手持ちの事件（saiban/cases.yaml）を使う")
    ap.add_argument("--no-verdict", action="store_true", help="前回の判決発表を入れない")
    ap.add_argument("--case", help="手持ちの事件をタイトルで指定する（動作確認・作り直し用）")
    ap.add_argument("--number", type=int, help="事件番号を指定する（既定: 履歴の続き）")
    ap.add_argument("--allow-silent", action="store_true", help="音声合成できないとき無音で続行（動作確認用）")
    ap.add_argument("--out", default="output", help="出力フォルダ")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    sc = cfg.get("saiban", {})
    # 判決発表＋事件で少し長くなるので、裁判用の尺を優先する
    cfg = {**cfg, "max_seconds": sc.get("max_seconds", 59)}
    tz = ZoneInfo(cfg.get("timezone", "Asia/Tokyo"))
    now = dt.datetime.now(tz)
    hist_path = ROOT / sc.get("history", "saiban/history.json")
    history = sb.load_history(hist_path)
    yt_ok = upload.credentials_available()

    # 1) 前回の判決
    prev = None if args.no_verdict else sb.pending_case(history, now, float(sc.get("min_hours", 12)))
    verdict = None
    if prev and yt_ok:
        try:
            comments = upload.fetch_comments(prev["video_id"])
            a, b, a_list, b_list = sb.count_votes(comments)
            verdict = sb.Verdict(a, b)
            print(f"[verdict] No.{prev['no']} {prev['case']['title']}: A {a}票 / B {b}票（コメント {len(comments)}件）")
            if verdict.total and sb.claude_available() and not args.stock:
                try:
                    verdict.a_voice, verdict.b_voice = sb.pick_voices(cfg, prev["case"], a_list, b_list)
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] コメントの紹介文を作れませんでした: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 前回のコメントを読めませんでした（トークンにコメント権限が無い可能性）: {e}")
    elif prev:
        print("[info] YouTube の Secrets が無いので、前回の判決は集計しません")
    show_verdict = verdict is not None and verdict.total >= int(sc.get("min_votes", 1))
    if verdict is not None and not show_verdict:
        print("[info] 票が少ないので、今回は判決発表を入れません")

    # 2) 新しい事件
    case = None
    if args.case:
        cases = yaml.safe_load((ROOT / sc.get("cases", "saiban/cases.yaml")).read_text(encoding="utf-8")) or []
        case = next((c for c in cases if c["title"] == args.case), None)
        if case is None:
            print(f"[error] 「{args.case}」という事件が見つかりません", file=sys.stderr)
            return 2
        case["source"] = "stock"
    elif not args.stock and sb.claude_available():
        try:
            case = sb.generate_case(cfg, [h["case"] for h in history])
            case["source"] = "claude"
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Claude で事件を作れなかったので手持ちの事件を使います: {e}")
    if case is None:
        case = sb.stock_case(ROOT / sc.get("cases", "saiban/cases.yaml"), history)
        case["source"] = "stock"
    no = args.number or ((history[-1]["no"] + 1) if history else 1)

    plan = sb.build_plan(case, no, now.date(), prev if show_verdict else None, verdict if show_verdict else None)
    print(f"[plan] {plan.title}")
    for s in plan.scenes:
        print(f"   - [{s.label}] {s.narration}")

    # 3) 動画
    name = f"{now.date().isoformat()}_saiban_{no:03d}"
    out = Path(args.out) / f"{name}.mp4"
    os.chdir(ROOT)
    pipeline.build_video(plan, cfg, Path(args.out) / "work" / name, out, allow_silent=args.allow_silent)
    print(f"[done] {out}")
    np_prev, np_v = (prev, verdict) if show_verdict else (None, None)
    ntitle, nmd = note.saiban_article(case, no, None, np_prev, np_v)
    print(f"[note] {note.write(out.with_suffix(''), ntitle, nmd)[1]}")

    if not args.upload:
        return 0
    if not yt_ok:
        print("[error] YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN が設定されていません", file=sys.stderr)
        return 2

    # 4) 投稿・案内コメント・履歴
    vid = upload.upload(out, plan, cfg)
    print(f"[uploaded] https://youtube.com/shorts/{vid}")
    note.write(out.with_suffix(""), *note.saiban_article(case, no, vid, np_prev, np_v))  # 動画の URL 入りに更新
    try:
        upload.post_comment(vid, sb.vote_comment(case))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 投票案内のコメントを書けませんでした: {e}")

    if prev and verdict is not None:
        prev["verdict"] = {"a": verdict.a, "b": verdict.b, "a_voice": verdict.a_voice, "b_voice": verdict.b_voice,
                           "announced": show_verdict, "announced_in": vid if show_verdict else None}
    history.append({"no": no, "date": now.date().isoformat(), "uploaded_at": now.isoformat(timespec="seconds"),
                    "video_id": vid, "case": case, "verdict": None})
    sb.save_history(hist_path, history)

    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"### みんなの裁判 No.{no} を投稿しました\n- {plan.title}\n- https://youtube.com/shorts/{vid}\n")
            if prev and verdict is not None:
                f.write(f"- 前回 No.{prev['no']} の票: A {verdict.a} / B {verdict.b}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
