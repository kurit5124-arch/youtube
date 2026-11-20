"""台本 → 音声 → 映像 → (アップロード) をまとめて実行する。"""
from __future__ import annotations

import json
from pathlib import Path

from . import render, tts
from .models import VideoPlan


def build_video(plan: VideoPlan, cfg: dict, workdir: Path, out: Path, allow_silent: bool = False) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    font = render.find_font(cfg.get("font"))
    max_len = float(cfg.get("max_seconds", 58))
    gap = float(cfg.get("scene_gap", 0.35))

    # 1) 音声。長すぎたら item シーンを後ろから削る
    audios: list[tuple[Path, float]] = []
    for i, s in enumerate(plan.scenes):
        a = workdir / f"voice_{i:02d}.mp3"
        audios.append((a, tts.synthesize(s.narration, a, cfg, allow_silent) + gap))
    while sum(d for _, d in audios) > max_len:
        items = [i for i, s in enumerate(plan.scenes) if s.kind == "item"]
        if len(items) <= 1:
            break
        drop = items[-1]
        print(f"[info] {max_len}秒に収めるため「{plan.scenes[drop].text[:15]}…」を外します")
        del plan.scenes[drop], audios[drop]

    # 2) スライド画像 + シーンごとの動画
    segs = []
    for i, (s, (a, dur)) in enumerate(zip(plan.scenes, audios)):
        img = workdir / f"scene_{i:02d}.png"
        render.draw_scene(plan, s, i, len(plan.scenes), font, img)
        seg = workdir / f"seg_{i:02d}.mp4"
        render.render_segment(img, a, dur, seg)
        segs.append(seg)

    # 3) 結合・BGM・プログレスバー
    total = sum(d for _, d in audios)
    bgm_dir = Path(cfg.get("bgm_dir", "assets/bgm"))
    bgms = sorted(p for p in bgm_dir.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")) if bgm_dir.exists() else []
    bgm = bgms[plan.seed % len(bgms)] if bgms else None
    out.parent.mkdir(parents=True, exist_ok=True)
    render.finalize(segs, total, out, bgm, float(cfg.get("bgm_volume", 0.12)), render.accent_of(plan))

    meta = {"title": plan.title, "description": plan.description, "tags": plan.tags,
            "duration": round(total, 2), "scenes": [s.__dict__ for s in plan.scenes]}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
