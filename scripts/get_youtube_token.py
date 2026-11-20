#!/usr/bin/env python3
"""YouTube へ投稿するためのリフレッシュトークンを取得する（自分の PC で 1 回だけ実行）。

1. Google Cloud Console で OAuth クライアント（デスクトップアプリ）を作り、
   JSON をダウンロードして client_secret.json としてこのリポジトリ直下に置く
2. pip install google-auth-oauthlib
3. python scripts/get_youtube_token.py
4. ブラウザでチャンネルのアカウントを選んで許可
5. 表示された 3 つの値を GitHub の Secrets に登録
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# upload: 動画の投稿 / force-ssl: コメントの読み書き（みんなの裁判の投票集計に使う）
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]

path = Path(sys.argv[1] if len(sys.argv) > 1 else "client_secret.json")
if not path.exists():
    sys.exit(f"{path} が見つかりません。Google Cloud Console からダウンロードしてください。")

flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
info = json.loads(path.read_text())
info = info.get("installed") or info.get("web")

print("\n以下を GitHub リポジトリの Settings → Secrets and variables → Actions に登録してください:\n")
print(f"YT_CLIENT_ID     = {info['client_id']}")
print(f"YT_CLIENT_SECRET = {info['client_secret']}")
print(f"YT_REFRESH_TOKEN = {creds.refresh_token}")
print("\n※ これらは他人に見せないでください。")
