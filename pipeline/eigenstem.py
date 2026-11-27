"""Eigen stem: een opname van de gebruiker (gsm, voice memo) gebruiken in plaats van de AI-stem.

Werkwijze:
  1. opname omzetten naar wav + lichte ruisonderdrukking,
  2. Whisper schrijft de opname uit met tijd per woord,
  3. die woorden worden uitgelijnd op het script (difflib), zodat elke scène en elke ondertitel
     op het juiste moment komt. De ondertitels tonen de scripttekst (met cijfers), niet Whispers versie.
Het resultaat is dezelfde 'timing' als de AI-stem oplevert, dus de rest van de pipeline werkt ongewijzigd.

Gebruik: zet de opname naast het script als  scripts/<map>/<id>.opname.<m4a|mp3|wav|...>
en bouw zoals altijd: python -m pipeline.build scripts/<map>/<id>.json
"""
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from . import config as C
from .tts import display_text, duration, spoken_text

EXT = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".mp4", ".mov", ".webm", ".caf")


def vind_opname(script_path: Path):
    for ext in EXT:
        p = script_path.with_suffix(f".opname{ext}")
        if p.exists():
            return p
    return None


def _norm(w):
    return re.sub(r"[^\w]", "", w.lower())


def timing_from_recording(script, rec: Path, audio_dir: Path):
    from . import luister
    audio_dir.mkdir(parents=True, exist_ok=True)
    sid = script["id"]
    wav = audio_dir / f"{sid}.wav"
    # mono 48 kHz, lichte ruisonderdrukking, stilte aan begin/einde weg
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(rec), "-ac", "1", "-ar", "48000",
                    "-af", "highpass=f=70,afftdn=nf=-25,silenceremove=start_periods=1:start_threshold=-45dB,"
                           "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                    str(wav)], check=True)
    segs, info = luister.model().transcribe(luister.load_audio(wav), language="nl", word_timestamps=True, beam_size=5)
    heard = [{"w": w.word.strip(), "start": w.start, "end": w.end} for s in segs for w in (s.words or [])]
    if not heard:
        raise RuntimeError("Whisper hoort niets in de opname")

    # scripttokens (zoals getoond in ondertitels) per scène + gesproken vorm om te vergelijken
    toks, scene_of = [], []
    for i, sc in enumerate(script["scenes"]):
        for t in display_text(sc["say"]).split():
            toks.append(t)
            scene_of.append(i)
    spoken_cmp = [_norm(w) for w in spoken_text(" ".join(sc["say"] for sc in script["scenes"])).split()]
    disp_cmp = [_norm(t) for t in toks]
    heard_cmp = [_norm(h["w"]) for h in heard]

    # uitlijnen: eerst op de getoonde tokens (cijfers als '35%'), Whisper schrijft cijfers vaak ook als cijfers
    sm = SequenceMatcher(None, disp_cmp, heard_cmp, autojunk=False)
    t_of = [None] * len(toks)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            t_of[a + k] = (heard[b + k]["start"], heard[b + k]["end"])
    matched = sum(1 for x in t_of if x)
    # ontbrekende tokens: tijd interpoleren tussen de buren
    known = [i for i, x in enumerate(t_of) if x]
    if len(known) < max(5, 0.4 * len(toks)):
        raise RuntimeError(f"opname lijkt niet op het script ({matched}/{len(toks)} woorden herkend)")
    for i in range(len(toks)):
        if t_of[i]:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is None:
            t_of[i] = (max(0, t_of[nxt][0] - 0.3 * (nxt - i)),) * 2
        elif nxt is None:
            t_of[i] = (t_of[prev][1] + 0.3 * (i - prev),) * 2
        else:
            f = (i - prev) / (nxt - prev)
            s = t_of[prev][1] + f * (t_of[nxt][0] - t_of[prev][1])
            t_of[i] = (s, s + 0.2)
    words = [{"text": t, "start": a, "end": max(b, a + 0.08)} for t, (a, b) in zip(toks, t_of)]
    # zinsgrenzen voor de ondertitels
    for i, t in enumerate(toks):
        if t[-1] in ".!?":
            words[i]["eos"] = True
    total = duration(wav)
    starts = []
    for i in range(len(script["scenes"])):
        first = scene_of.index(i)
        starts.append(max(0.0, words[first]["start"] - 0.15) if i else 0.0)
    scenes = [{"start": starts[i], "end": (starts[i + 1] - C.SCENE_GAP) if i + 1 < len(starts) else total}
              for i in range(len(starts))]
    data = {"audio": str(wav.relative_to(C.ROOT)), "duration": total, "scenes": scenes, "words": words,
            "spoken": [spoken_text(sc["say"]) for sc in script["scenes"]], "eigen_stem": True,
            "herkend": round(matched / len(toks), 2)}
    (audio_dir / f"{sid}.timings.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return data
