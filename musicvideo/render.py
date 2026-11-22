"""フレームを並列で描いて、音声と合わせて mp4 にする。"""
from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .analyze import Features
from .scene import ImageScene, NeonDriveScene
from .scene_city import SkyCityScene

_scene = None


def _init(kind, W, H, feats, opts):
    global _scene
    cv2.setNumThreads(1)
    if kind == "image":
        _scene = ImageScene(W, H, feats, **opts)
    elif kind == "city":
        _scene = SkyCityScene(W, H, feats, **opts)
    else:
        _scene = NeonDriveScene(W, H, feats, **opts)


def _frame(i: int) -> bytes:
    img = _scene.render(i)
    return (img * 255 + 0.5).astype(np.uint8).tobytes()


def render_video(audio: Path, feats: Features, out: Path, W: int, H: int, kind: str = "neon",
                 opts: dict | None = None, seconds: float | None = None, workers: int | None = None,
                 thumbnail: Path | None = None) -> Path:
    opts = opts or {}
    n = feats.n if seconds is None else min(feats.n, int(seconds * feats.fps))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(feats.fps), "-i", "-",
        "-i", str(audio),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    workers = workers or max(1, (os.cpu_count() or 2))
    ctx = mp.get_context("fork") if hasattr(os, "fork") else mp.get_context()
    # サムネイル用：一番盛り上がる（ドロップ直後の）フレーム
    thumb_i = int(np.argmax(feats.drop[:n] > 0.99)) + int(feats.fps * 1.5) if feats.drop[:n].max() > 0.99 else n // 2
    thumb_i = min(thumb_i, n - 1)
    with ctx.Pool(workers, initializer=_init, initargs=(kind, W, H, feats, opts)) as pool:
        for i, buf in enumerate(pool.imap(_frame, range(n), chunksize=4)):
            proc.stdin.write(buf)
            if thumbnail is not None and i == thumb_i:
                arr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
                cv2.imwrite(str(thumbnail), arr[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 92])
            if i % (feats.fps * 5) == 0:
                print(f"  描画中 {i / feats.fps:5.1f}秒 / {n / feats.fps:.1f}秒", flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg でのエンコードに失敗しました")
    return out
