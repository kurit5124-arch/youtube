"""楽天市場の商品検索API（2026年の新しい版）で、人気の商品を自動で選ぶ。

必要な環境変数（GitHub Actions では Secrets に登録）:
  RAKUTEN_APP_ID      … 楽天ウェブサービスのアプリID（UUID 形式）
  RAKUTEN_ACCESS_KEY  … 同じ画面のアクセスキー（pk_ で始まる）
アフィリエイトIDも一緒に渡すので、返ってくる商品リンクは最初からあなたのアフィリエイトリンクになる。
"""
from __future__ import annotations

import os
import re
import time

import requests
from urllib.parse import urlsplit

ENDPOINT = os.environ.get(
    "RAKUTEN_ITEM_SEARCH_URL",
    "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701",
)
_last_call = 0.0
_cache: dict[str, list[dict]] = {}


def available() -> bool:
    return bool(os.environ.get("RAKUTEN_APP_ID") and os.environ.get("RAKUTEN_ACCESS_KEY"))


def short_name(name: str, limit: int = 34) -> str:
    """「【楽天1位】送料無料 枕 まくら ...」のような長い商品名を短くする。"""
    s = re.sub(r"[【\[［(（<＜《][^】\]］)）>＞》]*[】\]］)）>＞》]", " ", name)
    s = re.sub(r"(送料無料|ポイント\d+倍|\d+%OFF|クーポン\S*|楽天\d位\S*|あす楽\S*|即納)", " ", s)
    s = re.sub(r"[★☆◆◇■□●○※!！]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip() or name.strip()
    if len(s) > limit:
        cut = s.rfind(" ", 0, limit)
        s = s[: cut if cut >= limit // 2 else limit].rstrip() + "…"
    return s


def _items(data: dict) -> list[dict]:
    out = []
    for it in data.get("Items") or data.get("items") or []:
        if isinstance(it, dict) and isinstance(it.get("Item"), dict):
            it = it["Item"]
        if isinstance(it, dict):
            out.append(it)
    return out


def search(keyword: str, affiliate_id: str, referer: str = "", hits: int = 20) -> list[dict]:
    """レビューの多い順に商品を探す。失敗したら空のリスト。"""
    global _last_call
    if keyword in _cache:
        return _cache[keyword]
    app_id, key = os.environ.get("RAKUTEN_APP_ID", ""), os.environ.get("RAKUTEN_ACCESS_KEY", "")
    params = {
        "applicationId": app_id, "accessKey": key, "keyword": keyword, "hits": hits,
        "sort": "-reviewCount", "availability": 1, "imageFlag": 1, "formatVersion": 2, "format": "json",
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "shorts-affiliate/1.0"}
    if referer:  # 楽天ウェブサービスに登録した「許可されたWebサイト」と同じにする
        headers["Referer"] = referer
        u = urlsplit(referer)
        if u.scheme and u.netloc:
            headers["Origin"] = f"{u.scheme}://{u.netloc}"
    wait = 1.1 - (time.time() - _last_call)  # 1秒に1回まで
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(ENDPOINT, params=params, headers=headers, timeout=20)
        _last_call = time.time()
        if r.status_code != 200:
            print(f"[rakuten] 商品検索に失敗（{keyword}）: HTTP {r.status_code} {r.text[:200]}")
            items = []
        else:
            items = _items(r.json())
    except Exception as e:  # noqa: BLE001 - 失敗しても動画づくりは止めない
        print(f"[rakuten] 商品検索に失敗（{keyword}）: {e}")
        items = []
    _cache[keyword] = items
    return items


def pick(keyword: str, affiliate_id: str, referer: str = "", exclude: set[str] | None = None,
         min_reviews: int = 20, min_average: float = 4.0) -> dict | None:
    """レビューが多くて評価の高い商品を1つ選ぶ。"""
    exclude = exclude or set()
    items = search(keyword, affiliate_id, referer)
    good = [it for it in items
            if str(it.get("itemCode")) not in exclude
            and int(it.get("reviewCount") or 0) >= min_reviews
            and float(it.get("reviewAverage") or 0) >= min_average
            and (it.get("affiliateUrl") or it.get("itemUrl"))]
    if not good:
        good = [it for it in items if str(it.get("itemCode")) not in exclude and (it.get("affiliateUrl") or it.get("itemUrl"))]
    if not good:
        return None
    it = good[0]
    return {
        "code": str(it.get("itemCode")),
        "name": short_name(str(it.get("itemName", ""))),
        "url": it.get("affiliateUrl") or it.get("itemUrl"),
        "price": int(it.get("itemPrice") or 0),
        "review_average": float(it.get("reviewAverage") or 0),
        "review_count": int(it.get("reviewCount") or 0),
        "shop": str(it.get("shopName", "")),
    }
