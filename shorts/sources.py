"""動画のネタを集めて VideoPlan（台本）を作る。

- today : Wikipedia 日本語版の「○月○日」ページから「今日は何の日」を自動作成
- topics: topics.yaml に書いた雑学ネタを日替わりで使う
"""
from __future__ import annotations

import datetime as dt
import os
import random
import re
import time
from pathlib import Path

import requests
import yaml

from . import illust, wikitext
from .models import Scene, VideoPlan

WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKI_RAW = "https://ja.wikipedia.org/w/index.php"
# Wikimedia の決まり: ボットは何者か・連絡先（URL）を名乗る
USER_AGENT = os.environ.get(
    "WIKI_USER_AGENT",
    "DailyShortsQuizBot/1.1 (https://github.com/%s; automated daily quiz video) python-requests"
    % os.environ.get("GITHUB_REPOSITORY", "kurit5124-arch/youtube"),
)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith(("。", "！", "？", "!", "?")) else text + "。"


def _shorten(text: str, limit: int) -> str:
    """長すぎる文は最初の句点・読点で切る。"""
    if len(text) <= limit:
        return text
    for sep in ("。", "（", "(", "、"):
        idx = text.find(sep)
        if 8 <= idx <= limit:
            return text[:idx]
    return text[: limit - 1] + "…"


# ---------------------------------------------------------------- today
def fetch_date_wikitext(date: dt.date, attempts: int = 6) -> str:
    """「○月○日」ページの本文を取る。混雑（429 など）なら待ってやり直す。"""
    page = f"{date.month}月{date.day}日"
    headers = {"User-Agent": USER_AGENT, "Api-User-Agent": USER_AGENT}
    last: Exception | None = None
    for n in range(attempts):
        for how in ("api", "raw"):
            try:
                if how == "api":
                    r = requests.get(WIKI_API, headers=headers, timeout=30, params={
                        "action": "parse", "page": page, "prop": "wikitext", "format": "json",
                        "formatversion": 2, "redirects": 1, "maxlag": 5})
                    r.raise_for_status()
                    data = r.json()
                    if "parse" not in data:
                        raise RuntimeError(data.get("error", data))
                    return data["parse"]["wikitext"]
                r = requests.get(WIKI_RAW, headers=headers, timeout=30,
                                 params={"title": page, "action": "raw"})
                r.raise_for_status()
                if "== できごと ==" in r.text or "==できごと==" in r.text or "できごと" in r.text:
                    return r.text
                raise RuntimeError("ページの形式が想定と違います")
            except Exception as e:  # noqa: BLE001
                last = e
                retry_after = 0
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    try:
                        retry_after = int(e.response.headers.get("Retry-After", "0"))
                    except ValueError:
                        retry_after = 0
                print(f"[warn] Wikipedia 取得失敗 ({how}, {n + 1}回目): {e}")
        if n < attempts - 1:
            wait = max(retry_after, min(15 * 2 ** n, 90))
            print(f"[info] {wait}秒待ってやり直します")
            time.sleep(wait)
    raise RuntimeError(f"Wikipedia から取得できませんでした: {last}")


