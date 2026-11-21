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
# コメントの読み書き（みんなの裁判の投票集計）に必要。トークン取得時に一緒に許可しておく
COMMENT_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def credentials_available() -> bool:
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def _youtube(scopes: list[str]):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(video: Path, plan: VideoPlan, cfg: dict) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    from .tts import credit

    yt = _youtube(SCOPES)
    uc = cfg.get("upload", {})
    desc = plan.description
    if credit(cfg) and credit(cfg) not in desc:
        desc += f"\n\n音声：{credit(cfg)}"
    art = (cfg.get("character") or {}).get("credit", "")
    if art and (cfg.get("character") or {}).get("image") and Path(cfg["character"]["image"]).exists() and art not in desc:
        desc += f"\n{art}"
    body = {
        "snippet": {
            "title": plan.title[:100],
            "description": desc[:4900],
            "tags": plan.tags[:30],
            "categoryId": str(plan.category_id or uc.get("category_id", 27)),  # 27 = Education
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


def post_comment(video_id: str, text: str) -> str:
    """動画にコメントを書き込み、コメントの ID を返す（50 ユニット）。"""
    yt = _youtube(COMMENT_SCOPES)
    resp = yt.commentThreads().insert(part="snippet", body={
        "snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}},
    }).execute()
    return resp["id"]


def fetch_comments(video_id: str, max_pages: int = 10) -> list[dict]:
    """動画のトップレベルコメントを集める（1 ページ 100 件・1 ユニット）。

    返り値: [{"author": チャンネルID, "text": 本文, "likes": いいね数, "is_owner": 投稿者本人か}, ...]
    """
    yt = _youtube(COMMENT_SCOPES)
    out: list[dict] = []
    token = None
    for _ in range(max_pages):
        resp = yt.commentThreads().list(part="snippet", videoId=video_id, maxResults=100,
                                        textFormat="plainText", order="time", pageToken=token).execute()
        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            author = (top.get("authorChannelId") or {}).get("value", "")
            out.append({"author": author, "text": top.get("textOriginal") or top.get("textDisplay", ""),
                        "likes": int(top.get("likeCount", 0)),
                        "is_owner": bool(author) and author == item["snippet"].get("channelId")})
        token = resp.get("nextPageToken")
        if not token:
            break
    return out
