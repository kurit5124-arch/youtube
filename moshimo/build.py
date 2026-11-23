"""エピソード（episodes/*.yaml）から、声・アニメーション・字幕・BGM 入りの mp4 を作る。

声:
  - voice/<エピソード名>/01.mp3, 02.wav … があれば、それを使う（あなたの録音。番号は beats の順番）
  - 無い行は、音声合成（Edge TTS）で仮の声を作る
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from shorts import tts

from . import shots
from .anim import FPS, H, W, Background, card, glitch, paste_center, text_sprite

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
INK = (30, 30, 45)


# ---------------------------------------------------------------- 音
def load_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def sfx_pop() -> np.ndarray:
    n = int(SR * 0.09)
    t = np.arange(n) / SR
    f = 520 + 900 * t / t[-1]
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 38) * 0.22).astype(np.float32)


def sfx_whoosh() -> np.ndarray:
    n = int(SR * 0.5)
    rng = np.random.default_rng(1)
    noise = rng.standard_normal(n).astype(np.float32)
    k = 40
    noise = np.convolve(noise, np.ones(k) / k, mode="same")  # こもらせる
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return (noise * env * 0.9).astype(np.float32)


def voice_for(i: int, text: str, ep: dict, workdir: Path, voice_dir: Path) -> np.ndarray:
    for ext in (".wav", ".mp3", ".m4a", ".aac", ".ogg"):
        p = voice_dir / f"{i:02d}{ext}"
        if p.exists():
            print(f"[voice] {i:02d}: 録音を使います ({p.name})")
            return load_audio(p)
    key = hashlib.sha1((text + str(ep.get("voice"))).encode()).hexdigest()[:12]
    out = workdir / f"tts_{i:02d}_{key}.mp3"
    if not out.exists():
        tts.synthesize(text, out, {"voice": ep.get("voice", {})})
    return load_audio(out)


# ---------------------------------------------------------------- 字幕
def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[。！？])", text) if p.strip()]
    return parts or [text]


# ---------------------------------------------------------------- 本体
def build(ep_path: Path, out: Path, workdir: Path, preview: tuple[float, float] | None = None) -> Path:
    ep = yaml.safe_load(ep_path.read_text(encoding="utf-8"))
    name = ep_path.stem
    workdir.mkdir(parents=True, exist_ok=True)
    voice_dir = ROOT / "voice" / name
    theme = ep.get("theme", {})
    top, bottom = tuple(theme.get("top", (12, 16, 44))), tuple(theme.get("bottom", (40, 22, 78)))
    accent = tuple(theme.get("accent", (255, 196, 61)))
    bg = Background(top, bottom, accent, seed=ep.get("episode", 1))

    # 1) 声と時間割
    beats = ep["beats"]
    timeline = []  # (start, dur, beat, shot, shot_start, audio)
    t = float(ep.get("lead_in", 0.4))
    shot, shot_start = None, 0.0
    for i, b in enumerate(beats, 1):
        audio = voice_for(i, b["say"], ep, workdir, voice_dir)
        dur = len(audio) / SR + float(b.get("pause", ep.get("pause", 0.35)))
        if b.get("shot"):
            shot, shot_start = b["shot"], t
        timeline.append({"start": t, "dur": dur, "beat": b, "shot": shot, "shot_start": shot_start, "audio": audio})
        t += dur
    total = t + float(ep.get("tail", 1.2))
    print(f"[moshimo] {name}: {len(beats)}行 / {total / 60:.1f}分")

    # 2) 音（声＋効果音）
    track = np.zeros(int(total * SR) + SR, dtype=np.float32)
    pop, whoosh = sfx_pop(), sfx_whoosh()
    for k, seg in enumerate(timeline):
        s0 = int(seg["start"] * SR)
        track[s0:s0 + len(seg["audio"])] += seg["audio"]
        if seg["beat"].get("shot"):
            fx = whoosh if seg["shot"].get("type") == "chapter" else pop
            p0 = max(0, s0 - int(0.08 * SR))
            track[p0:p0 + len(fx)] += fx
    track = np.clip(track, -1, 1)
    wav = workdir / "voice_sfx.f32"
    track.tofile(wav)

    # 3) 映像（1コマずつ描いて ffmpeg に流す）
    hud_label = ep.get("hud_label", "")
    tag = ep.get("tag", f"もしもシリーズ #{ep.get('episode', 1)}")
    vid_only = workdir / "video.mp4"
    f0, f1 = 0, int(total * FPS)
    if preview:
        f0, f1 = int(preview[0] * FPS), int(min(total, preview[1]) * FPS)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", str(vid_only)], stdin=subprocess.PIPE)
    prev_frame, prev_shot_start, switch_from = None, None, None
    hud_value, hud_changed = None, -10.0
    seg_i = 0
    for fr in range(f0, f1):
        now = fr / FPS
        while seg_i + 1 < len(timeline) and timeline[seg_i + 1]["start"] <= now:
            seg_i += 1
        seg = timeline[seg_i] if now >= timeline[0]["start"] else None
        b = seg["beat"] if seg else {}
        if seg and "hud" in b and b["hud"] != hud_value:
            hud_value, hud_changed = b["hud"], seg["start"]
        img = bg.frame(now)
        if seg and seg["shot"]:
            if seg["shot_start"] != prev_shot_start:
                switch_from, prev_shot_start = prev_frame, seg["shot_start"]
            shots.draw(img, seg["shot"], now - seg["shot_start"], accent)
        # 場面の切りかえはふわっと（見出し・字幕はこのあと上に描くので混ざらない）
        if switch_from is not None and seg:
            k = (now - seg["shot_start"]) / 0.25
            if k < 1:
                img = Image.blend(switch_from, img, max(0.0, k))
            else:
                switch_from = None
        prev_frame = img.copy()
        # 見出し（左上：経過時間などのメーター、右上：シリーズ名）
        if hud_value:
            pulse = 1 + 0.18 * max(0.0, 1 - (now - hud_changed) / 0.35)
            hud = text_sprite(f"{hud_label}  {hud_value}" if hud_label else hud_value, 46, accent, 0)
            box = card(hud.width + 60, 86, (15, 15, 30, 200), 43)
            x, y = 50 + box.width / 2, 40 + box.height / 2
            paste_center(img, box, x, y, pulse)
            paste_center(img, hud, x - 12, y - 14, pulse)
        tg = text_sprite(tag, 34, (255, 255, 255, 190), 0)
        img.alpha_composite(tg, (W - tg.width - 50, 52))
        # 字幕
        if seg and seg["audio"] is not None:
            sents = split_sentences(b["say"])
            total_chars = sum(len(s) for s in sents)
            speech = len(seg["audio"]) / SR
            local = now - seg["start"]
            acc, cur = 0.0, sents[-1]
            for s in sents:
                acc += speech * len(s) / total_chars
                if local < acc:
                    cur = s
                    break
            sub = text_sprite(cur.replace("*", ""), 52, (255, 255, 255), 7, INK, max_w=1650)
            band = card(sub.width + 60, sub.height + 16, (0, 0, 0, 110), 24)
            img.alpha_composite(band, (int(W / 2 - (sub.width + 60) / 2), int(H - 40 - sub.height - 16)))
            img.alpha_composite(sub, (int(W / 2 - sub.width / 2), int(H - 40 - sub.height - 8)))
        # 効果
        for fx in b.get("fx", []) if seg else []:
            local = now - seg["start"]
            if fx["type"] == "glitch":
                img = glitch(img, fr, float(fx.get("strength", 1.0)))
            elif fx["type"] == "blackout" and fx["at"] <= local < fx["at"] + fx["dur"]:
                img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        enc.stdin.write(img.convert("RGB").tobytes())
        if fr % (FPS * 30) == 0:
            print(f"[moshimo]   {now / 60:.1f}分 / {total / 60:.1f}分")
    enc.stdin.close()
    enc.wait()

    # 4) 声・効果音・BGM を重ねて完成
    out.parent.mkdir(parents=True, exist_ok=True)
    a0 = f0 / FPS
    dur = (f1 - f0) / FPS
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(vid_only),
           "-ss", f"{a0:.3f}", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(wav)]
    bgm = ROOT / ep.get("bgm", "assets/bgm/02_chill_lofi.mp3")
    if bgm.exists():
        vol = float(ep.get("bgm_volume", 0.09))
        cmd += ["-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
                f"[2:a]volume={vol},afade=t=out:st={max(0, dur - 2):.2f}:d=2[b];"
                "[1:a][b]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out
