"""Voice-over met edge-tts, per scène, met woordtimings voor de ondertitels.

Uitspraakhulp: schrijf in de tekst `[TOB|T.O.B.]` om op scherm/ondertitel
"TOB" te tonen maar "T.O.B." te laten uitspreken.
"""
import asyncio
import json
import os
import re
import shutil
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


SENT_END = re.compile(r"(?<=[a-zà-ÿ0-9%€)\]'\"])[.!?](?=\s)")


def flowing(text: str) -> str:
    """Elke scène wordt één doorlopende zin (. ! ? midden in de scène -> komma).
    Belangrijk: de meertalige stem bepaalt de taal PER ZIN. Een korte losse zin ("Plus 35%.")
    werd soms Frans of Engels. Als één lange Nederlandse zin blijft het altijd Nederlands.
    De pauzes op de zinsgrenzen voegt synth_scene daarna zelf toe."""
    if not config.FLOW_SENTENCES:
        return text
    text = re.sub(r"(?<=\.)\.(?=\s)", ",", text)  # 'T.O.B..' (afkorting + punt) -> 'T.O.B.,'
    return SENT_END.sub(",", text)


async def _synth(text: str, out_mp3: Path, flow: bool = True):
    spoken, mapping = split_pronunciation(text)
    spoken = (flowing(spoken) if flow else spoken).replace("&", " en ")  # "&" breekt de spraakdienst (bv. S&P -> "S en P")
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


def synth_scene(text: str, out_mp3: Path, raw=None, flow: bool = True):
    """Hele scène in één keer inspreken (met volledige context blijft de meertalige stem Nederlands),
    dan elke stilte tussen zinnen inkorten tot een korte adempauze. Geen lange leespauzes, maar wel
    duidelijke zinsgrenzen (anders klinkt het alsof hij 2 dingen tegelijk zegt)."""
    if raw is None:
        raw = asyncio.run(_synth(text, out_mp3, flow))
    expected = len(display_text(text).split())
    if len(raw) < 0.85 * expected:  # de dienst gaf soms maar een stuk audio terug, zonder fout
        raise RuntimeError(f"onvolledige audio: {len(raw)}/{expected} woorden")
    if duration(out_mp3) < 0.18 * expected or (raw and duration(out_mp3) < raw[-1]["start"]):
        raise RuntimeError(f"audio te kort: {duration(out_mp3):.1f} s voor {expected} woorden")
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
            wt = norm(words[j]["text"])
            if last and (wt == last or (words[j]["text"].startswith("-") and last.endswith(wt))):
                words[j]["eos"], words[j]["eos_q"], pos = True, end == "?", j + 1
                words[j]["eos_len"] = len(sent.split())
                break
    # korte stilte invoegen op elke zinsgrens (behalve na de laatste zin)
    total = duration(out_mp3)
    sil = _silences(out_mp3, 0.05)
    inserts = []
    for w, nxt in zip(words, words[1:]):
        if not w.get("eos"):
            continue
        # gevarieerde pauzes zoals bij praten: korte uitroep -> korte pauze, vraag -> iets langer
        target = (config.QUESTION_GAP if w.get("eos_q")
                  else config.SHORT_GAP if w.get("eos_len", 9) <= 3 else config.SENTENCE_GAP)
        lo, hi = w["end"] - 0.35, nxt["start"] + 0.05
        real = [(st, en) for st, en in sil if en > lo and st < hi]
        have = max((en - st for st, en in real), default=0.0)
        at = (max(real, key=lambda x: x[1] - x[0]) if real else None)
        at = (at[0] + at[1]) / 2 if at else (w["end"] + nxt["start"]) / 2
        if target - have > 0.03 and 0.05 < at < total - 0.05:
            inserts.append((at, target - have))
    if not inserts:
        return words
    inserts.sort()
    pts = [0.0] + [a for a, _ in inserts] + [total]
    filt, labels = [], []
    for i in range(len(pts) - 1):
        filt.append(f"[0:a]atrim={pts[i]:.3f}:{pts[i + 1]:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                    f"aformat=channel_layouts=mono[s{i}]")
        labels.append(f"[s{i}]")
        if i < len(inserts):
            filt.append(f"anullsrc=r=48000:cl=mono,atrim=0:{inserts[i][1]:.3f}[z{i}]")
            labels.append(f"[z{i}]")
    filt.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    tmp = out_mp3.with_suffix(".pause.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_mp3), "-filter_complex", ";".join(filt),
                    "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", str(tmp)], check=True)
    tmp.replace(out_mp3)

    def shift(t):
        return t + sum(d for a, d in inserts if t > a)
    return [{**w, "start": shift(w["start"]), "end": shift(w["end"])} for w in words]


