"""無料の音声合成（Edge TTS）。使えないときは無音で代用する。"""
from __future__ import annotations

import asyncio
import os
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

    ca = os.environ.get("SSL_CERT_FILE")
    if ca and os.path.exists(ca):  # 社内プロキシなど独自の証明書がある環境向け
        import ssl

        import edge_tts.communicate as comm
        comm._SSL_CTX = ssl.create_default_context(cafile=ca)
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
        if vc.get("filter"):  # 声の加工（例: 犯人風に少し響かせる）
            tmp = out.with_name(out.stem + "_f.mp3")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-af", vc["filter"],
                            "-c:a", "libmp3lame", str(tmp)], check=True)
            tmp.replace(out)
    except Exception as e:  # noqa: BLE001
        if not allow_silent:
            raise RuntimeError(f"音声合成に失敗しました: {e}") from e
        print(f"[warn] 音声合成できないので無音で代用します ({type(e).__name__})")
        _silent(text, out)
    return duration(out)


def tick(out: Path, high: bool = False) -> None:
    """カウントダウンの「ピッ」（1秒）。"""
    f = 1320 if high else 880
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency={f}:sample_rate=24000:duration=0.09",
         "-af", "afade=t=out:st=0.03:d=0.06,volume=0.5,apad=whole_dur=1.0",
         "-ac", "1", "-c:a", "libmp3lame", str(out)],
        check=True,
    )


def prepend_chime(path: Path) -> None:
    """正解発表の「ピンポン」を音声の頭に付ける（0.6秒）。"""
    tmp = path.with_name(path.stem + "_c.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=988:sample_rate=24000:duration=0.18",
         "-f", "lavfi", "-i", "sine=frequency=784:sample_rate=24000:duration=0.42",
         "-i", str(path),
         "-filter_complex",
         "[0]afade=t=out:st=0.1:d=0.08,volume=0.45[a];[1]afade=t=out:st=0.1:d=0.3,volume=0.45[b];"
         "[2]aresample=24000,aformat=channel_layouts=mono[c];[a][b][c]concat=n=3:v=0:a=1[o]",
         "-map", "[o]", "-c:a", "libmp3lame", str(tmp)],
        check=True,
    )
    tmp.replace(path)
