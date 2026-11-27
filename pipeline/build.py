"""Bouwt video's uit scripts en zet alles klaar in /review.

Gebruik:
  python -m pipeline.build scripts/2026-W48            # hele week
  python -m pipeline.build scripts/2026-W48/01-tob.json  # één script
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from . import config as C
from .render import render_video
from .tts import display_text, synthesize_script

# Woorden die op beleggingsadvies of clickbait kunnen wijzen -> menselijke check
RED_FLAGS = [
    r"\bkoop\b", r"\bkopen moet\b", r"\baanrader\b", r"\bbeste (etf|aandeel|aandelen|crypto)\b",
    r"\bgegarandeerd\b", r"\bsnel rijk\b", r"\bkoers(en)? (gaat|zal|stijgt)\b", r"\bmust[- ]have\b",
    r"\bmoet je (kopen|hebben)\b", r"\bnooit meer belasting\b",
]


def words_of(script):
    return " ".join(display_text(s["say"]) for s in script["scenes"]).split()


def checks(script, timing):
    res = []
    n = len(words_of(script))
    lo, hi = (170, 220) if script.get("stijl") == "uitleg" else (150, 190)  # uitleg: vlotter, minder pauzes
    res.append((f"Woordenaantal {lo}-{hi}", lo <= n <= hi, f"{n} woorden"))
    d = timing["duration"] + C.OUTRO_HOLD
    res.append(("Duur net boven 1 min (60-75 s; > 70 s alleen als de inhoud het draagt)", 60 <= d <= 75, f"{d:.1f} s"))
    hook_words = len(display_text(script["scenes"][0]["say"]).split())
    res.append(("Hook kort (≤ 22 woorden)", hook_words <= 22, f"{hook_words} woorden"))
    last = script["scenes"][-1]["visual"]
    res.append(("Eindkaart met disclaimer", last["type"] == "outro" or bool(last.get("eind")), C.DISCLAIMER))
    if script.get("stijl") != "uitleg":  # uitleg-stijl eindigt bewust op een twist, zonder 'volg voor meer'
        cta = "volg" in display_text(script["scenes"][-1]["say"]).lower()
        res.append(("Call to action ('volg')", cta, ""))
    res.append(("AI-vermelding in caption", "ai" in script["caption"].lower(), ""))
    nh = len(script["hashtags"])
    res.append(("3-5 hashtags", 3 <= nh <= 5, f"{nh}"))
    text = " ".join(display_text(s["say"]) for s in script["scenes"]).lower() + " " + script["caption"].lower()
    flags = [f for f in RED_FLAGS if re.search(f, text)]
    res.append(("Geen advies-/clickbaittaal (automatische scan)", not flags, ", ".join(flags)))
    res.append(("Geen 'hè' in de tekst", not re.search(r"\bh[eè]\b", text), ""))
    res.append(("Elke claim heeft een bron", all(c.get("sources") for c in script["claims"]), ""))
    return res


def caption_with_credits(script, eigen_stem=False):
    from .fotos import credits
    c = credits(script)
    return script["caption"].strip() + (("\n📸 Foto's: " + "; ".join(c)) if c else "")


def caption_text(script):
    return caption_with_credits(script) + "\n\n" + " ".join(script["hashtags"])


def build_one(path: Path):
    script = json.loads(path.read_text())
    oud = {k: getattr(C, k) for k in C.UITLEG_GAPS}
    if script.get("stijl") == "uitleg":
        for k, val in C.UITLEG_GAPS.items():
            setattr(C, k, val)
    try:
        return _build_one(path, script)
    finally:
        for k, val in oud.items():
            setattr(C, k, val)


def _build_one(path: Path, script):
    week = path.parent.name
    sid = script["id"]
    print(f"▶ {sid}: voice-over…", flush=True)
    from .eigenstem import timing_from_recording, vind_opname
    rec = vind_opname(path)
    if rec:  # eigen stem van de gebruiker in plaats van de AI-stem
        print(f"▶ {sid}: eigen opname gevonden ({rec.name}), uitlijnen met Whisper…", flush=True)
        timing = timing_from_recording(script, rec, C.ROOT / "audio" / week)
    else:
        timing = synthesize_script(script, C.ROOT / "audio" / week)
    print(f"▶ {sid}: video renderen ({timing['duration']:.1f} s)…", flush=True)
    out = render_video(script, timing, C.ROOT / "video" / week / f"{sid}.mp4", C.ROOT / "audio" / week)
    # voice-over bewaren als compacte mp3 (wav enkel tijdelijk nodig voor de render)
    wav = C.ROOT / timing["audio"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "128k",
                    str(wav.with_suffix(".mp3"))], check=True)
    wav.unlink()
    rdir = C.ROOT / "review" / week
    rdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(out, rdir / out.name)
    # omslagbeeld: einde van de openingsscène (hook volledig in beeld), om te kiezen bij het uploaden
    make_cover(script, timing, rdir / f"{sid}.cover.jpg")
    (rdir / f"{sid}.bronnen.md").write_text(
        f"# Bronnen · {script['title']}\n\nGeldigheid: {script['validity']}\n\n" + md_sources(script) + "\n",
        encoding="utf-8")
    (rdir / f"{sid}.caption.txt").write_text(caption_text(script), encoding="utf-8")
    chk = checks(script, timing)
    sdir = rdir / "studio"
    sdir.mkdir(exist_ok=True)
    (sdir / f"{week}_{sid}.json").write_text(
        json.dumps(studio_doc(script, timing, chk, week), indent=1, ensure_ascii=False), encoding="utf-8")
    return script, timing, chk


def make_cover(script, timing, path):
    """Omslagbeeld zonder ondertitels: de openingsscène volledig in beeld."""
    import copy
    from PIL import Image
    from . import render
    scenes = copy.deepcopy(script["scenes"])
    render.apply_cues(scenes, timing["scenes"], timing["words"])
    sc0, t0 = scenes[0], timing["scenes"][0]
    dur = t0["end"] - t0["start"]
    layer = render.render_layer(sc0, max(dur, render.animation_end(sc0["visual"], dur) + 0.5), dur)
    v = sc0["visual"]
    bg = render.photo_background(v["photo"], dur, dur, v.get("photo_dim", 0.62)) if v.get("photo") else render.moving_background(1.0)
    Image.alpha_composite(bg, layer).convert("RGB").save(path, quality=92)


def studio_doc(script, timing, chk, week):
    """Document voor de Studio-pagina (collection `videos`, doc-id `<week>_<id>`)."""
    return {
        "week": week, "id": script["id"], "title": script["title"], "validity": script["validity"],
        "status": "klaar voor review", "durationSec": round(timing["duration"] + C.OUTRO_HOLD, 1),
        "words": len(words_of(script)),
        "script": [display_text(s["say"]) for s in script["scenes"]],
        "caption": caption_with_credits(script), "hashtags": script["hashtags"],
        "claims": script["claims"], "warnings": script.get("warnings", []),
        "checks": [{"name": n, "ok": bool(ok), "info": info} for n, ok, info in chk],
        "repoPath": f"review/{week}/{script['id']}.mp4",
    }


def md_sources(script):
    out = []
    for c in script["claims"]:
        flag = "⚠️ " if c.get("status") != "ok" else "✅ "
        out.append(f"- {flag}**{c['claim']}**" + (f" — _{c['note']}_" if c.get("note") else ""))
        for s in c["sources"]:
            out.append(f"  - [{s['title']}]({s['url']}) — geraadpleegd {s['date']}")
    return "\n".join(out)


def write_review(week: str, results):
    rdir = C.ROOT / "review" / week
    L = [f"# Review {week}", "",
         f"Gegenereerd op {date.today().isoformat()} · stem `{C.VOICE}` · kanaal **{C.CHANNEL_NAME}** ({C.CHANNEL_HANDLE})",
         "", "Video's, captions en dit overzicht staan in deze map. Er wordt **niets** automatisch gepost.", "",
         "| # | Titel | Duur | Woorden | Auto-checks | ⚠️ |", "|---|---|---|---|---|---|"]
    for script, timing, chk in results:
        ok = sum(1 for c in chk if c[1])
        warn = sum(1 for c in script["claims"] if c.get("status") != "ok") + len(script.get("warnings", []))
        L.append(f"| {script['id']} | {script['title']} | {timing['duration'] + C.OUTRO_HOLD:.0f} s | "
                 f"{len(words_of(script))} | {ok}/{len(chk)} | {warn or '–'} |")
    for script, timing, chk in results:
        sid = script["id"]
        L += ["", "---", "", f"## {sid} · {script['title']}", "",
              f"**Video:** [{sid}.mp4]({sid}.mp4) · **Geldigheid:** {script['validity']}", "",
              "### Script (voice-over)", ""]
        for s in script["scenes"]:
            L.append(f"> {display_text(s['say'])}")
            L.append(">")
        L[-1] = ""
        L += ["### Bronnen en controle van cijfers", "", md_sources(script), ""]
        if script.get("warnings"):
            L += ["### ⚠️ Aandachtspunten", ""] + [f"- ⚠️ {w}" for w in script["warnings"]] + [""]
        L += ["### Caption", "", "```", caption_text(script), "```", "",
              "### Automatische checks", ""]
        L += [f"- {'✅' if okk else '❌'} {name}" + (f" ({info})" if info else "") for name, okk, info in chk]
        L += ["", "### Jouw checklist", "",
              "- [ ] Cijfers en tarieven nagekeken tegen de bronnen hierboven (aanslagjaar/geldigheid klopt)",
              "- [ ] Alle ⚠️-punten opgelost of geschrapt",
              "- [ ] Geen beleggingsadvies, geen productaanraders, geen koersvoorspellingen",
              "- [ ] Uitspraak en ondertitels correct (vooral cijfers en afkortingen)",
              "- [ ] Disclaimer \"" + C.DISCLAIMER + "\" zichtbaar op het einde",
              "- [ ] Geen misleidende hook",
              "- [ ] AI-label aanzetten in TikTok bij het inplannen",
              "- [ ] Ingepland in Metricool/Buffer", ""]
    (rdir / "review.md").write_text("\n".join(L), encoding="utf-8")
    return rdir / "review.md"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="scriptmap van een week of één .json-script")
    a = ap.parse_args(argv)
    p = (C.ROOT / a.target) if not Path(a.target).is_absolute() else Path(a.target)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    week = files[0].parent.name
    results = [build_one(f) for f in files]
    md = write_review(week, results)
    print(f"✔ klaar: {md}")
    bad = [(s["id"], n) for s, _, chk in results for n, ok, _ in chk if not ok]
    if bad:
        print("Let op, gefaalde checks:", bad, file=sys.stderr)


if __name__ == "__main__":
    main()
