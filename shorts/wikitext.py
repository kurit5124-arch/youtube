"""Wikipedia のウィキテキストを読み上げ用の普通の文章に変換する。"""
from __future__ import annotations

import re

_REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
_FILE_LINK_RE = re.compile(r"\[\[(?:ファイル|画像|File|Image):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", re.I)
_LINK_RE = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_EXT_LINK_RE = re.compile(r"\[https?://\S+\s*([^\]]*)\]")


def _template(match: re.Match) -> str:
    parts = [p.strip() for p in match.group(1).split("|")]
    name = parts[0].lower()
    if name in ("仮リンク", "ill2", "interlang") and len(parts) > 1:
        return parts[1]
    if name in ("lang", "langwithname") and len(parts) > 2:
        return parts[2]
    if name in ("en", "ruby", "読み仮名", "読み仮名_ruby不使用") and len(parts) > 1:
        return parts[1]
    if name in ("nowrap", "smaller", "small", "large", "big") and len(parts) > 1:
        return parts[1]
    return ""  # 国旗アイコンなどは捨てる


def clean(text: str) -> str:
    text = _COMMENT_RE.sub("", text)
    text = _REF_RE.sub("", text)
    # 入れ子のテンプレートは内側から順に処理
    for _ in range(10):
        new = _TEMPLATE_RE.sub(_template, text)
        if new == text:
            break
        text = new
    text = _FILE_LINK_RE.sub("", text)
    text = _LINK_RE.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), text)
    text = _EXT_LINK_RE.sub(lambda m: m.group(1), text)
    text = _TAG_RE.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"[（(]\s*[)）]", "", text)  # 空になった括弧
    return text.strip()


def sections(wikitext: str) -> dict[str, str]:
    """レベル2見出し（== 見出し ==）ごとに本文を分ける。"""
    result: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in wikitext.splitlines():
        m = re.match(r"^==\s*([^=].*?)\s*==\s*$", line)
        if m:
            if current is not None:
                result[current] = "\n".join(buf)
            current, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if current is not None:
        result[current] = "\n".join(buf)
    return result


_EVENT_RE = re.compile(r"^(紀元前)?\s*(\d{1,4})年\s*(?:[（(][^）)]*[）)])?\s*[-–—ー－]\s*(.+)$")


def parse_events(section_text: str) -> list[tuple[int, str]]:
    """「* [[1945年]] - ○○が起こる。」形式の行を (年, 内容) にする。"""
    events = []
    for raw in section_text.splitlines():
        if not raw.startswith("*") or raw.startswith("**") or raw.startswith("*:"):
            continue
        line = clean(raw.lstrip("* ").strip())
        m = _EVENT_RE.match(line)
        if not m:
            continue
        year = int(m.group(2)) * (-1 if m.group(1) else 1)
        body = m.group(3).strip()
        if body:
            events.append((year, body))
    return events


def parse_observances(section_text: str) -> list[tuple[str, str]]:
    """記念日セクションを (名前, 説明) にする。説明は直後の「*:」行。"""
    items: list[tuple[str, str]] = []
    for raw in section_text.splitlines():
        if raw.startswith("*:") or raw.startswith("**:"):
            if items and not items[-1][1]:
                items[-1] = (items[-1][0], clean(raw.lstrip("*: ").strip()))
        elif raw.startswith("*") and not raw.startswith("**"):
            name = clean(raw.lstrip("* ").strip())
            name = re.sub(r"[（(][^）)]*[）)]\s*$", "", name).strip()  # 末尾の(国名)
            if name:
                items.append((name, ""))
    return items
