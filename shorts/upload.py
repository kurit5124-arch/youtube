"""YouTube Data API で動画をアップロードする。

必要な環境変数（GitHub Actions では Secrets に登録）:
  YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .models import VideoPlan

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def credentials_available() -> bool:
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def upload(video: Path, plan: VideoPlan, cfg: dict) -> str:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    uc = cfg.get("upload", {})
    body = {
        "snippet": {
            "title": plan.title[:100],
            "description": plan.description[:4900],
            "tags": plan.tags[:30],
            "categoryId": str(uc.get("category_id", 27)),  # 27 = Education
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": uc.get("privacy", "private"),
            "selfDeclaredMadeForKids": bool(uc.get("made_for_kids", False)),
            "containsSyntheticMedia": True,  # AI 合成音声を使っているので申告
        },
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=-1, resumable=True))
    resp = None
    retries = 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                time.sleep(2 ** retries)
                continue
            raise
    return resp["id"]
