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
    group: int = 0       # 同じ問題に属するシーンは同じ番号（尺調整で一緒に外す）
    choices: list[str] = field(default_factory=list)  # クイズの選択肢
    answer: int | None = None    # 正解の番号（reveal のとき強調）
    reveal: bool = False         # 正解発表シーンか
    countdown: int | None = None # カウントダウン表示（3,2,1）
    emoji: str = ""              # 場面のイメージ画像として大きく描く絵文字（例: 😴🔊🥩）
    art: dict = field(default_factory=dict)  # イラストの指定（背景・登場人物・表情。shorts/illust.py）
    sub: str = ""                # 補足（ドキュメンタリー: 場所や話し手）
    badge: str = ""              # reveal のとき正解の選択肢の右に出す文字（既定: 正解）


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
    style: str = "card"          # card = カード型 / documentary = ドキュメンタリー風
    bgm: str = ""                # 使う BGM のファイル名（空なら日替わり）
    category_id: int | None = None  # YouTube のカテゴリ（空なら config.yaml）
    palette: int | None = None      # 配色を固定する（render.PALETTES の番号。空なら日替わり）
