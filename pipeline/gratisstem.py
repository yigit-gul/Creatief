"""Gratis, natuurlijkere stem: Chatterbox Multilingual (open-source, MIT), lokaal op de CPU.

Gekozen door de gebruiker op 27/11 (variant C: klankkleur van Andrew, exaggeration 0.5, cfg 0.5).
Werkwijze per video:
  1. elke scène inspreken (gewone zinnen met punten: Chatterbox wisselt niet van taal zoals de Edge-stem),
  2. Whisper luistert terug: Nederlands? alle woorden gehoord? anders opnieuw met een andere seed (beste take blijft),
  3. stilte/ruis voor het eerste en na het laatste woord wegknippen, iets sneller (atempo),
  4. woorden uitlijnen op de scripttekst -> zelfde 'timing' als de Edge-stem (ondertitels, cues blijven werken).

Installatie (eenmalig, gebeurt automatisch als de map ontbreekt): zie `ensure_env`.
"""
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from . import config as C
from .getallen import to_spoken
from .tts import display_text, duration, split_pronunciation

ENV = Path.home() / ".cache" / "fiscaalfluitje" / "cbenv"
PY = ENV / "bin" / "python"
RUNNER = Path(__file__).with_name("_cb_runner.py")


def ensure_env():
    """Aparte Python 3.11-omgeving (Chatterbox vraagt oudere torch/numpy dan de pipeline)."""
    if PY.exists():
        return
    subprocess.run(["uv", "venv", "-p", "3.11", str(ENV)], check=True)
    env = {"VIRTUAL_ENV": str(ENV), **__import__("os").environ}
    subprocess.run(["uv", "pip", "install", "chatterbox-tts==0.1.7", "setuptools<81"], check=True, env=env)


def tekst_voor_stem(say):
    """Uitspraakvorm ([RSZ|R.S.Z.]) en getallen als woorden; zinnen blijven gewone zinnen."""
    sp, _ = split_pronunciation(say)
    return to_spoken(sp.replace("&", " en "))[0]


def _run(jobs):
    task = {"ref": str(C.ROOT / C.CB_REF), "exaggeration": C.CB_EXAGGERATION, "cfg": C.CB_CFG, "jobs": jobs}
    env = {**__import__("os").environ, "HF_HUB_DISABLE_XET": "1",
           "REQUESTS_CA_BUNDLE": "/root/.ccr/ca-bundle.crt", "SSL_CERT_FILE": "/root/.ccr/ca-bundle.crt"}
    p = subprocess.run([str(PY), str(RUNNER)], input=json.dumps(task), text=True, capture_output=True, env=env)
    if p.returncode != 0:
        raise RuntimeError("Chatterbox faalde:\n" + p.stderr[-2000:])


def _norm(w):
    w = re.sub(r"[^\w]", "", w.lower())
    m = re.fullmatch(r"([a-z]*)(\d{1,2})", w)  # Whisper schrijft 'hap twee' als 'HAP2': cijfer = woord
    if m and not m.group(1):
        from .getallen import getal
        return getal(int(m.group(2)))
    return w


def _luister(wav):
    from . import luister
    segs, info = luister.model().transcribe(luister.load_audio(wav), word_timestamps=True, beam_size=5)
    heard = [{"w": w.word.strip(), "start": w.start, "end": w.end} for s in segs for w in (s.words or [])]
    out = []
    for h in heard:  # 'HAP2' -> 'HAP' + 'twee'
        m = re.fullmatch(r"([A-Za-z]{2,})(\d{1,2})", h["w"].strip(".,!?"))
        out += ([{**h, "w": m.group(1)}, {**h, "w": m.group(2)}] if m else [h])
    return out, info.language, info.language_probability


def _uitspraak_terug(heard, say):
    """'er es zet' (zo uitgesproken) weer als één woord 'RSZ' tellen, zodat de controle het herkent."""
    from .tts import PRON
    for shown, spoken in PRON.findall(say):
        sp = [_norm(x) for x in spoken.split()]
        n = len(sp)
        k = 0
        while k + n <= len(heard):
            if [_norm(h["w"]) for h in heard[k:k + n]] == sp or _norm("".join(h["w"] for h in heard[k:k + n])) == _norm(shown):
                heard[k:k + n] = [{"w": shown, "start": heard[k]["start"], "end": heard[k + n - 1]["end"]}]
            k += 1
    return heard


def _woorden(txt):
    return [w for w in re.sub(r"[^a-zà-ÿ ]", " ", to_spoken(txt.lower().replace(",", " , "))[0]).split()]


