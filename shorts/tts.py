"""無料の音声合成。

engine: voicevox … VOICEVOX（ずんだもん など）。VOICEVOX ENGINE を起動しておく（GitHub Actions では自動）
        edge     … Edge TTS（Microsoft の読み上げ）
使えないときは Edge TTS → Open JTalk → 無音 の順に代用する。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

# VOICEVOX の話者 ID（style id）。ほかの声は http://127.0.0.1:50021/speakers で確認できます
VOICEVOX_SPEAKERS = {
    "ずんだもん": 3, "ずんだもん（あまあま）": 1, "ずんだもん（ツンツン）": 7,
    "四国めたん": 2, "春日部つむぎ": 8, "雨晴はう": 10, "玄野武宏": 11, "青山龍星": 13,
}


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


async def _edge(text: str, out: Path, voice: str, rate: str, pitch: str) -> None:
    import edge_tts

    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out))


def _openjtalk(text: str, out: Path, speed: float) -> None:
    """オフラインの音声合成（pip install pyopenjtalk-plus）。Edge TTS に繋がらないときの代わり。"""
    import wave

    import numpy as np
    import pyopenjtalk

    x, sr = pyopenjtalk.tts(text, speed=speed)
    wav = out.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", str(out)], check=True)
    wav.unlink(missing_ok=True)


def _voicevox(text: str, out: Path, vc: dict) -> None:
    import requests

    url = os.environ.get("VOICEVOX_URL", vc.get("voicevox_url", "http://127.0.0.1:50021")).rstrip("/")
    sp = vc.get("speaker", "ずんだもん")
    speaker = sp if isinstance(sp, int) else VOICEVOX_SPEAKERS[sp]
    q = requests.post(f"{url}/audio_query", params={"text": text, "speaker": speaker}, timeout=60)
    q.raise_for_status()
    query = q.json()
    query["speedScale"] = float(vc.get("speed", 1.15))
    query["pitchScale"] = float(vc.get("pitch_scale", 0.0))
    query["intonationScale"] = float(vc.get("intonation", 1.2))
    query["prePhonemeLength"] = 0.05
    query["postPhonemeLength"] = 0.1
    r = requests.post(f"{url}/synthesis", params={"speaker": speaker}, json=query, timeout=120)
    r.raise_for_status()
    wav = out.with_suffix(".wav")
    wav.write_bytes(r.content)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                   check=True)
    wav.unlink(missing_ok=True)


def is_voicevox(cfg: dict) -> bool:
    return cfg.get("voice", {}).get("engine", "edge") == "voicevox"


def credit(cfg: dict) -> str:
    """VOICEVOX の利用規約で必要なクレジット表記（例: VOICEVOX:ずんだもん）。"""
    if not is_voicevox(cfg):
        return ""
    sp = cfg.get("voice", {}).get("speaker", "ずんだもん")
    name = next((k for k, v in VOICEVOX_SPEAKERS.items() if v == sp), sp) if isinstance(sp, int) else sp
    return f"VOICEVOX:{str(name).split('（')[0]}"


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
    if is_voicevox(cfg):
        try:
            _voicevox(text, out, vc)
            return duration(out)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] VOICEVOX が使えないので別の声で代用します ({type(e).__name__}: {e})")
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
        try:
            _openjtalk(text, out, float(vc.get("fallback_speed", 1.15)))
            print(f"[warn] Edge TTS が使えないので Open JTalk で読み上げます ({type(e).__name__})")
            return duration(out)
        except ImportError:
            pass
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
