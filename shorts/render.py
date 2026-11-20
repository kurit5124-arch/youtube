"""スライド画像を描いて、音声と合わせて縦型 mp4 にする。"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import Scene, VideoPlan

W, H = 1080, 1920
FPS = 30

# (上の色, 下の色, アクセント色)
PALETTES = [
    ((20, 30, 72), (88, 28, 135), (255, 196, 61)),
    ((6, 78, 59), (15, 23, 42), (52, 211, 153)),
    ((127, 29, 29), (30, 27, 75), (251, 146, 60)),
    ((12, 74, 110), (15, 23, 42), (56, 189, 248)),
    ((76, 29, 149), (190, 24, 93), (253, 224, 71)),
    ((17, 24, 39), (55, 65, 81), (244, 114, 182)),
]

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
]


def find_font(custom: str | None = None) -> str:
    for p in ([custom] if custom else []) + FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    for d in ("assets/fonts", "/usr/share/fonts"):
        for f in sorted(Path(d).rglob("*")) if Path(d).exists() else []:
            if f.suffix.lower() in (".ttf", ".otf", ".ttc") and ("CJK" in f.name or "JP" in f.name or "Gothic" in f.name):
                return str(f)
    raise RuntimeError("日本語フォントが見つかりません。fonts-noto-cjk を入れるか assets/fonts に置いてください")


# 行頭に来てはいけない文字
NO_START = set("、。，．・：；？！ー」』）】〕〉》ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ…")


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            if font.getlength(line + ch) <= max_w or not line or ch in NO_START:
                line += ch
            else:
                lines.append(line)
                line = ch
        lines.append(line)
    return lines


def fit_text(text: str, font_path: str, max_w: int, max_h: int, start: int, minimum: int = 40):
    size = start
    while True:
        font = ImageFont.truetype(font_path, size)
        lines = wrap(text, font, max_w)
        line_h = int(size * 1.35)
        if len(lines) * line_h <= max_h or size <= minimum:
            return font, lines, line_h
        size -= 4


def _gradient(top, bottom) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        px.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def _shadow_text(draw, xy, text, font, fill, anchor="mm", shadow=(0, 0, 0, 160), offset=5):
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=shadow, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def draw_scene(plan: VideoPlan, scene: Scene, idx: int, total: int, font_path: str, out: Path) -> None:
    rng = random.Random(plan.seed)
    top, bottom, accent = PALETTES[rng.randrange(len(PALETTES))]
    img = _gradient(top, bottom).convert("RGBA")

    # 背景の飾り（ぼかした円）
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    for _ in range(7):
        r = rng.randint(120, 380)
        x, y = rng.randint(-100, W + 100), rng.randint(-100, H + 100)
        dd.ellipse([x - r, y - r, x + r, y + r], fill=accent + (rng.randint(25, 60),))
    img = Image.alpha_composite(img, deco.filter(ImageFilter.GaussianBlur(60)))
    d = ImageDraw.Draw(img)

    # 見出し
    head_font = ImageFont.truetype(font_path, 92)
    sub_font = ImageFont.truetype(font_path, 64)
    _shadow_text(d, (W // 2, 300), plan.header, head_font, (255, 255, 255))
    sub_w = sub_font.getlength(plan.subheader) + 80
    d.rounded_rectangle([W / 2 - sub_w / 2, 380, W / 2 + sub_w / 2, 480], radius=50, fill=accent)
    d.text((W // 2, 430), plan.subheader, font=sub_font, fill=top, anchor="mm")

    # 中央カード
    cx0, cy0, cx1, cy1 = 70, 600, W - 70, 1380
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([cx0 + 12, cy0 + 16, cx1 + 12, cy1 + 16], radius=48, fill=(0, 0, 0, 90))
    img = Image.alpha_composite(img, card.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=48, fill=(255, 255, 255, 245))

    if scene.label:
        lf = ImageFont.truetype(font_path, 60)
        lw = lf.getlength(scene.label) + 70
        d.rounded_rectangle([W / 2 - lw / 2, cy0 - 50, W / 2 + lw / 2, cy0 + 50], radius=50, fill=accent)
        d.text((W // 2, cy0), scene.label, font=lf, fill=(20, 20, 30), anchor="mm")

    big = scene.kind in ("hook", "outro")
    if scene.choices:
        # 問題文（カード上部）
        font, lines, lh = fit_text(scene.text, font_path, cx1 - cx0 - 100, 270, start=68, minimum=36)
        y = cy0 + 75 + (270 - len(lines) * lh) / 2 + lh / 2
        for line in lines:
            d.text((W // 2, y), line, font=font, fill=(25, 25, 35), anchor="mm")
            y += lh
        # 選択肢
        cf = ImageFont.truetype(font_path, 66)
        row_h, gap_y = 100, 22
        top = cy0 + 360
        for i, ch in enumerate(scene.choices):
            y0 = top + i * (row_h + gap_y)
            box = [cx0 + 50, y0, cx1 - 50, y0 + row_h]
            if scene.reveal and i == scene.answer:
                d.rounded_rectangle(box, radius=56, fill=(34, 197, 94))
                d.text((box[0] + 60, y0 + row_h / 2), ch, font=cf, fill=(255, 255, 255), anchor="lm")
                d.text((box[2] - 60, y0 + row_h / 2), "正解", font=cf, fill=(255, 255, 255), anchor="rm")
            elif scene.reveal:
                d.rounded_rectangle(box, radius=56, fill=(229, 231, 235))
                d.text((box[0] + 60, y0 + row_h / 2), ch, font=cf, fill=(160, 160, 170), anchor="lm")
            else:
                d.rounded_rectangle(box, radius=56, fill=(243, 244, 246), outline=accent, width=6)
                d.text((box[0] + 60, y0 + row_h / 2), ch, font=cf, fill=(25, 25, 35), anchor="lm")
    else:
        font, lines, lh = fit_text(scene.text, font_path, cx1 - cx0 - 120, cy1 - cy0 - 180,
                                   start=118 if big else 84)
        y = (cy0 + cy1) / 2 - (len(lines) - 1) * lh / 2 + 10
        for line in lines:
            d.text((W // 2, y), line, font=font, fill=(25, 25, 35), anchor="mm")
            y += lh

    if scene.countdown:
        # カウントダウンの数字（カードの下）
        r = 95
        d.ellipse([W / 2 - r, 1500 - r, W / 2 + r, 1500 + r], fill=accent, outline=(255, 255, 255), width=8)
        d.text((W // 2, 1500), str(scene.countdown), font=ImageFont.truetype(font_path, 130),
               fill=(20, 20, 30), anchor="mm")
    elif total <= 10:
        # 何枚目かのドット（下部はショートのUIで隠れるので少し上に）
        dot_y = 1480
        gap = 44
        x0 = W / 2 - (total - 1) * gap / 2
        for i in range(total):
            r = 13 if i == idx else 9
            col = accent + (255,) if i == idx else (255, 255, 255, 120)
            d.ellipse([x0 + i * gap - r, dot_y - r, x0 + i * gap + r, dot_y + r], fill=col)

    img.convert("RGB").save(out)


def _run(cmd: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *cmd], check=True)


def render_segment(image: Path, audio: Path, dur: float, out: Path, zoom: float = 0.06) -> None:
    frames = max(1, int(dur * FPS))
    vf = (f"scale={W * 2}:{H * 2},"
          f"zoompan=z='1+{zoom}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
          "format=yuv420p")
    _run(["-loop", "1", "-framerate", str(FPS), "-i", str(image), "-i", str(audio),
          "-filter_complex", f"[0:v]{vf}[v];[1:a]apad,aresample=44100,aformat=channel_layouts=stereo[a]",
          "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(out)])


def finalize(segments: list[Path], total: float, out: Path, bgm: Path | None, bgm_volume: float, accent) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segments), encoding="utf-8")
    color = "0x%02x%02x%02x" % accent
    inputs = ["-f", "concat", "-safe", "0", "-i", str(lst),
              "-f", "lavfi", "-i", f"color=c={color}:s={W}x14:r={FPS}"]
    # 画面上端に動画全体の進み具合バー
    fc = f"[0:v][1:v]overlay=x='-W+W*t/{total:.3f}':y=0:shortest=1[v]"
    amap = "0:a"
    if bgm:
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        fc += (f";[2:a]volume={bgm_volume},afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[b];"
               "[0:a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        amap = "[a]"
    _run([*inputs, "-filter_complex", fc, "-map", "[v]", "-map", amap, "-t", f"{total:.3f}",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    lst.unlink(missing_ok=True)


def accent_of(plan: VideoPlan):
    return PALETTES[random.Random(plan.seed).randrange(len(PALETTES))][2]
