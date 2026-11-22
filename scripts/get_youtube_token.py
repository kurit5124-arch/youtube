#!/usr/bin/env python3
"""YouTube へ投稿するためのリフレッシュトークンを取得する（自分の PC で 1 回だけ実行）。

1. Google Cloud Console で OAuth クライアント（デスクトップアプリ）を作り、
   JSON をダウンロードして client_secret.json としてこのリポジトリ直下に置く
2. pip install google-auth-oauthlib
3. python scripts/get_youtube_token.py
4. ブラウザでチャンネルのアカウントを選んで許可
5. 表示された 3 つの値を GitHub の Secrets に登録

別チャンネル（アフィリエイト用など）のトークンを取るとき:
  python scripts/get_youtube_token.py client_secret.json YT2
  → ブラウザで「そのチャンネル」を選ぶ。YT2_REFRESH_TOKEN などの名前で表示されます
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

path = Path(sys.argv[1] if len(sys.argv) > 1 else "client_secret.json")
prefix = sys.argv[2] if len(sys.argv) > 2 else "YT"
if not path.exists():
    sys.exit(f"{path} が見つかりません。Google Cloud Console からダウンロードしてください。")

flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
info = json.loads(path.read_text())
info = info.get("installed") or info.get("web")

print("\n以下を GitHub リポジトリの Settings → Secrets and variables → Actions に登録してください:\n")
print(f"{prefix}_CLIENT_ID     = {info['client_id']}")
print(f"{prefix}_CLIENT_SECRET = {info['client_secret']}")
print(f"{prefix}_REFRESH_TOKEN = {creds.refresh_token}")
print("\n※ これらは他人に見せないでください。")