def plan_today(date: dt.date, cfg: dict, wikitext_src: str | None = None) -> VideoPlan:
    src = wikitext_src if wikitext_src is not None else fetch_date_wikitext(date)
    secs = wikitext.sections(src)
    events = wikitext.parse_events(next((v for k, v in secs.items() if "できごと" in k or "出来事" in k), ""))
    obs = wikitext.parse_observances(next((v for k, v in secs.items() if "記念日" in k), ""))
    if not events:
        raise RuntimeError("Wikipedia から出来事を取得できませんでした")

    tc = cfg.get("today", {})
    rng = random.Random(date.toordinal())
    min_year = tc.get("min_year", 1600)
    max_chars = tc.get("max_chars", 60)

    quiz = tc.get("format", "quiz") == "quiz"
    if quiz:
        # クイズは3問を58秒に収めるため、1文目が短い出来事だけを使う
        qmax = tc.get("quiz_max_chars", 36)
        firsts = [(y, re.split(r"[。]", t)[0].strip()) for y, t in events]
        good = [(y, t) for y, t in firsts if y >= min_year and 6 <= len(t) <= qmax]
        if len(good) < 3:
            good = [(y, t) for y, t in firsts if 6 <= len(t) <= qmax + 15]
    else:
        good = [(y, _shorten(t, max_chars)) for y, t in events if y >= min_year and 6 <= len(t)]
    if len(good) < 3:
        good = [(y, _shorten(t, max_chars)) for y, t in events]
    # 日本関連を少し優先しつつランダムに選ぶ
    jp_words = ("日本", "東京", "大阪", "京都", "江戸", "幕府", "天皇", "昭和", "平成", "令和", "明治", "大正", "国鉄", "JR", "NHK")
    weights = [3 if any(w in t for w in jp_words) else 1 for _, t in good]
    picked: list[tuple[int, str]] = []
    pool = list(zip(good, weights))
    for _ in range(min(tc.get("num_events", 3), len(pool))):
        choice = rng.choices(range(len(pool)), weights=[w for _, w in pool])[0]
        picked.append(pool.pop(choice)[0])
    picked.sort()

    md = f"{date.month}月{date.day}日"
    if quiz:
        use_obs = tc.get("include_observance", True)
        best = wikitext.best_observance(obs) if use_obs else None
        jp_list = [(n, d) for n, d, jp in obs if jp] if use_obs else []
        return _quiz_today(date, md, picked, best, cfg, rng, holiday=japan_holiday(date), jp_list=jp_list)
    scenes = [Scene(kind="hook", label="TODAY", text=f"{md}は\n何の日？",
                    narration=f"今日、{md}は何の日？思わず話したくなる出来事を紹介します。")]

    obs_used = None
    best = wikitext.best_observance(obs) if tc.get("include_observance", True) else None
    if best:
        name, desc = best
        obs_used = name
        desc = _shorten(desc, 45) if desc else ""
        scenes.append(Scene(kind="item", label="記念日", text=f"「{name}」",
                            narration=_sentence(f"まず今日は、{name}") + (_sentence(desc) if desc else "")))

    for y, t in picked:
        year = f"紀元前{-y}年" if y < 0 else f"{y}年"
        scenes.append(Scene(kind="item", label=year, text=t, narration=_sentence(f"{year}、{t}")))

    scenes.append(Scene(kind="outro", label="SEE YOU", text="明日の\n「何の日」もお楽しみに！",
                        narration=cfg.get("outro_narration", "明日もお楽しみに！チャンネル登録よろしくお願いします。")))

    lines = [f"{md}は何の日？今日起きた歴史上の出来事を紹介します。", ""]
    if obs_used:
        lines.append(f"■ 記念日：{obs_used}")
    lines += [f"■ {('紀元前%d' % -y) if y < 0 else y}年：{t}" for y, t in picked]
    lines += ["", f"出典：Wikipedia「{md}」 https://ja.wikipedia.org/wiki/{md}",
              "（CC BY-SA 4.0 で提供されている文章をもとに作成しています）", "",
              "#今日は何の日 #雑学 #歴史 #shorts"]

    return VideoPlan(
        header="今日は何の日？", subheader=md, scenes=scenes,
        title=f"【今日は何の日】{md}に起きた出来事 #shorts",
        description="\n".join(lines),
        tags=["今日は何の日", md, "雑学", "歴史", "shorts"],
        seed=date.toordinal(),
    )


def _year_str(y: int) -> str:
    return f"紀元前{-y}年" if y < 0 else f"{y}年"