def _gelijkenis(say, heard):
    """Welk deel van de bedoelde woorden Whisper terug hoort, in gesproken vorm ('100' = 'honderd').
    Kleine schrijfverschillen ('elk'/'elke') tellen als juist; echte uitspraakfouten ('RCJ' i.p.v. 'er es zet',
    een afgebroken 'bedrijfsvoorhef') niet. Verzonnen extra woorden verlagen de score ook."""
    a = _woorden(tekst_voor_stem(say))
    b = _woorden(" ".join(h["w"] for h in heard))
    if not a or not b:
        return 0.0
    # gehoorde woorden die bijna gelijk zijn aan een woord uit het script, als dat woord tellen
    b = [next((x for x in a if x == w or (len(w) > 2 and SequenceMatcher(None, w, x).ratio() >= 0.8)), w) for w in b]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    m = sum(n for _, _, n in sm.get_matching_blocks())
    return 2 * m / (len(a) + len(b))


def _rand(heard):
    """Begin van het eerste en einde van het laatste woord dat Whisper echt hoorde (ook als het verkeerd verstaan is)."""
    return (heard[0]["start"], heard[-1]["end"]) if heard else None


def _align(tokens, heard):
    """Tijd per scripttoken uit Whispers woorden (ontbrekende tokens: tussen de buren schatten)."""
    sm = SequenceMatcher(None, [_norm(t) for t in tokens], [_norm(h["w"]) for h in heard], autojunk=False)
    t_of = [None] * len(tokens)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            t_of[a + k] = (heard[b + k]["start"], heard[b + k]["end"])
    known = [i for i, x in enumerate(t_of) if x]
    matched = len(known)
    if not known:
        return None, 0.0
    for i in range(len(tokens)):
        if t_of[i]:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is None:
            s = max(0.0, t_of[nxt][0] - 0.3 * (nxt - i))
        elif nxt is None:
            s = t_of[prev][1] + 0.3 * (i - prev)
        else:
            s = t_of[prev][1] + (i - prev) / (nxt - prev) * (t_of[nxt][0] - t_of[prev][1])
        t_of[i] = (s, s + 0.2)
    return t_of, matched / len(tokens)


