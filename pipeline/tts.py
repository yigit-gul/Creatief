"""Voice-over met edge-tts, per scène, met woordtimings voor de ondertitels.

Uitspraakhulp: schrijf in de tekst `[TOB|T.O.B.]` om op scherm/ondertitel
"TOB" te tonen maar "T.O.B." te laten uitspreken.
"""
import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

import edge_tts

from . import config

PRON = re.compile(r"\[([^\]|]+)\|([^\]]+)\]")


def split_pronunciation(text: str):
    """Geeft (gesproken tekst, mapping gesproken->getoond)."""
    mapping = {}

    def repl(m):
        shown, spoken = m.group(1), m.group(2)
        for s_tok, d_tok in zip(spoken.split(), shown.split() + [""] * 10):
            mapping[s_tok.strip(".,!?")] = d_tok
        return spoken

    return PRON.sub(repl, text), mapping


def display_text(text: str) -> str:
    return PRON.sub(lambda m: m.group(1), text)


SENT_END = re.compile(r"(?<=[a-zà-ÿ0-9%€])[.!](?=\s)")


def flowing(text: str) -> str:
    """Punten en uitroeptekens midden in een scène worden komma's: de stem leest dan niet
    zin per zin met een lange pauze, maar praat door zoals in een TikTok. Vraagtekens blijven
    (intonatie), afkortingen zoals T.O.B. blijven ongemoeid."""
    return SENT_END.sub(",", text) if config.FLOW_SENTENCES else text


async def _synth(text: str, out_mp3: Path):
    spoken, mapping = split_pronunciation(text)
    spoken = flowing(spoken).replace("&", " en ")  # "&" breekt de spraakdienst (bv. S&P -> "S en P")
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    com = edge_tts.Communicate(
        spoken, config.VOICE, rate=config.VOICE_RATE, pitch=config.VOICE_PITCH,
        boundary="WordBoundary", proxy=proxy,
    )
    words = []
    with open(out_mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                tok = ch["text"]
                core = tok.strip(".,!?")
                if core in mapping:
                    tok = tok.replace(core, mapping[core]) if mapping[core] else ""
                if tok:
                    words.append({
                        "text": tok,
                        "start": ch["offset"] / 1e7,
                        "end": (ch["offset"] + ch["duration"]) / 1e7,
                    })
    return words


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def synthesize_script(script: dict, audio_dir: Path) -> dict:
    """Maakt per scène audio, plakt alles aan elkaar en geeft een timeline terug."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    sid = script["id"]
    parts, timeline, all_words = [], [], []
    t = 0.0
    for i, scene in enumerate(script["scenes"]):
        mp3 = audio_dir / f"{sid}_s{i:02d}.mp3"
        for attempt in range(4):
            try:
                words = asyncio.run(_synth(scene["say"], mp3))
                break
            except Exception as e:  # netwerkhapering: opnieuw proberen
                print(f"  scène {i}: poging {attempt + 1} mislukt ({type(e).__name__})", flush=True)
                if attempt == 3:
                    raise
                time.sleep(2 + 3 * attempt)
        if words:  # stilte voor het eerste en na het laatste woord wegknippen
            a, b = max(0.0, words[0]["start"] - 0.04), words[-1]["end"] + 0.10
            trimmed = mp3.with_suffix(".trim.mp3")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ss", f"{a:.3f}",
                            "-to", f"{b:.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(trimmed)], check=True)
            trimmed.replace(mp3)
            words = [{**w, "start": w["start"] - a, "end": w["end"] - a} for w in words]
        d = duration(mp3)
        timeline.append({"start": t, "end": t + d})
        all_words += [{**w, "start": w["start"] + t, "end": w["end"] + t} for w in words]
        parts.append(mp3)
        t += d + config.SCENE_GAP

    # Alles samenvoegen tot één wav-spoor met stiltes tussen de scènes
    full = audio_dir / f"{sid}.wav"
    inputs, filt = [], []
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        filt.append(f"[{i}:a]aresample=48000,apad=pad_dur={config.SCENE_GAP}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(parts))) +
                f"concat=n={len(parts)}:v=0:a=1[out]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                    "-filter_complex", ";".join(filt), "-map", "[out]", str(full)],
                   check=True)
    for p in parts:
        p.unlink()

    data = {"audio": str(full.relative_to(config.ROOT)), "duration": duration(full),
            "scenes": timeline, "words": all_words}
    (audio_dir / f"{sid}.timings.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return data
