"""女性ボーカルを作る：音声合成で歌詞を1行まるごと自然に話させ、WORLD（音声分析・合成）で
音程と長さをメロディに合わせて「歌わせる」。

人間らしさのために:
  - 1行まとめて話させる（言葉どうしが自然につながった声を使う）→ 語ごとに切り出して歌に
  - フレーズはひと息で合成（語の間が途切れない）、音程はなめらかにすべる
  - 息つぎの音、ふんわり息っぽい声、長い音は少しふくらませてから抜く、フレーズの終わりは少し下がって消える
  - 歌い出しのタイミングのわずかな揺れ、ビブラートの深さ・速さの揺れ、声色の細かな揺れ
  - サ行の耳ざわりをおさえる

音声合成は Microsoft Edge の読み上げ（edge-tts、無料）。作った声は cache に保存して使い回す。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import ssl
import subprocess
from pathlib import Path

import numpy as np

SR = 44100
FP = 5.0  # WORLD のフレーム間隔（ミリ秒）
CACHE = Path(__file__).resolve().parent.parent / "output" / "voice_cache"


def tts(word: str, voice: str = "en-US-AriaNeural", rate: str = "-10%") -> np.ndarray:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{voice}|{rate}|{word}".encode()).hexdigest()[:16]
    wav = CACHE / f"{key}.wav"
    if not wav.exists():
        import edge_tts
        import edge_tts.communicate as ec
        ca = "/root/.ccr/ca-bundle.crt"
        if Path(ca).exists():
            ec._SSL_CTX = ssl.create_default_context(cafile=ca)
        mp3 = CACHE / f"{key}.mp3"

        async def run():
            c = edge_tts.Communicate(word, voice, rate=rate, proxy=os.environ.get("HTTPS_PROXY"))
            await c.save(str(mp3))
        for attempt in range(4):
            try:
                asyncio.run(run())
                break
            except Exception:
                if attempt == 3:
                    raise
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), str(wav)],
                       check=True)
        mp3.unlink()
    import wave
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768
    # 前後の無音を切る
    fr = 256
    e = np.array([np.sqrt(np.mean(x[i:i + fr] ** 2)) for i in range(0, len(x) - fr, fr)])
    on = np.where(e > e.max() * 0.03)[0]
    if len(on):
        x = x[max(0, on[0] * fr - fr): min(len(x), (on[-1] + 2) * fr)]
    return x


_ANALYSIS: dict = {}


def _norm(w):
    return "".join(c for c in w.lower() if c.isalnum() or c == "'")


def tts_phrase(words, voice, rate="-20%"):
    """1行まるごと話させて、(音声, [(語, 開始秒, 終了秒)]) を返す（キャッシュ）"""
    import json
    CACHE.mkdir(parents=True, exist_ok=True)
    text = " ".join(words)
    key = hashlib.md5(f"phrase|{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    wav, meta = CACHE / f"{key}.wav", CACHE / f"{key}.json"
    if not (wav.exists() and meta.exists()):
        import edge_tts
        import edge_tts.communicate as ec
        ca = "/root/.ccr/ca-bundle.crt"
        if Path(ca).exists():
            ec._SSL_CTX = ssl.create_default_context(cafile=ca)
        mp3 = CACHE / f"{key}.mp3"

        async def run():
            c = edge_tts.Communicate(text, voice, rate=rate, proxy=os.environ.get("HTTPS_PROXY"),
                                     boundary="WordBoundary")
            audio, bounds = b"", []
            async for ch in c.stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    bounds.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
            mp3.write_bytes(audio)
            return bounds
        for attempt in range(4):
            try:
                bounds = asyncio.run(run())
                break
            except Exception:
                if attempt == 3:
                    raise
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), str(wav)],
                       check=True)
        mp3.unlink()
        meta.write_text(json.dumps(bounds))
    import json
    import wave
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768
    return x, json.loads(meta.read_text())


def _world(x):
    import pyworld as pw
    f0, t = pw.harvest(x, SR, f0_floor=70, f0_ceil=700, frame_period=FP)
    sp = pw.cheaptrick(x, f0, t, SR)
    ap = pw.d4c(x, f0, t, SR)
    return f0, sp, ap


def _word_info(f0, sp, ap):
    voiced = np.where(f0 > 0)[0]
    if len(voiced) < 3:
        voiced = np.arange(len(f0))
    v0, v1 = int(voiced[0]), int(voiced[-1])
    power = float(np.mean(np.log(np.sum(sp[v0:v1 + 1], axis=1) + 1e-12)))
    return dict(f0=f0, sp=sp, ap=ap, v0=v0, v1=v1, power=power)


def analyze_word(word: str, voice: str):
    """（予備）1語だけ話させて分析"""
    key = (word, voice)
    if key not in _ANALYSIS:
        _ANALYSIS[key] = _word_info(*_world(tts(word, voice)))
    return _ANALYSIS[key]


def analyze_phrase(words, voice):
    """1行まとめて話させ、語ごとの WORLD パラメータに切り分ける。うまく対応が取れなければ1語ずつにする"""
    key = (tuple(words), voice)
    if key in _ANALYSIS:
        return _ANALYSIS[key]
    try:
        x, bounds = tts_phrase(words, voice)
        if [_norm(b[0]) for b in bounds] != [_norm(w) for w in words]:
            raise ValueError("単語の区切りが合わない")
        f0, sp, ap = _world(x)
        n = len(f0)
        res = []
        for k, (_, st, en) in enumerate(bounds):
            a = int(st * 1000 / FP)
            b = int(en * 1000 / FP) + 4
            if k + 1 < len(bounds):
                b = min(b, int(bounds[k + 1][1] * 1000 / FP) + 2)
            a, b = max(0, a - 2), min(n, max(b, a + 6))
            res.append(_word_info(f0[a:b], sp[a:b], ap[a:b]))
    except Exception:
        res = [analyze_word(w, voice) for w in words]
    _ANALYSIS[key] = res
    return res


def _phrases(lines, gap_beats=0.6):
    """歌詞を息つぎ（休符）ごとのフレーズに分ける"""
    out, cur = [], []
    last_end = None
    for word, notes in lines:
        st = notes[0][0]
        if cur and last_end is not None and st - last_end > gap_beats:
            out.append(cur)
            cur = []
        cur.append((word, notes))
        last_end = notes[-1][0] + notes[-1][1]
    if cur:
        out.append(cur)
    return out


def breath(rng, dur=0.3):
    """息を吸う音"""
    from .compose import highpass, lowpass
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = lowpass(highpass(rng.standard_normal(n), 700), 4200)
    env = np.sin(np.pi * t / dur) ** 1.5
    return x * env * 0.05


def deess(y):
    """サ行（5〜10kHz の強い音）が出たときだけ、その帯域を下げる"""
    from .compose import highpass, lowpass
    band = lowpass(highpass(y, 5000), 10000)
    env = np.sqrt(np.convolve(band ** 2, np.ones(220) / 220, mode="same")) + 1e-7
    thr = np.percentile(env, 85)
    g = np.where(env > thr, (thr / env) ** 0.7, 1.0)
    return y - band * (1 - g)


def sing_phrase(phrase, beat, voice, transpose=0, vib_depth=0.17, seed=0):
    """フレーズ全体をひと息で歌う。戻り値: (開始秒, 音)"""
    import pyworld as pw
    rng = np.random.default_rng(seed)
    # 歌い出しのわずかな揺れ（語ごと）
    words = []
    for w, ns in phrase:
        sh = float(np.clip(rng.normal(0.004, 0.012), -0.02, 0.03))
        words.append((w, [(p * beat + sh, ln * beat, m + transpose) for p, ln, m in ns]))
    info = analyze_phrase([w for w, _ in phrase], voice)
    target_pow = np.mean([a["power"] for a in info])
    maxpre = int(120 / FP)
    t_start = words[0][1][0][0] - (maxpre + 4) * FP / 1000 - 0.35  # 息つぎのぶん早めに
    t_end = words[-1][1][-1][0] + words[-1][1][-1][1] + 0.4
    nfr = int((t_end - t_start) * 1000 / FP) + 1
    nb = info[0]["sp"].shape[1]
    SP = np.full((nfr, nb), 1e-12)
    AP = np.ones((nfr, nb))
    V = np.zeros(nfr, bool)
    GAIN = np.ones(nfr)
    fr = lambda sec: int(round((sec - t_start) * 1000 / FP))  # noqa: E731

    for wi, ((w, notes), a) in enumerate(zip(words, info)):
        f0, sp, ap, v0, v1 = a["f0"], a["sp"], a["ap"], a["v0"], a["v1"]
        n = len(f0)
        pre = min(v0, maxpre)
        post = min(n - 1 - v1, int(110 / FP))
        start = fr(notes[0][0])
        end_note = fr(notes[-1][0] + notes[-1][1])
        if wi + 1 < len(words):
            nxt = words[wi + 1][1][0][0]
            nxt_pre = min(info[wi + 1]["v0"], maxpre)
            end_note = fr(nxt) - nxt_pre if fr(nxt) - nxt_pre - end_note < 30 else end_note
        mid_end = max(start + 6, end_note - post)
        n_mid = mid_end - start
        # 子音の前後にある無音（「k」「t」を閉じている間など）は短くする：歌手は次の音へすぐつなぐ
        ew = np.sum(sp, axis=1)
        thr_e = np.median(ew[v0:v1 + 1]) * 0.004
        pre_idx = np.array([j for j in range(v0 - pre, v0) if ew[j] > thr_e or j >= v0 - 3], dtype=float)
        post_idx = np.array([j for j in range(v1 + 1, v1 + 1 + post) if ew[j] > thr_e], dtype=float)[:int(70 / FP)]
        pre, post = len(pre_idx), len(post_idx)
        mid_end = max(start + 6, end_note - post)
        n_mid = mid_end - start
        # 伸ばすのは母音だけ。語の途中の子音（to-night の n など）は元の長さのまま
        seg_e = ew[v0:v1 + 1]
        vowel = seg_e > np.median(seg_e) * 0.3
        dur = np.where(vowel, 1.0, 0.0)
        cons_frames = (~vowel).sum()
        extra = max(0.0, n_mid - cons_frames)
        dur = np.where(vowel, extra / max(1, vowel.sum()), 1.0)
        if extra <= 0:
            dur = np.full(len(seg_e), n_mid / len(seg_e))
        cum = np.concatenate([[0], np.cumsum(dur)])
        mid_idx = np.interp(np.arange(n_mid) + 0.5, cum, np.arange(len(cum)) + v0 - 0.5).clip(v0, v1)
        idx = np.concatenate([pre_idx, mid_idx, post_idx])
        i0 = np.floor(idx).astype(int).clip(0, n - 1)
        i1 = np.minimum(i0 + 1, n - 1)
        wgt = (idx - i0)[:, None]
        sp2 = sp[i0] * (1 - wgt) + sp[i1] * wgt
        ap2 = ap[i0] * (1 - wgt) + ap[i1] * wgt
        sp2 *= np.exp(target_pow - a["power"])
        # 母音の途中で一瞬だけ「無声」と判定された所（分析の誤り）は、声があることにする
        vsrc = f0 > 0
        run = 0
        for j in range(v0, v1 + 1):
            if not vsrc[j]:
                run += 1
            else:
                if 0 < run <= 8:
                    vsrc[j - run:j] = True
                run = 0
        vflag = vsrc[np.rint(idx).astype(int).clip(0, n - 1)]
        # 声が出ているところの大きさをそろえる（歌手は母音も「r」「l」も同じくらいの大きさで伸ばす）
        e = np.sum(sp2, axis=1) + 1e-12
        if vflag.sum() > 4:
            tgt = np.median(e[vflag])
            g = np.where(vflag, np.clip(tgt / e, 0.25, 12.0) ** 0.85, 1.0)
            ker = np.hanning(9)
            g = np.convolve(np.pad(g, 4, mode="edge"), ker / ker.sum(), mode="valid")
            sp2 *= g[:, None]
        s0 = start - pre
        s1 = min(nfr, s0 + len(idx))
        L = s1 - s0
        xf = np.ones(L)
        k = min(4, L)
        xf[:k] = np.linspace(0.3, 1, k)
        old = SP[s0:s1]
        blend = (old > 1e-10).any(axis=1)[:, None] & (xf[:, None] < 1)
        SP[s0:s1] = np.where(blend, old * (1 - xf[:, None]) + sp2[:L] * xf[:, None], sp2[:L])
        AP[s0:s1] = ap2[:L]
        V[s0:s1] |= vflag[:L]
        if wi + 1 == len(words) or fr(words[wi + 1][1][0][0]) - s1 > 8:
            tail = min(L, 18)
            GAIN[s1 - tail:s1] *= np.linspace(1, 0.05, tail) ** 1.5

    # 声色の細かな揺れ（固まった機械っぽい母音を防ぐ）と、全体の強弱
    SP *= (GAIN ** 2)[:, None]
    # ふんわり息っぽい声：高い周波数ほど息の成分を増やす
    fbin = np.linspace(0, SR / 2, nb)
    airy = np.clip((fbin - 2500) / 6000, 0, 1) * 0.55
    AP = np.maximum(AP, airy[None, :])

    # 目標の音程
    semis = np.full(nfr, np.nan)
    for _, notes in words:
        for p, ln, m in notes:
            semis[fr(p):fr(p + ln)] = m
    idxs = np.where(~np.isnan(semis))[0]
    semis = np.interp(np.arange(nfr), idxs, semis[idxs])
    ker = np.hanning(17)
    ker /= ker.sum()
    semis = np.convolve(np.pad(semis, 8, mode="edge"), ker, mode="valid")
    tt = np.arange(nfr) * FP / 1000
    for _, notes in words:
        for p, ln, m in notes:
            if ln > 0.55:
                a_, b_ = fr(p), fr(p + ln)
                loc = tt[a_:b_] - tt[a_]
                rate = 5.0 + rng.uniform(-0.4, 0.4) + 0.3 * np.sin(2 * np.pi * 0.7 * loc)
                depth = vib_depth * rng.uniform(0.7, 1.2) * np.clip((loc - 0.3) / 0.4, 0, 1)
                semis[a_:b_] += depth * np.sin(2 * np.pi * np.cumsum(rate) * FP / 1000)
    # フレーズの終わりは少し下がって消える
    last_end = fr(words[-1][1][-1][0] + words[-1][1][-1][1])
    k = 30
    semis[max(0, last_end - k):last_end] -= np.linspace(0, 0.7, min(k, last_end)) ** 2
    semis[last_end:] -= 0.7
    drift = np.convolve(rng.standard_normal(nfr), np.hanning(41) / np.hanning(41).sum(), mode="same")
    semis += drift * 0.07
    f0n = np.where(V, 440.0 * 2 ** ((semis - 69) / 12), 0.0)
    y = pw.synthesize(f0n, np.ascontiguousarray(SP), np.ascontiguousarray(AP), SR, frame_period=FP)
    y = deess(y)
    y /= np.percentile(np.abs(y), 99.7) + 1e-9
    y *= 0.7
    # 息つぎ
    br = breath(rng, 0.28)
    bi = max(0, fr(words[0][1][0][0]) * int(SR * FP / 1000) - int(0.45 * SR))
    y[bi:bi + len(br)] += br[: len(y) - bi]
    return t_start, y


def render_lyrics(lines, beat: float, voice="en-US-JennyNeural", transpose: int = 0, vib_depth=0.17, seed=0):
    """lines: [(単語, [(拍位置, 長さ[拍], MIDI), ...]), ...] → [(開始秒, 音)]（フレーズごと）"""
    return [sing_phrase(ph, beat, voice, transpose, vib_depth, seed + k) for k, ph in enumerate(_phrases(lines))]
