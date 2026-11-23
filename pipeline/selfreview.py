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
from .render import chunk_words, font
from .tts import display_text

RUBRIC = {
    "hook": "Pakt de eerste 2-3 s? Herkenbaar, verrassend of grappig, en niet misleidend.",
    "eenvoud": "Korte zinnen (max. ~10 woorden), gewone woorden, één idee per zin. Klinkt als praten, niet voorlezen.",
    "tempo": "Geen stukken die slepen of te vol zitten; elke scène heeft een reden.",
    "humor": "Minstens 1-2 knipogen die de uitleg helpen; niets geforceerd of kwetsend.",
    "info": "Leer je echt iets? Klopt elk cijfer met de claims en bronnen?",
    "visueel": "Tekst leesbaar, niets overlapt, grafiek/cijfers verschijnen op het juiste moment.",
    "regels": "Geen advies of voorspelling, disclaimer op het einde, AI-vermelding in caption.",
}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


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
                     "langer_dan_10": [x for x in all_sents if len(x.split()) > 10]}
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
        flags.append(f"{len(out['zinnen']['langer_dan_10'])} zin(nen) langer dan 10 woorden: opsplitsen.")
    for s in out["scenes"]:
        if s["woorden_per_sec"] and s["woorden_per_sec"] > 3.3:
            flags.append(f"Scène {s['n']} is erg vol ({s['woorden_per_sec']} w/s).")
        if s["sec"] > 16:
            flags.append(f"Scène {s['n']} duurt {s['sec']} s: risico op wegzappen, overweeg te splitsen.")
    if gaps:
        flags.append(f"{len(gaps)} stilte(s) > 0,6 s.")
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
        data = {"id": sid, "signalen": signals(script, timing),
                "rubriek": {k: {"vraag": v, "score": None, "opmerking": ""} for k, v in RUBRIC.items()},
                "ronde": 1, "verbeteringen": []}
        (odir / f"{sid}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        flags = data["signalen"]["aandachtspunten"]
        print(f"{sid}: {len(flags)} aandachtspunt(en)" + ("".join(f"\n  - {x}" for x in flags) if flags else ""))


if __name__ == "__main__":
    p = Path(sys.argv[1])
    run(p if p.is_absolute() else C.ROOT / p)
