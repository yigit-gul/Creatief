"""Zelfreview: maakt het materiaal waarmee Claude een eigen video kritisch beoordeelt.

Gebruik:  python -m pipeline.selfreview scripts/<map>            (alle video's in de map)
          python -m pipeline.selfreview scripts/<map>/<id>.json

Per video komt in review/<map>/selfreview/:
  <id>.png   contactsheet: per scène het beeld halverwege en op het einde (+ eerste 2 s)
  <id>.json  meetbare signalen (tempo, zinslengte, hook, stiltes, ondertitels) + lege rubriek
Claude bekijkt die twee, vult de rubriek in (zie WORKFLOW.md, stap 6) en verbetert waar nodig.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import config as C
import copy

import numpy as np

from .render import animation_end, apply_cues, chunk_words, font, render_layer
from .tts import display_text

RUBRIC = {
    "hook": "Pakt de eerste 2-3 s? Herkenbaar, verrassend of grappig, en niet misleidend.",
    "eenvoud": "Korte zinnen (max. ~10 woorden), gewone woorden, één idee per zin. Klinkt als praten, niet voorlezen.",
    "tempo": "Geen stukken die slepen of te vol zitten; elke scène heeft een reden.",
    "humor": "Minstens 1-2 knipogen die de uitleg helpen; niets geforceerd of kwetsend.",
    "info": "Leer je echt iets? Klopt elk cijfer met de claims en bronnen?",
    "visueel": "Tekst leesbaar, niets overlapt of staat dubbel (beeld + ondertitel), grafiek/cijfers verschijnen op het juiste moment.",
    "stem": "Elke zin is apart te horen (korte adempauze), niets klinkt als 2 dingen tegelijk, geen leesstijl.",
    "regels": "Geen advies of voorspelling, disclaimer op het einde, AI-vermelding in caption.",
}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def silences(audio: Path):
    if not audio.exists():
        return []
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(audio), "-af", "silencedetect=noise=-38dB:d=0.1",
                        "-f", "null", "-"], capture_output=True, text=True)
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(st, en))


def signals(script, timing):
    words = timing["words"]
    sc = timing["scenes"]
    out = {"duration": round(timing["duration"] + C.OUTRO_HOLD, 1), "scenes": []}
    all_sents = []
    for i, (s, t) in enumerate(zip(script["scenes"], sc)):
        txt = display_text(s["say"])
        sents = _sentences(txt)
        all_sents += sents
        n = len(txt.split())
        dur = t["end"] - t["start"]
        out["scenes"].append({
            "n": i, "type": s["visual"]["type"], "sec": round(dur, 1), "woorden": n,
            "woorden_per_sec": round(n / dur, 2) if dur else None,
            "langste_zin": max((len(x.split()) for x in sents), default=0),
        })
    lens = [len(x.split()) for x in all_sents]
    out["zinnen"] = {"aantal": len(lens), "gemiddeld": round(sum(lens) / len(lens), 1) if lens else 0,
                     "langer_dan_10": [x for x in all_sents if len(x.split()) > 12]}
    first = _sentences(display_text(script["scenes"][0]["say"]))[0]
    k = len(first.split())
    out["hook"] = {"eerste_zin": first, "klaar_na_sec": round(words[k - 1]["end"], 1) if len(words) >= k else None}
    gaps = [round(b["start"] - a["end"], 2) for a, b in zip(words, words[1:]) if b["start"] - a["end"] > 0.6]
    out["lange_stiltes"] = gaps
    chunks = chunk_words(words)
    out["ondertitels"] = {"blokken": len(chunks), "langste": max((" ".join(w["text"] for w in c) for c in chunks), key=len, default="")}
    flags = []
    if out["hook"]["klaar_na_sec"] and out["hook"]["klaar_na_sec"] > 3.0:
        flags.append("Eerste zin duurt langer dan 3 s: hook inkorten.")
    if out["zinnen"]["langer_dan_10"]:
        flags.append(f"{len(out['zinnen']['langer_dan_10'])} zin(nen) langer dan 12 woorden: opsplitsen.")
    for s in out["scenes"]:
        if s["woorden_per_sec"] and s["woorden_per_sec"] > 3.8:
            flags.append(f"Scène {s['n']} is erg vol ({s['woorden_per_sec']} w/s).")
        if s["sec"] > 16:
            flags.append(f"Scène {s['n']} duurt {s['sec']} s: risico op wegzappen, overweeg te splitsen.")
    if gaps:
        flags.append(f"{len(gaps)} stilte(s) > 0,6 s.")
    # TAALBEWAKING: de stem moet per scène één doorlopende Nederlandse zin krijgen, zonder cijfers.
    # (Losse korte zinnen of cijfers lieten de meertalige stem Frans/Engels spreken.)
    for i, sp in enumerate(timing.get("spoken", [])):
        if re.search(r"\d", sp):
            flags.append(f"TAAL: scène {i} stuurt nog cijfers naar de stem ({re.findall(r'[^ ]*\d[^ ]*', sp)[:3]}).")
        if re.search(r"[.!?]\s+\S", sp.replace("T.O.B.", "TOB")):
            flags.append(f"TAAL: scène {i} wordt in losse zinnen ingesproken (risico op taalwissel).")
    if "spoken" not in timing:
        flags.append("TAAL: geen gesproken tekst bewaard; bouw opnieuw met de huidige pipeline.")
    # zinnen die aan elkaar plakken (klinkt alsof hij 2 dingen tegelijk zegt)
    sil = silences(C.ROOT / timing["audio"].replace(".wav", ".mp3")) if timing.get("audio") else []
    def breathes(a, b):  # echte stilte in de audio tussen twee zinnen (woordtimings zijn te ruim)
        return any(e - st >= 0.11 and st < b["start"] + 0.05 and e > a["end"] - 0.6 for st, e in sil)
    glued = [f'"{a["text"]} | {b["text"]}"' for a, b in zip(words, words[1:]) if a.get("eos") and not breathes(a, b)]
    if glued:
        flags.append(f"{len(glued)} zinsgrens(en) zonder adempauze: {', '.join(glued[:4])}.")
    # tekst in beeld die de ondertitels raakt, of dubbele tekst (beeld + ondertitel)
    scenes = copy.deepcopy(script["scenes"])
    apply_cues(scenes, sc, words)
    overlap = []
    for i, (scn, t) in enumerate(zip(scenes, sc)):
        v = scn["visual"]
        subs = v.get("subs", v["type"] != "slam")
        if v["type"] == "slam" and v.get("subs"):
            flags.append(f"Scène {i}: reuzenwoorden én ondertitels tegelijk (dubbele tekst).")
        if not subs:
            continue
        dur = t["end"] - t["start"]
        layer = render_layer(scn, min(dur, animation_end(v, dur) + 0.5), dur)
        a = np.asarray(layer)[:, :, 3]
        rows = np.where(a[: C.H - 60].max(axis=1) > 40)[0]
        bottom = int(rows.max()) if len(rows) else 0
        overlap.append({"scene": i, "onderkant_tekst": bottom})
        if bottom > C.SUB_Y - 80:
            flags.append(f"Scène {i}: tekst in beeld loopt tot y={bottom} en raakt de ondertitels (y≈{C.SUB_Y}).")
    out["layout"] = overlap
    # EERSTE BEELD: staat de hook er meteen? (lege openingsframes = kijkers swipen weg)
    try:
        v0 = scenes[0]["visual"]
        t0 = 0.0 + (2.0 if v0["type"] == "hook" else 0.0)
        if v0["type"] == "slam" and v0.get("at"):
            v0 = {**v0, "at": [-1.0] + v0["at"][1:]}
        lay0 = render_layer({**scenes[0], "visual": v0}, t0, sc[0]["end"] - sc[0]["start"])
        a0 = np.asarray(lay0)[200:1300, :, 3]
        if (a0 > 40).mean() < 0.01:
            flags.append("EERSTE BEELD is (bijna) leeg: de hook moet er op frame 0 al staan.")
        out["eerste_beeld_tekst"] = round(float((a0 > 40).mean()), 3)
    except Exception as e:
        flags.append(f"Eerste beeld kon niet gecontroleerd worden ({type(e).__name__}).")
    out["aandachtspunten"] = flags
    return out


def contact_sheet(video: Path, timing, out_png: Path):
    sc = timing["scenes"]
    times = [1.5] + [x for s in sc for x in ((s["start"] + s["end"]) / 2, max(s["start"], s["end"] - 0.3))]
    tw, th = 270, 480
    cols = min(len(times), 7)
    rows = (len(times) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 30)), "#111")
    d = ImageDraw.Draw(sheet)
    tmp = out_png.with_suffix(".frame.png")
    for i, t in enumerate(times):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={tw}:{th}", str(tmp)], check=True)
        x, y = (i % cols) * tw, (i // cols) * (th + 30)
        sheet.paste(Image.open(tmp), (x, y + 30))
        d.text((x + 8, y + 6), f"{t:.1f}s", font=font("Bold", 18), fill="#2EE6A6")
    tmp.unlink(missing_ok=True)
    sheet.save(out_png)


def run(path: Path):
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    for f in files:
        script = json.loads(f.read_text())
        sid, grp = script["id"], f.parent.name
        timing = json.loads((C.ROOT / "audio" / grp / f"{sid}.timings.json").read_text())
        odir = C.ROOT / "review" / grp / "selfreview"
        odir.mkdir(parents=True, exist_ok=True)
        contact_sheet(C.ROOT / "video" / grp / f"{sid}.mp4", timing, odir / f"{sid}.png")
        sig = signals(script, timing)
        # LUISTEREN: Whisper schrijft de stem uit en controleert taal en ontbrekende stukken per scène
        try:
            from . import luister
            audio = C.ROOT / "audio" / grp / f"{sid}.mp3"
            if not audio.exists():
                audio = C.ROOT / timing["audio"]
            gehoord = luister.luister(audio, timing)
            sig["gehoord"] = gehoord
            sig["aandachtspunten"] = luister.flags(gehoord) + sig["aandachtspunten"]
        except Exception as e:
            sig["aandachtspunten"].insert(0, f"STEM: luistertest kon niet draaien ({type(e).__name__}: {str(e)[:80]}). Controleer de stem extra goed.")
        data = {"id": sid, "signalen": sig,
                "rubriek": {k: {"vraag": v, "score": None, "opmerking": ""} for k, v in RUBRIC.items()},
                "ronde": 1, "verbeteringen": []}
        (odir / f"{sid}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        flags = data["signalen"]["aandachtspunten"]
        print(f"{sid}: {len(flags)} aandachtspunt(en)" + ("".join(f"\n  - {x}" for x in flags) if flags else ""))


if __name__ == "__main__":
    p = Path(sys.argv[1])
    run(p if p.is_absolute() else C.ROOT / p)
