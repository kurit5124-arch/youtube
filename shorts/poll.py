"""「昨日の多数決」：前日の動画のコメントで投票を集計し、結果発表＋今日のお題の動画を作る。

流れ（毎日）:
  1. poll_state.json に書いてある「昨日の動画ID・お題」を読む
  2. その動画のコメントを YouTube Data API で読み、A / B（/ C）を数える
  3. 「昨日の結果発表」＋「今日のお題」の台本を作る
  4. 投稿したら、今日の動画ID・お題を poll_state.json に書く（save_state）

コメントを読むのに必要なもの（どちらか）:
  - 環境変数 YT_API_KEY（Google Cloud の「認証情報 → API キー」。無料）
  - または YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN（youtube.force-ssl などの権限があるとき）
どちらも無い・読めないときは、結果発表なしで「今日のお題」だけの動画になります。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import unicodedata
from pathlib import Path

import yaml

from . import illust
from .models import Scene, VideoPlan

LETTERS = "ABCD"
STATE_FILE = "poll_state.json"


# ---------------------------------------------------------------- お題
def load_polls(path: Path) -> list[dict]:
    polls = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    for p in polls:
        if not p.get("id") or not p.get("question") or len(p.get("choices", [])) < 2:
            raise ValueError(f"{path}: id・question・choices（2つ以上）が必要です: {p}")
    ids = [p["id"] for p in polls]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: id が重複しています")
    return polls


def pick_poll(polls: list[dict], date: dt.date, used: list[str] | None = None) -> dict:
    """今日のお題。季節もの（months）はその月だけ。最近使ったお題は避ける。"""
    used = used or []
    pool = [p for p in polls if not p.get("months") or date.month in p["months"]]
    fresh = [p for p in pool if p["id"] not in used] or pool or polls
    # dates: ["12-24"] のように日付指定のお題があれば優先
    md = f"{date.month:02d}-{date.day:02d}"
    pinned = [p for p in fresh if md in [str(x) for x in p.get("dates", [])]]
    if pinned:
        return pinned[0]
    return fresh[date.toordinal() % len(fresh)]


def _label(choice) -> str:
    return choice["label"] if isinstance(choice, dict) else str(choice)


def _words(choice) -> list[str]:
    if isinstance(choice, dict):
        return [_label(choice)] + [str(w) for w in choice.get("words", [])]
    return [str(choice)]


# ---------------------------------------------------------------- 集計
def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().lower()


def parse_vote(text: str, choices: list) -> int | None:
    """コメント1つから投票先を読む。読めなければ None。

    - 「A」「a派」「Ａです！」「B一択」のように先頭が A/B/C（の後に英字が続かない）
    - または選択肢の言葉（label / words）がちょうど1つの選択肢にだけ含まれている
    """
    t = _norm(text)
    if not t:
        return None
    letters = LETTERS[: len(choices)].lower()
    m = re.match(r"^[\s「『(（【]*([a-d])(?![a-z])", t)
    if m and m.group(1) in letters:
        return letters.index(m.group(1))
    hits = {i for i, c in enumerate(choices) for w in _words(c) if w and _norm(w) in t}
    return hits.pop() if len(hits) == 1 else None


def count_votes(comments: list[dict], choices: list, owner_id: str | None = None) -> list[int]:
    """comments = [{"author": チャンネルID, "text": 本文, "time": ISO時刻}]。1人1票（最後の投票を数える）。"""
    latest: dict[str, tuple[str, int]] = {}
    for c in comments:
        if owner_id and c.get("author") == owner_id:
            continue
        v = parse_vote(c.get("text", ""), choices)
        if v is None:
            continue
        key = c.get("author") or f"anon-{id(c)}"
        prev = latest.get(key)
        if prev is None or c.get("time", "") >= prev[0]:
            latest[key] = (c.get("time", ""), v)
    counts = [0] * len(choices)
    for _, v in latest.values():
        counts[v] += 1
    return counts


def _youtube_client():
    from googleapiclient.discovery import build

    key = os.environ.get("YT_API_KEY")
    if key:
        return build("youtube", "v3", developerKey=key, cache_discovery=False)
    if all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        from google.oauth2.credentials import Credentials

        creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                            client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                            token_uri="https://oauth2.googleapis.com/token")
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    return None


def fetch_comments(video_id: str, max_pages: int = 10) -> tuple[list[dict], str | None]:
    """動画のコメント（返信は除く）と、動画のチャンネルID。1ページ=1ユニット。"""
    yt = _youtube_client()
    if yt is None:
        raise RuntimeError("YT_API_KEY（または YouTube の認証情報）が無いのでコメントを読めません")
    out: list[dict] = []
    owner = None
    token = None
    for _ in range(max_pages):
        resp = yt.commentThreads().list(part="snippet", videoId=video_id, maxResults=100,
                                        textFormat="plainText", order="time", pageToken=token).execute()
        for item in resp.get("items", []):
            owner = owner or item["snippet"].get("channelId")
            s = item["snippet"]["topLevelComment"]["snippet"]
            out.append({"author": (s.get("authorChannelId") or {}).get("value", ""),
                        "text": s.get("textOriginal") or s.get("textDisplay", ""),
                        "time": s.get("publishedAt", "")})
        token = resp.get("nextPageToken")
        if not token:
            break
    return out, owner


# ---------------------------------------------------------------- 状態
def load_state(root: Path) -> dict:
    p = root / STATE_FILE
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(root: Path, plan: VideoPlan, video_id: str, date: dt.date) -> None:
    """投稿した今日のお題を記録する（明日の結果発表で使う）。過去の結果も履歴に残す。"""
    meta = plan.poll or {}
    state = load_state(root)
    history = state.get("history", [])
    if meta.get("result"):
        history.append(meta["result"])
    used = ([meta["id"]] + state.get("used", []))[:30]
    state = {"date": date.isoformat(), "video_id": video_id, "poll_id": meta.get("id"),
             "used": used, "history": history[-400:]}
    (root / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def yesterday_result(root: Path, polls: list[dict], cfg: dict) -> dict | None:
    """前回の動画のコメントを集計。結果が出せないときは None。"""
    state = load_state(root)
    vid, pid = state.get("video_id"), state.get("poll_id")
    poll = next((p for p in polls if p["id"] == pid), None)
    if not vid or not poll:
        print("[poll] 前回のお題が記録されていないので、結果発表なしで作ります")
        return None
    try:
        comments, owner = fetch_comments(vid)
    except Exception as e:  # noqa: BLE001 - 結果が読めなくても今日のお題は出す
        print(f"[warn] コメントを読めませんでした: {e}")
        return None
    counts = count_votes(comments, poll["choices"], owner)
    total = sum(counts)
    print(f"[poll] 前回「{poll['question']}」: コメント{len(comments)}件 → 有効票 {counts}")
    if total < int(cfg.get("poll", {}).get("min_votes", 1)):
        print("[poll] 票が少ないので結果発表はしません")
        return None
    return {"id": poll["id"], "question": poll["question"], "date": state.get("date"), "video_id": vid,
            "choices": [_label(c) for c in poll["choices"]], "counts": counts}


# ---------------------------------------------------------------- 台本
def _sentence(t: str) -> str:
    t = t.strip()
    return t if t.endswith(("。", "！", "？", "!", "?")) else t + "。"


def _pcts(counts: list[int]) -> list[int]:
    """合計がちょうど100になる整数の%（最大剰余法）。"""
    total = sum(counts) or 1
    raw = [c * 100 / total for c in counts]
    base = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)[: 100 - sum(base)]:
        base[i] += 1
    return base


def _result_scenes(res: dict, cfg: dict) -> list[Scene]:
    choices, counts = res["choices"], res["counts"]
    total = sum(counts)
    pcts = _pcts(counts)
    top = max(counts)
    winners = [i for i, c in enumerate(counts) if c == top]
    labels = [f"{LETTERS[i]}  {c}" for i, c in enumerate(choices)]
    em = illust.pick_one(res["question"], fallback="🗳️")
    show_n = total >= int(cfg.get("poll", {}).get("show_count_from", 30))
    who = f"{total}人が答えてくれました。" if show_n else "答えてくれたみんな、ありがとう！"
    scenes = [
        Scene(kind="hook", label="昨日の結果", text="昨日の多数決\n結果発表！", emoji="📣",
              narration=f"昨日の多数決、結果発表！お題は、{_sentence(res['question'])}"),
        Scene(kind="poll", label="結果は…？", text=res["question"], choices=labels, emoji=em,
              narration=who + "1位は…"),
    ]
    if len(winners) > 1:
        names = "と".join(choices[i] for i in winners)
        narr = f"なんと、{names}が{pcts[winners[0]]}パーセントで同点！決着は持ち越しです。"
    else:
        w = winners[0]
        narr = f"{choices[w]}！{pcts[w]}パーセントでした！"
        low = min(range(len(counts)), key=lambda i: counts[i])
        if len(choices) >= 2 and low != w and pcts[low] > 0:
            narr += f"少数派の{choices[low]}派は{pcts[low]}パーセント。"
    scenes.append(Scene(kind="poll", label="結果", text=res["question"], choices=labels, emoji=em,
                        answer=winners[0], reveal=True, reveal_label="1位",
                        ratios=[p / 100 for p in pcts], narration=narr))  # 画面と読み上げの%をそろえる
    return scenes


def plan_poll(date: dt.date, cfg: dict, root: Path, result: dict | None = "auto") -> VideoPlan:
    """result="auto" なら前回の動画のコメントを集計する。dict を渡せばそれを結果として使う（確認用）。"""
    polls = load_polls(root / "polls.yaml")
    state = load_state(root)
    if result == "auto":
        result = yesterday_result(root, polls, cfg)
    used = state.get("used", []) + ([result["id"]] if result else [])
    poll = pick_poll(polls, date, used)
    pc = cfg.get("poll", {})

    choices = [_label(c) for c in poll["choices"]]
    letters = LETTERS[: len(choices)]
    em = poll.get("emoji") or illust.pick_one(poll["question"], fallback="🤔")
    scenes: list[Scene] = []
    if result:
        scenes += _result_scenes(result, cfg)
    else:
        scenes.append(Scene(kind="hook", label="多数決", text="みんなの答えで\n決まる多数決", emoji="🗳️",
                            narration="みんなの答えで決まる、日本人の多数決！"))
    how = "か".join(letters) if len(letters) == 2 else "・".join(letters)
    which = "どっち" if len(letters) == 2 else "どれ"
    vote = how if len(letters) == 2 else "、".join(letters) + "のどれか"  # 読み上げ用
    read = "。".join(f"{l}、{c}" for l, c in zip(letters, choices))
    scenes.append(Scene(kind="poll", label="今日のお題", text=poll["question"], emoji=em,
                        choices=[f"{l}  {c}" for l, c in zip(letters, choices)],
                        narration=f"今日のお題。{_sentence(poll['question'])}{read}。あなたは{which}？"))
    scenes.append(Scene(kind="outro", label="投票してね", text=f"コメントに\n「{how}」で投票！\n結果は明日", emoji="✍️",
                        narration=pc.get("outro_narration",
                                         f"コメントに、{vote}で投票してね！結果は明日の動画で発表します。")))

    title = f"【多数決】{poll['question']} あなたは{which}？"
    if result:
        w = max(range(len(result["counts"])), key=lambda i: result["counts"][i])
        title += f"｜昨日は{result['choices'][w]}派が{_pcts(result['counts'])[w]}%"
    title += " #shorts"

    lines = [f"今日のお題：{poll['question']}", ""]
    lines += [f"  {l}：{c}" for l, c in zip(letters, choices)]
    lines += ["", f"コメントに「{how}」で投票してください（1人1票・最後のコメントを数えます）。",
              "結果は明日の動画で発表します。", ""]
    if result:
        pcts = _pcts(result["counts"])
        lines += [f"▼ 昨日の結果：{result['question']}"]
        lines += [f"  {LETTERS[i]}：{c}　{pcts[i]}%（{result['counts'][i]}票）" for i, c in enumerate(result["choices"])]
        lines += [""]
    tags = list(dict.fromkeys(["多数決", "あなたはどっち", "アンケート", *poll.get("tags", []), "shorts"]))
    lines += ["イラスト：Noto Emoji（Google / SIL Open Font License）", "", " ".join("#" + t for t in tags)]

    plan = VideoPlan(header=pc.get("header", "日本人の多数決"), subheader=date.strftime("%-m月%-d日"),
                     scenes=scenes, title=title[:100], description="\n".join(lines), tags=tags,
                     seed=date.toordinal() * 7 + 3,
                     emojis=list(dict.fromkeys([em, "🗳️"])),
                     max_seconds=float(pc.get("max_seconds", 58)))
    plan.poll = {"id": poll["id"], "result": result}
    return plan