def _year_choices(y: int, rng: random.Random, this_year: int) -> tuple[list[int], int]:
    """正解の年 y と、それっぽいハズレ2つを作る。正解の位置（A/B/C）もランダムにする。"""
    age = this_year - y
    step = 5 if age < 60 else 10 if age < 200 else 25
    for pos in rng.sample([0, 1, 2], 3):  # 正解を A・B・C のどこに置くか（無理なら次の候補）
        below = [y - k * step for k in rng.sample(range(1, 5), 4)]
        above = [y + k * step for k in rng.sample(range(1, 5), 4) if y + k * step <= this_year]
        below = [c for c in below if (y < 0) == (c < 0)]
        need_below, need_above = pos, 2 - pos
        if len(below) >= need_below and len(above) >= need_above:
            years = sorted([y] + below[:need_below] + above[:need_above])
            return years, years.index(y)
    years = sorted([y, y - step, y - 2 * step])
    return years, years.index(y)


LETTERS = "ABC"


def _first_sentences(text: str, limit: int) -> str:
    """説明文を、limit 文字以内に収まるところまで文単位で切る。"""
    out = ""
    for sent in [x for x in re.split(r"(?<=。)", text) if x.strip()]:
        if len(out) + len(sent) > limit:
            break
        out += sent
    return out or _shorten(text, limit)


def japan_holiday(date: dt.date) -> str | None:
    """日本の祝日ならその名前（振替休日も含む）。"""
    try:
        import jpholiday
    except ImportError:
        return None
    return jpholiday.is_holiday_name(date)


