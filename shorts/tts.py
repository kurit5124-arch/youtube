"""無料の音声合成（Edge TTS）。使えないときは無音で代用する。"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


async def _edge(text: str, out: Path, voice: str, rate: str, pitch: str) -> None:
    import edge_tts

    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out))


def _silent(text: str, out: Path) -> None:
    secs = max(1.5, len(text) * 0.13)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{secs:.2f}", "-c:a", "libmp3lame", str(out)],
        check=True,
    )


def synthesize(text: str, out: Path, cfg: dict, allow_silent: bool = False) -> float:
    """text を out (mp3) に保存して長さ（秒）を返す。"""
    vc = cfg.get("voice", {})
    try:
        for attempt in range(3):
            try:
                asyncio.run(_edge(text, out, vc.get("name", "ja-JP-NanamiNeural"),
                                  vc.get("rate", "+15%"), vc.get("pitch", "+0Hz")))
                if out.exists() and out.stat().st_size > 0:
                    break
            except Exception:
                if attempt == 2:
                    raise
        else:
            raise RuntimeError("音声が空でした")
    except Exception as e:  # noqa: BLE001
        if not allow_silent:
            raise RuntimeError(f"音声合成に失敗しました: {e}") from e
        print(f"[warn] 音声合成できないので無音で代用します ({type(e).__name__})")
        _silent(text, out)
    return duration(out)
