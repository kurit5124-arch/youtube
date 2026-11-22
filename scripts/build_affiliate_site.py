#!/usr/bin/env python3
"""affiliate.yaml からまとめページ（site/index.html）を作る。

  python scripts/build_affiliate_site.py              # channels/affiliate の設定
  python scripts/build_affiliate_site.py 別のチャンネル名
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shorts import affiliate  # noqa: E402

if __name__ == "__main__":
    channel = sys.argv[1] if len(sys.argv) > 1 else "affiliate"
    cfg = affiliate.load(ROOT / "channels" / channel)
    if not cfg:
        sys.exit(f"channels/{channel}/affiliate.yaml がありません")
    import yaml
    tp = ROOT / "channels" / channel / "topics.yaml"
    topics = (yaml.safe_load(tp.read_text(encoding="utf-8")) or []) if tp.exists() else []
    out = affiliate.build_site(cfg, ROOT / "site", topics)
    print(f"[done] {out}")
    if not (cfg.get("amazon_tag") or cfg.get("rakuten_id")):
        print("[warn] Amazon / 楽天の ID が未設定なので、url: を書いた商品しか載りません")