def _quiz_today(date, md, picked, obs, cfg, rng, holiday: str | None = None,
                jp_list: list[tuple[str, str]] | None = None) -> VideoPlan:
    """obs = (記念日の名前, 説明) または None。holiday = 祝日名。jp_list = 日本の記念日 [(名前, 説明)]"""
    tc = cfg.get("today", {})
    jp_list = jp_list or []
    if holiday:
        # 祝日を一番に紹介する（説明は Wikipedia の記念日欄から探す）
        desc = next((d for n, d in jp_list + ([obs] if obs else []) if d and (holiday in n or n in holiday)), "")
        obs = (holiday, desc or "国民の祝日です。")
    obs_name, obs_desc = obs if obs else ("", "")
    obs_emoji = illust.pick_one(obs_name + obs_desc, fallback="🎌" if holiday else "📅") if obs else "📅"

    hook_narr = (f"今日、{md}は祝日、{holiday}！3択クイズに挑戦！" if holiday
                 else f"今日、{md}は何の日？3択クイズに挑戦！")
    scenes = [Scene(kind="hook", label="3択クイズ", text=f"{md}は\n何の日？", emoji=obs_emoji, narration=hook_narr)]

    # 今日は何の日かの説明（祝日なら祝日）
    if obs:
        desc = _first_sentences(obs_desc, tc.get("observance_max_chars", 70)) if obs_desc else ""
        scenes.append(Scene(kind="item", label="今日は祝日" if holiday else "今日は何の日",
                            text=f"「{obs_name}」", subtext=desc, emoji=obs_emoji,
                            narration=_sentence(f"今日は、{obs_name}") + (_sentence(desc) if desc else "")))

    # ほかの日本の記念日
    others = [n for n, _ in jp_list if n != obs_name and not (holiday and (holiday in n or n in holiday))]
    others = [n if len(n) <= 18 else n[:17] + "…" for n in dict.fromkeys(others)][: int(tc.get("jp_observances_max", 3))]
    if others:
        scenes.append(Scene(kind="item", label="日本の記念日", text="\n".join(f"・{n}" for n in others),
                            emoji=illust.pick_one("".join(others), fallback="🗓️"),
                            narration="ほかにも今日は、" + "、".join(others) + "です。"))

    answers = []
    for n, (y, t) in enumerate(picked, 1):
        years, ans = _year_choices(y, rng, date.year)
        choices = [f"{LETTERS[i]}  {_year_str(v)}" for i, v in enumerate(years)]
        t = t.rstrip("。")
        em = illust.pick_one(t, fallback="❓")
        q = Scene(kind="item", group=n, label=f"第{n}問", text=t, choices=choices, emoji=em,
                  narration=_sentence(f"第{n}問。{t}") + "何年？")
        scenes.append(q)
        for c in (3, 2, 1):
            scenes.append(Scene(kind="item", group=n, label=f"第{n}問", text=t, choices=choices, emoji=em,
                                countdown=c, narration=""))
        scenes.append(Scene(kind="item", group=n, label="正解！", text=t, choices=choices, answer=ans, emoji=em,
                            reveal=True, narration=f"正解は、{LETTERS[ans]}、{_year_str(y)}でした！"))
        answers.append((y, t))

    scenes.append(Scene(kind="outro", label="SEE YOU", text="何問わかった？\nコメントで\n教えてね！", emoji="🙌",
                        narration=cfg.get("quiz_outro_narration", "何問わかった？コメントで教えてね！")))

    lines = [f"{md}は何の日？出来事が何年か当てる3択クイズに挑戦！", "何問わかったかコメントで教えてね。", ""]
    if obs:
        head = f"■ 今日は祝日「{obs_name}」" if holiday else f"■ 今日は「{obs_name}」"
        lines += [head, obs_desc, ""] if obs_desc else [head, ""]
    if others:
        lines += ["■ 日本の記念日：" + "、".join(others), ""]
    lines += ["▼ クイズの答え（ネタバレ注意）", "", "", ""]
    lines += [f"■ {_year_str(y)}：{t}" for y, t in answers]
    lines += ["", f"出典：Wikipedia「{md}」 https://ja.wikipedia.org/wiki/{md}",
              "（CC BY-SA 4.0 で提供されている文章をもとに作成しています）",
              "イラスト：Noto Emoji（Google / SIL Open Font License）", "",
              "#クイズ #今日は何の日 #雑学 #歴史 #shorts"]
    emojis = [obs_emoji] + [s.emoji for s in scenes if s.choices and s.emoji not in ("❓",)]
    plan = VideoPlan(
        header="今日は何の日クイズ", subheader=md, scenes=scenes,
        title=(f"【今日は何の日】{md}は祝日「{obs_name}」！3択クイズ #shorts" if holiday
               else f"【今日は何の日】{md}は{obs_name}！3択クイズ #shorts" if obs
               else f"【3択クイズ】{md}の出来事、何年かわかる？ #shorts"),
        description="\n".join(lines),
        tags=["クイズ", "3択クイズ", "今日は何の日", md, obs_name, *others, "祝日" if holiday else "記念日",
              "雑学", "歴史", "shorts"],
        seed=date.toordinal(),
        emojis=list(dict.fromkeys(emojis)),
        max_seconds=float(tc.get("quiz_max_seconds", 100)),
    )
    return plan



