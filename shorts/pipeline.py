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

    # 1) 音声。長すぎたら item シーン（クイズなら1問まるごと）を後ろから削る
    audios: list[tuple[Path, float]] = []
    for i, s in enumerate(plan.scenes):
        a = workdir / f"voice_{i:02d}.mp3"
        if s.countdown:
            tts.tick(a, high=s.countdown == 1)
            audios.append((a, 1.0))
        elif s.reveal:
            dur = tts.synthesize(s.narration, a, cfg, allow_silent)
            tts.prepend_chime(a)
            audios.append((a, dur + 0.6 + gap + 0.5))  # 正解を見せる時間を少し長めに
        else:
            audios.append((a, tts.synthesize(s.narration, a, cfg, allow_silent) + gap))
    # 長すぎたら、まず「なくても成り立つ場面」（kind=optional）を外す
    while sum(d for _, d in audios) > max_len and any(s.kind == "optional" for s in plan.scenes):
        i = max(i for i, s in enumerate(plan.scenes) if s.kind == "optional")
        print(f"[info] {max_len}秒に収めるため「{plan.scenes[i].label}」の場面を外します")
        del plan.scenes[i], audios[i]
    while sum(d for _, d in audios) > max_len:
        items = [i for i, s in enumerate(plan.scenes) if s.kind == "item"]
        groups = sorted({plan.scenes[i].group for i in items})
        if len(items) <= 1 or (groups != [0] and len(groups) <= 1):
            break
        drop = [i for i in items if plan.scenes[i].group == groups[-1]] if groups != [0] else [items[-1]]
        print(f"[info] {max_len}秒に収めるため「{plan.scenes[drop[0]].text[:15]}…」を外します")
        for i in reversed(drop):
            del plan.scenes[i], audios[i]

    # 2) スライド画像 + シーンごとの動画
    segs = []
    for i, (s, (a, dur)) in enumerate(zip(plan.scenes, audios)):
        seg = workdir / f"seg_{i:02d}.mp4"
        if plan.style == "anime":
            from . import anime
            anime.render_segment(plan, s, i, len(plan.scenes), font, a, dur, seg, cfg)
        else:
            img = workdir / f"scene_{i:02d}.png"
            render.draw_scene(plan, s, i, len(plan.scenes), font, img)
            render.render_segment(img, a, dur, seg, zoom=0.0 if s.choices else 0.06)
        segs.append(seg)

    # 3) 結合・BGM・プログレスバー
    total = sum(d for _, d in audios)
    bgm_dir = Path(cfg.get("bgm_dir", "assets/bgm"))
    bgms = sorted(p for p in bgm_dir.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")) if bgm_dir.exists() else []
    bgm = None
    if plan.bgm:  # ファイル名（assets/bgm の中）か、パスで指定
        bgm = Path(plan.bgm) if Path(plan.bgm).is_file() else next((p for p in bgms if p.name == plan.bgm), None)
    bgm = bgm or (bgms[plan.seed % len(bgms)] if bgms else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    render.finalize(segs, total, out, bgm, float(cfg.get("bgm_volume", 0.12)), render.accent_of(plan))

    meta = {"title": plan.title, "description": plan.description, "tags": plan.tags,
            "duration": round(total, 2), "scenes": [s.__dict__ for s in plan.scenes]}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