def synth_all(scenes, audio_dir: Path, sid: str):
    """HET HELE SCRIPT IN ÉÉN KEER INSPREKEN en daarna per scène opknippen.
    De meertalige stem kiest de taal per stuk tekst: een korte scène ("Ken je die vriend...") werd soms
    Engels. Met het volledige script als context blijft hij Nederlands (gecontroleerd met de luistertest)."""
    full = audio_dir / f"{sid}_full.mp3"
    text = " ".join(sc["say"].strip() for sc in scenes)
    for attempt in range(7):
        try:
            raw = asyncio.run(_synth(text, full))
            exp = len(display_text(text).split())
            if len(raw) < 0.85 * exp or duration(full) < 0.18 * exp:
                raise RuntimeError(f"onvolledige audio: {len(raw)}/{exp} woorden")
            break
        except Exception as e:
            print(f"  volledig script: poging {attempt + 1} mislukt ({type(e).__name__})", flush=True)
            if attempt == 6:
                raise
            time.sleep(4 + 4 * attempt)
    norm = lambda x: re.sub(r"[^\w%€]", "", x.lower())
    # laatste woord van elke scène terugvinden -> knippunt net voor het eerste woord van de volgende scène
    bounds, pos, count = [], 0, 0
    for sc in scenes[:-1]:
        toks = display_text(sc["say"]).split()
        count += len(toks)
        last = norm(toks[-1])
        for j in range(max(pos, count - 4), len(raw) - 1):
            wt = norm(raw[j]["text"])
            if wt == last or (raw[j]["text"].startswith("-") and last.endswith(wt)):
                bounds.append(j)
                pos = j + 1
                break
        else:
            raise RuntimeError(f"scènegrens niet gevonden na '{toks[-1]}'")
    total = duration(full)
    cuts = [0.0] + [max(raw[j]["end"] - 0.25, raw[j + 1]["start"] - 0.03) for j in bounds] + [total]
    edges = [0] + [j + 1 for j in bounds] + [len(raw)]
    out = []
    for i in range(len(scenes)):
        a, b = cuts[i], cuts[i + 1]
        mp3 = audio_dir / f"{sid}_s{i:02d}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(full), "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                        "-c:a", "libmp3lame", "-q:a", "2", str(mp3)], check=True)
        ws = [{**w, "start": w["start"] - a, "end": w["end"] - a} for w in raw[edges[i]:edges[i + 1]]]
        out.append((mp3, ws))
    full.unlink()
    return out


def synth_with_context(text: str, extra: str, out_mp3: Path, flow: bool = False):
    """Inspreken met extra Nederlandse context erachter (de eerste zin van de volgende scène), zodat de
    meertalige stem Nederlands kiest; daarna het extra stuk eraf knippen."""
    raw = asyncio.run(_synth(text.strip() + " " + extra.strip(), out_mp3, flow))
    norm = lambda x: re.sub(r"[^\w%€]", "", x.lower())
    toks = display_text(text).split()
    last, n = norm(toks[-1]), len(toks)
    k = next((j for j in range(max(0, n - 4), len(raw)) if norm(raw[j]["text"]) == last
              or (raw[j]["text"].startswith("-") and last.endswith(norm(raw[j]["text"])))), None)
    if k is None:
        raise RuntimeError("einde van de scène niet gevonden in de context-opname")
    cut = min(raw[k]["end"] + 0.08, raw[k + 1]["start"] - 0.02) if k + 1 < len(raw) else raw[k]["end"] + 0.1
    tmp = out_mp3.with_suffix(".ctx.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_mp3), "-to", f"{cut:.3f}",
                    "-c:a", "libmp3lame", "-q:a", "2", str(tmp)], check=True)
    tmp.replace(out_mp3)
    return synth_scene(text, out_mp3, raw=raw[:k + 1], flow=flow)