# ---------------------------------------------------------------- topics
def plan_topic(date: dt.date, cfg: dict, topics_path: Path, index: int | None = None, slot: int = 0) -> VideoPlan:
    """雑学ネタ帳から1本作る。1日に複数本出すときは slot（0,1,…）で別のネタになる。"""
    topics = yaml.safe_load(topics_path.read_text(encoding="utf-8")) or []
    # months: [12] のような季節ネタは、その月だけ使う
    if index is None:
        topics = [t for t in topics if not t.get("months") or date.month in t["months"]]
    if not topics:
        raise RuntimeError(f"{topics_path} にネタがありません")
    per_day = int(cfg.get("topics_per_day", 2))
    # dates: ["12-24"] のように日付を指定したネタは、その日に優先して使う（1本目のみ）
    md = f"{date.month:02d}-{date.day:02d}"
    pinned = [t for t in topics if md in [str(x) for x in t.get("dates", [])]] if index is None and slot == 0 else []
    if pinned:
        i, t = topics.index(pinned[0]), pinned[0]
    elif index is None and cfg.get("product_ratio") and any(x.get("products") for x in topics):
        # 商品紹介（products: のあるネタ）を product_ratio 日、雑学を 1 日の割合で出す
        ratio = int(cfg["product_ratio"])
        day = date.toordinal() * per_day + slot
        cyc, pos = divmod(day, ratio + 1)
        prods = [x for x in topics if x.get("products")]
        others = [x for x in topics if not x.get("products")] or prods
        t = prods[(cyc * ratio + pos) % len(prods)] if pos < ratio else others[cyc % len(others)]
        i = topics.index(t)
    else:
        i = index if index is not None else date.toordinal() * per_day + slot
        i %= len(topics)
        t = topics[i]

    title = t["title"]
    main_em = t.get("emoji") or illust.pick_one(title, fallback="💡")
    hook = t.get("hook", f"{title}、知ってた？")
    scenes = [Scene(kind="hook", label=t.get("label", "雑学"), text=t.get("hook_text", title), emoji=main_em,
                    narration=_sentence(hook))]
    point_ems = []
    for n, p in enumerate(t["points"], 1):
        if isinstance(p, dict):
            text, narr = p["text"], p.get("narration", p["text"])
            em = p.get("emoji") or illust.pick_one(text, fallback=main_em)
        else:
            text = narr = str(p)
            em = illust.pick_one(text, fallback=main_em)
        point_ems.append(em)
        scenes.append(Scene(kind="item", label=f"その{n}", text=text, emoji=em, narration=_sentence(narr)))
    # 商品紹介用：使ったあとの姿（benefit）と、こんな人におすすめ（for_whom）。尺調整で削られない
    for key, label, default_em in (("benefit", "あると…", "✨"), ("for_whom", "こんな人に", "🙋")):
        b = t.get(key)
        if b:
            scenes.append(Scene(kind="benefit", label=label, text=b["text"], emoji=b.get("emoji", default_em),
                                narration=_sentence(b.get("narration", b["text"]))))
    scenes.append(Scene(kind="outro", label="SEE YOU", text=t.get("outro_text", "チャンネル登録\nしてね！"),
                        emoji="🙌",
                        narration=t.get("outro", cfg.get("outro_narration", "明日もお楽しみに！チャンネル登録よろしくお願いします。"))))

    tags = t.get("tags", ["雑学", "shorts"])
    desc = t.get("description") or "\n".join(
        [t["hook"] if t.get("benefit") and t.get("hook") else f"{title}を紹介します。", ""] + [f"■ {s.text}" for s in scenes if s.kind == "item"] +
        ([""] + [f"▼ {s.narration}" for s in scenes if s.kind == "benefit"] if t.get("benefit") else []) +
        ["", "イラスト：Noto Emoji（Google / SIL Open Font License）", "", " ".join("#" + x for x in tags)])
    return VideoPlan(header=t.get("header", "知ってた？"), subheader=title, scenes=scenes,
                     title=t.get("youtube_title", f"【雑学】{title} #shorts"),
                     description=desc, tags=tags, seed=date.toordinal() * per_day + slot,
                     emojis=list(dict.fromkeys([main_em] + point_ems)),
                     products=list(t.get("products") or []))


def make_plan(source: str, date: dt.date, cfg: dict, root: Path, topic_index: int | None = None,
              slot: int = 0) -> VideoPlan:
    if source == "today":
        return plan_today(date, cfg)
    if source == "poll":
        from . import poll
        return poll.plan_poll(date, cfg, root)
    if source == "topics":
        return plan_topic(date, cfg, root / "topics.yaml", topic_index, slot)
    if source == "auto":
        try:
            return plan_today(date, cfg)
        except Exception as e:  # noqa: BLE001 - 失敗したら手持ちネタで代用
            print(f"[warn] today の作成に失敗したので topics を使います: {e}")
            return plan_topic(date, cfg, root / "topics.yaml", topic_index, slot)
    raise ValueError(f"unknown source: {source}")


def slug(plan: VideoPlan) -> str:
    return re.sub(r"[^\w\-]+", "_", plan.subheader)[:40]
