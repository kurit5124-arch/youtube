"""背景（動く絵）の種類と、毎回ちがう背景を選ぶしくみ。"""
from __future__ import annotations

import json
import random
from pathlib import Path

SCENE_NAMES = ["neon", "city", "aurora", "space"]
# 背景ごとの、似合う色味（色相を回す角度）の候補
HUES = {"neon": [0, -45, 20], "city": [0, 20, -40], "aurora": [0, -20, 25], "space": [0, 0, 15]}
HISTORY = Path(__file__).resolve().parent.parent / "output" / ".scene_history.json"


def get_scene_class(name):
    if name == "neon":
        from .scene import NeonDriveScene
        return NeonDriveScene
    if name == "city":
        from .scene_city import SkyCityScene
        return SkyCityScene
    if name == "aurora":
        from .scene_aurora import AuroraScene
        return AuroraScene
    if name == "space":
        from .scene_space import SpaceScene
        return SpaceScene
    raise ValueError(name)


def choose(requested: str | None, hue: float | None, visual_seed: int | None):
    """auto なら前回と違う背景を選ぶ。色味と配置（山・ビルの形など）も毎回ランダム。"""
    hist = []
    try:
        hist = json.loads(HISTORY.read_text())
    except Exception:
        pass
    rnd = random.Random()
    if requested in (None, "auto"):
        recent = hist[-2:]
        cands = [s for s in SCENE_NAMES if s not in recent] or SCENE_NAMES
        name = rnd.choice(cands)
    else:
        name = requested
    if hue is None:
        hue = float(rnd.choice(HUES[name]))
    if visual_seed is None:
        visual_seed = rnd.randrange(1, 10 ** 6)
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps((hist + [name])[-10:]))
    except Exception:
        pass
    return name, hue, visual_seed
