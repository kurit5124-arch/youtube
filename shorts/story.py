"""実話・解説系のストーリー動画（イラスト＋アニメ風）の台本を stories.yaml から作る。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from .models import Scene, VideoPlan


def _s(text: str) -> str:
    text = text.strip()
    return text if text.endswith(("。", "！", "？", "!", "?", "…")) else text + "。"


def load(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def plan_story(st: dict, date: dt.date) -> VideoPlan:
    scenes: list[Scene] = []
    for n, sc in enumerate(st["scenes"]):
        if sc.get("choices"):
            scenes.append(Scene(kind="case", label=sc.get("label", "あなたはどう思う？"), text=sc["text"],
                                choices=[f"A {sc['choices'][0]}", f"B {sc['choices'][1]}"],
                                narration=_s(sc["narration"])))
        else:
            scenes.append(Scene(kind="hook" if n == 0 else "case", label=sc.get("label", ""), text=sc.get("text", ""),
                                narration=_s(sc["narration"]), art=sc.get("art", {})))
    tags = st.get("tags", ["shorts"])
    return VideoPlan(header=st.get("header", st["title"]), subheader=st.get("subheader", ""), scenes=scenes,
                     title=st.get("youtube_title", st["title"]), description=st.get("description", ""),
                     tags=tags, seed=date.toordinal() + len(st["title"]), style="anime",
                     bgm=st.get("bgm", ""), category_id=st.get("category_id"))
