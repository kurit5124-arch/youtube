#!/usr/bin/env python3
"""その日の雑学（topics.yaml から2本）を文章で表示する。チャットに送る用。

  python scripts/print_trivia.py              # 日本時間の今日
  python scripts/print_trivia.py 2026-12-01   # 日付指定
"""
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
topics = yaml.safe_load((ROOT / "topics.yaml").read_text(encoding="utf-8")) or []
per_day = int(cfg.get("topics_per_day", 2))
date = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()

print(f"# {date.month}月{date.day}日の雑学")
for slot in range(per_day):
    t = topics[(date.toordinal() * per_day + slot) % len(topics)]
    print(f"\n## {t.get('emoji', '💡')} {t['title']}")
    for n, p in enumerate(t["points"], 1):
        if isinstance(p, dict):
            print(f"{n}. **{p['text']}**  \n   {p.get('narration', '')}")
        else:
            print(f"{n}. {p}")