def _verwerk(raw, out):
    """48 kHz mono, licht versneld (CB_TEMPO), lange pauzes ingekort."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", "48000",
                    "-af", f"atempo={C.CB_TEMPO}", str(out)], check=True)
    _kort_stiltes(out)


def _kort_stiltes(wav):
    """Alleen té lange pauzes (> CB_PAUZE_MAX) inkorten; gewone adempauzes blijven (anders klinkt het gehaast,
    feedback 27/11). Mag meermaals op hetzelfde bestand: het resultaat blijft gelijk."""
    tmp = wav.with_suffix(".kort.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af",
                    f"silenceremove=stop_periods=-1:stop_duration={C.CB_PAUZE_MAX}:stop_threshold=-31dB:stop_silence={C.CB_PAUZE_HOUD}",
                    str(tmp)], check=True)
    tmp.replace(wav)


def _knip(wav, a, b):
    tmp = wav.with_suffix(".knip.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                    "-af", "afade=t=in:d=0.02,areverse,afade=t=in:d=0.04,areverse", str(tmp)], check=True)
    tmp.replace(wav)


def synthesize_script(script: dict, audio_dir: Path) -> dict:
    ensure_env()
    audio_dir.mkdir(parents=True, exist_ok=True)
    sid = script["id"]
    scenes = script["scenes"]
    best = [None] * len(scenes)  # (score, wav, words, taal, zeker)
    todo = list(range(len(scenes)))
    # CACHE: een scène waarvan de tekst en instellingen niet veranderden, hoeft niet opnieuw ingesproken te worden
    import hashlib
    import shutil
    cache = audio_dir / "cb_cache"
    cache.mkdir(exist_ok=True)

    def sleutel(i):  # de cache bewaart de RUWE opname: tempo/pauzes aanpassen vraagt geen nieuwe opname
        k = json.dumps([tekst_voor_stem(scenes[i]["say"]), display_text(scenes[i]["say"]), C.CB_REF,
                        C.CB_EXAGGERATION, C.CB_CFG])
        return cache / (hashlib.sha1(k.encode()).hexdigest()[:16] + ".raw.wav")

    def ruw(wav):
        return Path(str(wav)[:-4] + ".raw.wav")

    for i in list(todo):
        if sleutel(i).exists():
            wav = audio_dir / f"{sid}_s{i:02d}.cache.wav"
            shutil.copy(sleutel(i), ruw(wav))
            _verwerk(ruw(wav), wav)
            tokens = display_text(scenes[i]["say"]).split()
            heard, lang, prob = _luister(wav)
            score = _gelijkenis(scenes[i]["say"], heard) if lang == "nl" else -1
            heard = _uitspraak_terug(heard, scenes[i]["say"])
            t_of, _ = _align(tokens, heard)
            best[i] = (score, wav, (tokens, t_of, _rand(heard)), lang, prob)
            todo.remove(i)
            print(f"  scène {i}: uit cache", flush=True)
    for ronde, seed in enumerate((1, 7, 23, 61)):
        if not todo:
            break
        jobs = [{"text": tekst_voor_stem(scenes[i]["say"]), "seed": seed,
                 "out": str(audio_dir / f"{sid}_s{i:02d}.r{ronde}.raw.wav")} for i in todo]
        print(f"▶ gratis stem: ronde {ronde + 1}, {len(jobs)} scène(s) inspreken…", flush=True)
        _run(jobs)
        nog = []
        for i in todo:
            raw = audio_dir / f"{sid}_s{i:02d}.r{ronde}.raw.wav"
            wav = audio_dir / f"{sid}_s{i:02d}.r{ronde}.wav"
            _verwerk(raw, wav)
            tokens = display_text(scenes[i]["say"]).split()
            heard, lang, prob = _luister(wav)
            score = _gelijkenis(scenes[i]["say"], heard) if lang == "nl" else -1  # verzonnen/vergeten stukken tellen mee
            heard = _uitspraak_terug(heard, scenes[i]["say"])
            t_of, _ = _align(tokens, heard)
            print(f"  scène {i}: taal {lang} ({prob:.2f}), {score:.0%} juist gehoord", flush=True)
            if best[i] is None or score > best[i][0]:
                if best[i]:
                    Path(best[i][1]).unlink(missing_ok=True)
                    ruw(best[i][1]).unlink(missing_ok=True)
                best[i] = (score, wav, (tokens, t_of, _rand(heard)), lang, prob)
            else:
                wav.unlink()
                raw.unlink()
            if score < C.CB_MIN_SCORE:
                nog.append(i)
        todo = nog
    for i, b in enumerate(best):  # goede takes bewaren (ook als een andere scène faalt)
        if b[0] >= C.CB_OK and b[3] == "nl" and not str(b[1]).endswith(".cache.wav"):
            shutil.copy(ruw(b[1]), sleutel(i))
    for b in best:
        ruw(b[1]).unlink(missing_ok=True)
    bad = [i for i, b in enumerate(best) if b[3] != "nl" or b[0] < C.CB_OK]
    if bad:
        from .tts import TaalFout
        raise TaalFout(f"TAALFOUT/UITSPRAAK scène(s) {bad}: de gratis stem zegt deze zin niet goed. Herschrijf de zin "
                       f"(gewone woorden, geen afkortingen) en bouw opnieuw.")

    # knippen tot de eigenlijke woorden, plakken met korte pauzes, woorden op de tijdlijn zetten
    words, timeline, parts, t = [], [], [], 0.0
    lang_report = []
    for i, (score, wav, (tokens, t_of, rand), lang, prob) in enumerate(best):
        # knippen op wat echt gezegd werd: nooit midden in een (verkeerd verstaan) laatste woord
        a = max(0.0, min(t_of[0][0], rand[0] if rand else 9e9) - 0.05)
        b = min(duration(wav), max(t_of[-1][1], rand[1] if rand else 0) + 0.18)
        _knip(wav, a, b)
        final = audio_dir / f"{sid}_s{i:02d}.wav"
        Path(wav).replace(final)
        d = duration(final)
        for tok, (s, e) in zip(tokens, t_of):
            w = {"text": tok, "start": round(t + s - a, 3), "end": round(t + min(e, b) - a, 3)}
            if tok[-1] in ".!?":
                w["eos"] = True
            words.append(w)
        timeline.append({"start": round(t, 3), "end": round(t + d, 3)})
        parts.append(final)
        lang_report.append({"scene": i, "taal": lang, "zeker": round(prob, 2), "gehoord": round(score, 2)})
        t += d + C.SCENE_GAP
    out = audio_dir / f"{sid}.wav"
    ins, filt = [], []
    for k, p in enumerate(parts):
        ins += ["-i", str(p)]
        filt.append(f"[{k}:a]apad=pad_dur={C.SCENE_GAP}[a{k}]")
    filt.append("".join(f"[a{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(filt),
                    "-map", "[o]", str(out)], check=True)
    for p in parts:
        p.unlink()
    total = timeline[-1]["end"]
    data = {"audio": str(out.relative_to(C.ROOT)), "duration": total, "scenes": timeline, "words": words,
            "spoken": [tekst_voor_stem(s["say"]) for s in scenes], "taal": lang_report, "engine": "chatterbox"}
    (audio_dir / f"{sid}.timings.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return data
