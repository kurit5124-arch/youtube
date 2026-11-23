"""伸びている雑学ショートの定番レイアウトで動画を作る（topics.yaml の style: viral / viral_noir）。

  ┌──────────────────┐
  │ 【犯人の自白】        │ ← シリーズ名（小さめの帯）
  │ 猫が人間に隠してきた   │ ← 動画のタイトル。最初から最後まで出しっぱなし
  │    3つの秘密          │    （太字・黒フチ・キーワードだけ色付き）
  │                    │
  │   ［ 秘密① ］        │
  │      🐈‍⬛ 大きな絵     │ ← 中央に大きなイラスト（ゆっくりズーム）
  │                    │
  │ 字幕が声に合わせて     │ ← 読み上げに合わせて一言ずつ切り替わる字幕
  │ 切り替わる            │    （「」で囲んだ言葉は黄色）
  └──────────────────┘

カード・ページ送りのドットは使わない。シーンの頭に「ドン」という効果音を入れる。
タイトルの {波かっこ} で囲んだ部分は強調色になる。
"""
from __future__ import annotations

import json
import math
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import illust, render, tts
from .models import VideoPlan

W, H, FPS = render.W, render.H, render.FPS

last_total = 0.0  # 直前に作った動画の長さ（秒）

THEMES = {
    # 明るめ（いつもの雑学）
    "viral": {"bg": ((14, 18, 38), (4, 6, 14)), "glow": (90, 120, 255), "hi": (255, 221, 0),
              "tag_bg": (255, 221, 0), "tag_ink": (10, 10, 10), "badge": (255, 60, 60)},
    # 犯人の自白風（黒＋赤い光）
    "viral_noir": {"bg": ((22, 4, 6), (0, 0, 0)), "glow": (200, 20, 30), "hi": (255, 221, 0),
                   "tag_bg": (210, 20, 30), "tag_ink": (255, 255, 255), "badge": (210, 20, 30)},
}

BOLD_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def _font(custom: str | None) -> str:
    for p in BOLD_FONTS:
        if Path(p).exists():
            return p
    return render.find_font(custom)


# ------------------------------------------------------------ 色付き・フチ付き文字
def _runs(text: str, open_: str, close: str) -> list[tuple[str, bool]]:
    """'a{b}c' → [('a',False),('b',True),('c',False)]（open_/close は残さない）"""
    out, hi, buf = [], False, ""
    for ch in text:
        if ch == open_ and not hi:
            out.append((buf, False)); buf, hi = "", True
        elif ch == close and hi:
            out.append((buf, True)); buf, hi = "", False
        else:
            buf += ch
    out.append((buf, hi))
    return [(s, h) for s, h in out if s]


PARTICLES = set("はがをにでのともへやよねな")


def _kind(c: str) -> str:
    if "\u3041" <= c <= "\u309f":
        return "hira"
    if "\u30a0" <= c <= "\u30ff":
        return "kata"
    return "kanji" if "\u4e00" <= c <= "\u9fff" else "other"


def _good_break(prev: str, nxt: str) -> bool:
    """改行してよい位置か（単語の途中で切らない）。"""
    if nxt in "「" or prev in "」":
        return True
    if prev in PARTICLES and _kind(nxt) in ("kanji", "kata", "other"):
        return True
    return _kind(prev) == "hira" and _kind(nxt) in ("kanji", "kata") and prev in PARTICLES | set("てだるい")


