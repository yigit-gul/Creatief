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
import edge_tts.communicate as _ec

from . import config
from .getallen import to_spoken

def _mkssml_lang(tc, escaped_text):
    """Zelfde SSML als edge-tts, maar met xml:lang=nl-NL (de <lang>-tag zelf wordt door de dienst geweigerd)."""
    if isinstance(escaped_text, bytes):
        escaped_text = escaped_text.decode("utf-8")
    return (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{config.VOICE_LANG}'>"
        f"<voice name='{tc.voice}'>"
        f"<prosody pitch='{tc.pitch}' rate='{tc.rate}' volume='{tc.volume}'>{escaped_text}</prosody>"
        "</voice></speak>"
    )


if getattr(config, "VOICE_LANG", None):
    _ec.mkssml = _mkssml_lang

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
    # cijfers als Nederlandse woorden: anders leest de meertalige stem "35%" soms in het Frans
    spoken, num_repl = to_spoken(spoken)
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
    return merge_numbers(words, num_repl)


def merge_numbers(words, repl):
    """Uitgeschreven getallen ('vijfendertig', 'procent') terug samenvoegen tot het getoonde token ('35%')."""
    norm = lambda x: re.sub(r"[^\w]", "", x.lower())
    out, i, k = [], 0, 0
    while i < len(words):
        if k < len(repl):
            seq, shown, attach = repl[k]
            n = len(seq)
            if [norm(w["text"]) for w in words[i:i + n]] == [norm(x) for x in seq]:
                if attach and out:  # bv. 'Nasdaq-100': het getal hoort bij het vorige woord
                    out[-1] = {**out[-1], "text": out[-1]["text"] + shown, "end": words[i + n - 1]["end"]}
                else:
                    out.append({"text": shown, "start": words[i]["start"], "end": words[i + n - 1]["end"]})
                i += n
                k += 1
                continue
            # lukt de match niet op deze plek, dan zoeken we verder bij het volgende woord
        out.append(words[i])
        i += 1
    return out


SENT_SPLIT = re.compile(r"(?<=[a-zà-ÿ0-9%€)\]'\"])([.!?])\s+")


def split_sentences(text: str):
    """Zinnen apart houden (afkortingen zoals [TOB|T.O.B.] blijven heel)."""
    out, last = [], 0
    for m in SENT_SPLIT.finditer(text):
        out.append((text[last:m.end(1)].strip(), m.group(1)))
        last = m.end()
    if text[last:].strip():
        rest = text[last:].strip()
        out.append((rest, rest[-1] if rest[-1] in ".!?" else "."))
    return out


def _trim(mp3: Path, words):
    if not words:
        return words
    a, b = max(0.0, words[0]["start"] - 0.03), words[-1]["end"] + 0.06
    trimmed = mp3.with_suffix(".trim.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ss", f"{a:.3f}",
                    "-to", f"{b:.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(trimmed)], check=True)
    trimmed.replace(mp3)
    return [{**w, "start": w["start"] - a, "end": w["end"] - a} for w in words]


def _silences(path: Path, min_dur=0.12):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise=-38dB:d={min_dur}",
                        "-f", "null", "-"], capture_output=True, text=True)
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(st, en))


def synth_scene(text: str, out_mp3: Path):
    """Hele scène in één keer inspreken (met volledige context blijft de meertalige stem Nederlands),
    dan elke stilte tussen zinnen inkorten tot een korte adempauze. Geen lange leespauzes, maar wel
    duidelijke zinsgrenzen (anders klinkt het alsof hij 2 dingen tegelijk zegt)."""
    raw = asyncio.run(_synth(text, out_mp3))
    expected = len(display_text(text).split())
    if len(raw) < 0.85 * expected:  # de dienst gaf soms maar een stuk audio terug, zonder fout
        raise RuntimeError(f"onvolledige audio: {len(raw)}/{expected} woorden")
    words = _trim(out_mp3, raw)
    if not words:
        return words
    # zinsgrenzen markeren via het aantal woorden per zin
    sents = split_sentences(display_text(text))
    norm = lambda x: re.sub(r"[^\w%€]", "", x.lower())
    pos = 0
    for sent, end in sents:
        last = norm(sent.split()[-1]) if sent.split() else ""
        start = pos + max(0, len(sent.split()) - 3)  # niet te vroeg zoeken (zelfde woord kan eerder in de zin staan)
        for j in range(min(start, len(words) - 1), len(words)):  # laatste woord van de zin op naam terugvinden
            if last and (norm(words[j]["text"]) == last or last.endswith(norm(words[j]["text"]) or "#")):
                words[j]["eos"], words[j]["eos_q"], pos = True, end == "?", j + 1
                break
    # stiltes inkorten
    total = duration(out_mp3)
    cuts = []
    for st, en in _silences(out_mp3):
        before = [w for w in words if w["end"] <= en + 0.05 and w["start"] < st + 0.05]
        q = bool(before and before[-1].get("eos_q"))
        target = config.QUESTION_GAP if q else config.SENTENCE_GAP
        if en - st > target + 0.04 and st > 0.05 and en < total - 0.05:
            cuts.append((st + target / 2, en - target / 2))
    if not cuts:
        return words
    keep, last = [], 0.0
    for a, b in cuts:
        keep.append((last, a))
        last = b
    keep.append((last, total))
    filt = [f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[k{i}]" for i, (a, b) in enumerate(keep)]
    filt.append("".join(f"[k{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1[out]")
    tmp = out_mp3.with_suffix(".cut.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_mp3), "-filter_complex", ";".join(filt),
                    "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", str(tmp)], check=True)
    tmp.replace(out_mp3)

    def shift(t):
        return t - sum(min(b, max(t, a)) - a for a, b in cuts if t > a)
    return [{**w, "start": shift(w["start"]), "end": shift(w["end"])} for w in words]


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
                words = synth_scene(scene["say"], mp3)
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