class TaalFout(RuntimeError):
    pass


def taal(mp3: Path):
    """Welke taal hoort Whisper? Zonder Whisper (niet geïnstalleerd) -> ('nl', 1.0) en de zelfreview meldt het."""
    if not config.LANG_CHECK:
        return "nl", 1.0
    try:
        from . import luister
        _, info = luister.model().transcribe(luister.load_audio(mp3), beam_size=1)
        return info.language, info.language_probability
    except Exception as e:
        print(f"  taalcontrole niet mogelijk ({type(e).__name__})", flush=True)
        return "nl", 1.0


def spoken_text(text: str) -> str:
    """Exact de tekst die naar de stem gaat (voor de controle in de zelfreview)."""
    sp, _ = split_pronunciation(text)
    sp = flowing(sp).replace("&", " en ")
    return to_spoken(sp)[0]


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
    lang_report = []
    for i, scene in enumerate(script["scenes"]):
        mp3 = audio_dir / f"{sid}_s{i:02d}.mp3"
        words, best = None, None
        # TAALBEWAKING: de meertalige stem kiest zelf een taal. Na elke poging luistert Whisper mee;
        # geen Nederlands -> andere manier van inspreken (doorlopend / met gewone zinnen), tot het klopt.
        scenes_all = script["scenes"]
        nxt = split_sentences(display_text(scenes_all[i + 1]["say"]))[0][0] if i + 1 < len(scenes_all) else None
        for mode in ("flow", "zinnen", "flow", "zinnen"):
            if mode.startswith("context") and not nxt:
                continue
            for attempt in range(7):
                try:
                    if mode.startswith("context"):
                        ws = synth_with_context(scene["say"], nxt, mp3, flow=(mode == "context-flow"))
                    else:
                        ws = synth_scene(scene["say"], mp3, flow=(mode == "flow"))
                    break
                except Exception as e:  # netwerkhapering: opnieuw proberen
                    print(f"  scène {i}: poging {attempt + 1} mislukt ({type(e).__name__})", flush=True)
                    if attempt == 6:
                        raise
                    time.sleep(4 + 4 * attempt)
            lang, prob = taal(mp3)
            if best is None or (lang == "nl" and prob > best[1]):
                best = (lang, prob, mode)
                words = ws
                shutil.copy(mp3, mp3.with_suffix(".best.mp3"))
            if lang == "nl" and prob >= config.LANG_MIN:
                break
            print(f"  scène {i}: stem klinkt als '{lang}' ({prob:.2f}) -> opnieuw anders inspreken", flush=True)
        shutil.move(mp3.with_suffix(".best.mp3"), mp3)
        if config.LANG_CHECK and (best[0] != "nl" or best[1] < config.LANG_MIN):
            raise TaalFout(f"TAALFOUT scène {i}: de stem spreekt deze zin als '{best[0]}' uit, hoe vaak ik het ook "
                           f"probeer: \"{display_text(scene['say'])[:90]}\". Herschrijf de zin met duidelijk Nederlandse "
                           f"woorden (vermijd openingen die op Engels lijken, zoals 'Ken je', 'Is', een naam) en bouw opnieuw.")
        lang_report.append({"scene": i, "taal": best[0], "zeker": round(best[1], 2), "modus": best[2]})
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
            "scenes": timeline, "words": all_words,
            "spoken": [spoken_text(sc["say"]) for sc in script["scenes"]],
            "taal": lang_report}
    (audio_dir / f"{sid}.timings.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return data