def _wrap_runs(runs, font, max_w):
    """色付きの文字列を行に分ける。2行になるときは左右の長さがそろう位置で切る（「」の中では切らない）。"""
    chars = [(ch, h) for s, h in runs for ch in s]
    width = lambda cs: sum(font.getlength(c) for c, _ in cs)
    if any(c == "\n" for c, _ in chars):
        lines, cur = [], []
        for c in chars:
            if c[0] == "\n":
                lines.append(cur); cur = []
            else:
                cur.append(c)
        return lines + [cur]
    if width(chars) <= max_w:
        return [chars]
    best, best_score = None, None
    for i in range(1, len(chars)):
        a, b = chars[:i], chars[i:]
        if b[0][0] in render.NO_START or (a[-1][1] and b[0][1]):  # 行頭禁則・強調の途中
            continue
        score = max(width(a), width(b)) + (0 if _good_break(a[-1][0], b[0][0]) else 2000)
        if max(width(a), width(b)) <= max_w and (best_score is None or score < best_score):
            best, best_score = i, score
    if best is None:  # どうしても入らないときは幅で折り返す（呼び出し側で文字を小さくする）
        return [chars[:len(chars) // 2], chars[len(chars) // 2:], []]
    return [chars[:best], chars[best:]]


def _draw_rich(img, runs, font_path, center_y, max_w, size, hi, stroke, min_size=48, max_lines=2,
               fill=(255, 255, 255), stroke_fill=(0, 0, 0)):
    while True:
        font = ImageFont.truetype(font_path, size)
        lines = [ln for ln in _wrap_runs(runs, font, max_w) if ln] if size <= min_size else _wrap_runs(runs, font, max_w)
        too_wide = any(sum(font.getlength(c) for c, _ in ln) > max_w for ln in lines)
        if (len(lines) <= max_lines and not too_wide) or size <= min_size:
            break
        size -= 4
    d = ImageDraw.Draw(img)
    lh = int(size * 1.22)
    sw = max(4, int(size * stroke))
    y = center_y - (len(lines) - 1) * lh / 2
    for line in lines:
        total = sum(font.getlength(ch) for ch, _ in line)
        x = W / 2 - total / 2
        for ch, h in line:
            d.text((x, y), ch, font=font, fill=hi if h else fill, anchor="lm",
                   stroke_width=sw, stroke_fill=stroke_fill)
            x += font.getlength(ch)
        y += lh


# ------------------------------------------------------------ 背景・固定部分
def _base(plan: VideoPlan, th: dict, font_path: str) -> Image.Image:
    top, bottom = th["bg"]
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        px.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    img = img.convert("RGBA")
    # 中央のスポットライト
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W / 2 - 430, 760 - 430, W / 2 + 430, 760 + 430], fill=th["glow"] + (110,))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(120)))

    # シリーズ名の帯
    d = ImageDraw.Draw(img)
    tf = ImageFont.truetype(font_path, 54)
    tag = plan.header
    tw = tf.getlength(tag) + 70
    d.rounded_rectangle([W / 2 - tw / 2, 150, W / 2 + tw / 2, 236], radius=14, fill=th["tag_bg"])
    d.text((W / 2, 193), tag, font=tf, fill=th["tag_ink"], anchor="mm")
    # タイトル（出しっぱなし）
    _draw_rich(img, _runs(plan.headline or plan.subheader, "{", "}"), font_path, 375, W - 90, 112,
               th["hi"], 0.11, min_size=72, max_lines=2)
    return img


def _scene_layer(base, scene, th, font_path, with_emoji=True):
    img = base.copy()
    d = ImageDraw.Draw(img)
    if scene.label and scene.kind == "item":
        bf = ImageFont.truetype(font_path, 62)
        bw = bf.getlength(scene.label) + 80
        by = 610 if with_emoji else 600  # 3Dのときは猫の頭にかからないよう上に
        d.rounded_rectangle([W / 2 - bw / 2, by - 50, W / 2 + bw / 2, by + 50], radius=50, fill=th["badge"],
                            outline=(255, 255, 255), width=6)
        d.text((W / 2, by), scene.label, font=bf, fill=(255, 255, 255), anchor="mm")
    if scene.emoji and with_emoji:
        em = illust.image(scene.emoji, 540)
        if em:
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sh.alpha_composite(em, (int(W / 2 - em.width / 2) + 14, int(930 - em.height / 2) + 20))
            shadow = sh.split()[3].point(lambda v: int(v * 0.55))
            black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
            black.putalpha(shadow)
            img = Image.alpha_composite(img, black.filter(ImageFilter.GaussianBlur(16)))
            img.alpha_composite(em, (int(W / 2 - em.width / 2), int(930 - em.height / 2)))
    return img


# ------------------------------------------------------------ 字幕のタイミング
PHRASE = re.compile(r"[^、。！？!?…]+[、。！？!?…]*")
PUNCT = "、。！？!?… "


