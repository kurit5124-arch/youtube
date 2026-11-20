"""動画の中身を表すデータ構造。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scene:
    """1枚のスライド（＝ナレーション1区切り）。"""

    text: str            # 画面に大きく出す文字
    narration: str       # 読み上げる文章
    label: str = ""      # カード上部の小見出し（例: 1945年 / その1）
    kind: str = "item"   # hook / item / outro


@dataclass
class VideoPlan:
    """1本のショート動画の設計図。"""

    header: str                  # 画面上部の見出し（例: 今日は何の日？）
    subheader: str               # 見出しの下（例: 11月20日）
    scenes: list[Scene]
    title: str                   # YouTube のタイトル
    description: str             # YouTube の説明文
    tags: list[str] = field(default_factory=list)
    seed: int = 0                # 配色などのランダム要素を固定するため