def _chunks(narration: str, words: list[tuple[float, float, str]], dur: float, max_chars: int = 12):
    """ナレーションを短い字幕に分け、各字幕の表示開始秒を単語のタイミングから求める。"""
    parts: list[str] = []
    for seg in PHRASE.findall(narration):
        seg = seg.strip()
        if not seg.strip(PUNCT):
            continue
        # 短すぎる区切り（「声……」など）は前とつなげる
        if parts and len(parts[-1].strip(PUNCT)) + len(seg.strip(PUNCT)) <= 7:
            parts[-1] += seg
            continue
        parts.append(seg)
    # 句読点や記号を除いた文字の位置 → 単語の開始時刻
    plain = lambda s: re.sub(r"[\s、。！？!?…「」『』（）()・〜ー]", "", s)
    pos = 0
    char_time = []
    for off, _, w in words:
        for _c in plain(w):
            char_time.append(off)
    out = []
    for p in parts:
        t = char_time[pos] if pos < len(char_time) else (out[-1][0] + 0.8 if out else 0.0)
        shown = p.rstrip(PUNCT).replace("…", "") if p.rstrip(PUNCT) else p
        out.append((max(0.0, t - 0.05), shown))
        pos += len(plain(p))
    if out:
        out[0] = (0.0, out[0][1])
    return out


def _boom(path: Path) -> None:
    """シーン頭の「ドン」。"""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=55:sample_rate=24000:duration=0.6",
                    "-f", "lavfi", "-i", "anoisesrc=d=0.6:c=brown:r=24000:a=0.6",
                    "-filter_complex", "[0][1]amix=inputs=2:normalize=0,afade=t=out:st=0.02:d=0.55,"
                    "lowpass=f=180,volume=2.2", "-ac", "1", str(path)], check=True)


# ------------------------------------------------------------ 3Dモデル
MODEL_DIR = Path(__file__).resolve().parent.parent / "model3d"
MODEL_PX, MODEL_Y = 1000, 540  # 画面に置く大きさと上端の位置


def _mouth_curve(words, n_frames: int, lead: float) -> list[float]:
    """単語を話している間だけ口をパクパク開ける（0〜1）。"""
    out = []
    for f in range(n_frames):
        t = f / FPS - lead
        v = 0.0
        for off, d, _ in words:
            if off <= t <= off + d + 0.04:
                syl = max(1, round(d / 0.13))  # だいたい1音ごとに1回開く
                v = abs(math.sin(math.pi * syl * (t - off) / max(d, 0.05))) * 0.9
                break
        out.append(round(v, 3))
    return out


def _render_3d(plan: VideoPlan, jobs, workdir: Path, lead: float) -> dict[int, Path]:
    """model3d/render.js で各シーンの3Dアニメーションを透過PNGの連番にする。失敗したらイラストで代用。"""
    html = MODEL_DIR / f"{plan.model3d}.html"
    if not html.exists() or not (MODEL_DIR / "node_modules" / "three").exists():
        print(f"[warn] 3Dモデルを描けません（{html.name} か model3d/node_modules がない。cd model3d && npm ci）。イラストで代用します")
        return {}
    scenes, dirs = [], {}
    for i, (s, _audio, seg_dur, _dur, words) in enumerate(jobs):
        d = workdir / f"model_{i:02d}"
        n = max(1, round(seg_dur * FPS))
        scenes.append({"action": s.anim or "talk", "duration": seg_dur, "out": str(d),
                       "mouth": _mouth_curve(words, n, lead) if (s.anim or "talk") not in ("purr",) else []})
        dirs[i] = d
    job = workdir / "model3d_job.json"
    job.write_text(json.dumps({"model": plan.model3d, "size": MODEL_PX, "fps": FPS, "scenes": scenes}), encoding="utf-8")
    try:
        subprocess.run(["node", str(MODEL_DIR / "render.js"), str(job)], check=True, timeout=1800)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 3Dの描画に失敗したのでイラストで代用します: {e}")
        return {}
    return dirs


# ------------------------------------------------------------ 本体
def build(plan: VideoPlan, cfg: dict, workdir: Path, out: Path, allow_silent: bool = False) -> Path:
    th = THEMES.get(plan.style, THEMES["viral"])
    font_path = _font(cfg.get("font"))
    gap = float(cfg.get("scene_gap", 0.2))
    lead = 0.25  # 「ドン」のあとに声が始まるまで
    base = _base(plan, th, font_path)
    boom = workdir / "boom.wav"
    _boom(boom)

    # 1) 音声と字幕
    jobs = []
    for i, s in enumerate(plan.scenes):
        voice = workdir / f"voice_{i:02d}.mp3"
        dur, words = tts.synthesize_words(s.narration, voice, cfg, allow_silent)
        seg_dur = lead + dur + gap
        audio = workdir / f"audio_{i:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(boom), "-i", str(voice),
                        "-filter_complex", f"[1]adelay={int(lead * 1000)}[v];[0][v]amix=inputs=2:normalize=0:duration=longest,"
                        f"apad,atrim=0:{seg_dur:.3f}", "-ar", "44100", "-ac", "2", str(audio)], check=True)
        jobs.append((s, audio, seg_dur, dur, words))

    # 2) 3Dモデルのアニメーション（声に合わせて口を動かす）
    model_dirs = {}
    if plan.model3d:
        model_dirs = _render_3d(plan, jobs, workdir, lead)

    # 3) 画面を組み立てる
    segs, total = [], 0.0
    for i, (s, audio, seg_dur, dur, words) in enumerate(jobs):
        layer = _scene_layer(base, s, th, font_path, with_emoji=i not in model_dirs)
        caps = _chunks(s.narration, words, dur)
        cap_y = 1470 if model_dirs else 1390
        frames = []
        use3d = i in model_dirs
        if use3d:  # 背景は1枚、字幕は透明な別レイヤー（猫の上に重ねる）
            bgp = workdir / f"bg_{i:02d}.png"
            layer.convert("RGB").save(bgp)
        for k, (t0, text) in enumerate(caps):
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0)) if use3d else layer.copy()
            _draw_rich(img, _runs(text, "「", "」"), font_path, cap_y, W - 80, 118, th["hi"], 0.12,
                       min_size=76, max_lines=2)
            p = workdir / f"scene_{i:02d}_{k:02d}.png"
            (img if use3d else img.convert("RGB")).save(p)
            start = 0.0 if k == 0 else lead + t0
            end = lead + caps[k + 1][0] if k + 1 < len(caps) else seg_dur
            frames.append((p, max(0.1, end - start)))
        lst = workdir / f"frames_{i:02d}.txt"
        lst.write_text("".join(f"file '{p.resolve()}'\nduration {d:.3f}\n" for p, d in frames)
                       + f"file '{frames[-1][0].resolve()}'\n", encoding="utf-8")
        seg = workdir / f"seg_{i:02d}.mp4"
        n = max(1, int(seg_dur * FPS))
        enc = ["-map", "[v]", "-map", "1:a", "-t", f"{seg_dur:.3f}", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(seg)]
        if i in model_dirs:
            # 背景（タイトル・字幕）の上に3Dの猫を重ねる。カメラの動きは3D側でつける
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-i", str(audio), "-framerate", str(FPS), "-i", str(model_dirs[i] / "f_%05d.png"),
                            "-loop", "1", "-framerate", str(FPS), "-i", str(bgp),
                            "-filter_complex",
                            f"[3:v]format=rgba[bg];[2:v]scale={MODEL_PX}:{MODEL_PX}[m];"
                            f"[bg][m]overlay=x=(W-w)/2:y={MODEL_Y}:eof_action=repeat[bm];"
                            f"[0:v]fps={FPS},format=rgba[cap];[bm][cap]overlay=0:0:eof_action=repeat,format=yuv420p[v]",
                            *enc], check=True)
        else:
            # 最初の0.2秒で少し寄って「ドン」と出し、そのあとゆっくりズーム
            z = f"if(lt(on,6),1.06-0.01*on,1+0.04*on/{n})"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-i", str(audio), "-filter_complex",
                            f"[0:v]fps={FPS},scale={W * 2}:{H * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
                            f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},format=yuv420p[v]", *enc], check=True)
        segs.append(seg)
        total += seg_dur
        print(f"[time]   {seg_dur:5.1f}秒  [{s.label}] 字幕{len(caps)}枚" + (f"  3D:{s.anim}" if i in model_dirs else ""))
    print(f"[time] 合計 {total:.1f}秒")

    bgm = Path(plan.bgm) if plan.bgm and Path(plan.bgm).exists() else None
    if bgm is None:
        bdir = Path(cfg.get("bgm_dir", "assets/bgm"))
        bgms = sorted(p for p in bdir.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")) if bdir.exists() else []
        bgm = bgms[plan.seed % len(bgms)] if bgms else None
    vol = plan.bgm_volume if plan.bgm_volume is not None else float(cfg.get("bgm_volume", 0.12))
    out.parent.mkdir(parents=True, exist_ok=True)
    render.finalize(segs, total, out, bgm, vol, th["badge"])
    global last_total
    last_total = total
    return out
