"""Luisteren: de voice-over automatisch uitschrijven met Whisper en controleren.

Claude kan de audio niet zelf horen. Daardoor glipten taalwissels (Frans "trente-cinq pourcent",
Engels) en ontbrekende stukken erdoor. Deze module controleert per scène:
  - welke taal Whisper hoort (moet Nederlands zijn),
  - of er Franse/Engelse woorden in de uitschrift staan,
  - of de gesproken woorden overeenkomen met het script (ontbrekende audio).
Het model (faster-whisper 'small', ~480 MB; nauwkeuriger dan 'base' bij snelle spraak) wordt één keer gedownload naar ~/.cache.
"""
import re
import subprocess
import time
import urllib.request
from pathlib import Path

import numpy as np

MODEL_DIR = Path.home() / ".cache" / "fiscaalfluitje" / "whisper-small"
FILES = ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
URL = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/{}"

FRANS = {"pour", "cent", "pourcent", "trente", "cinq", "vingt", "quarante", "et", "le", "la", "les", "est",
         "une", "des", "mille", "euros", "dollars", "aujourd'hui", "avec", "dans", "sur"}
ENGELS = {"the", "and", "percent", "one", "two", "three", "five", "thirty", "is", "of", "today", "with",
          "dollars", "hundred", "thousand", "billion", "what", "why"}
NL_OOK = {"de", "is", "en", "in", "op", "van", "met"}  # komen in beide talen voor: niet meetellen

_model = None


def ensure_model():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        p = MODEL_DIR / f
        if p.exists() and p.stat().st_size > 0:
            continue
        for attempt in range(6):  # Hugging Face beperkt verzoeken vanaf gedeelde IP's
            try:
                req = urllib.request.Request(URL.format(f), headers={"User-Agent": "FiscaalFluitje/1.0"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    p.write_bytes(r.read())
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(30 * (attempt + 1))
    return MODEL_DIR


def model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(str(ensure_model()), device="cpu", compute_type="int8")
    return _model


def load_audio(path, start=None, end=None):
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}"]
    if end is not None:
        cmd += ["-to", f"{end:.2f}"]
    cmd += ["-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def _woorden(t):
    return [w for w in re.findall(r"[a-zà-ÿ']+", t.lower()) if len(w) > 1]


def luister(audio_path, timing):
    """Per scène: taal, zekerheid, uitschrift, vreemde woorden en hoeveel van het script terug te horen is."""
    m = model()
    out = []
    spoken = timing.get("spoken") or []
    for i, sc in enumerate(timing["scenes"]):
        a = load_audio(audio_path, sc["start"], sc["end"] + 0.1)
        segs, info = m.transcribe(a, beam_size=1)
        tekst = " ".join(s.text.strip() for s in segs)
        hw = _woorden(tekst)
        vreemd = sorted({w for w in hw if (w in FRANS or w in ENGELS) and w not in NL_OOK})
        verwacht = _woorden(spoken[i]) if i < len(spoken) else []
        # hoeveel verwachte woorden (min. 4 letters) komen ongeveer terug in wat Whisper hoort?
        lang_w = [w for w in verwacht if len(w) >= 4]
        from difflib import SequenceMatcher
        def lijkt(w, h):  # vage gelijkenis: Whisper schrijft snelle spraak niet altijd foutloos uit
            return w[:4] == h[:4] or w in h or h in w or SequenceMatcher(None, w, h).ratio() >= 0.6
        hits = sum(1 for w in lang_w if any(lijkt(w, h) for h in hw))
        out.append({"scene": i, "taal": info.language, "zeker": round(info.language_probability, 2),
                    "gehoord": tekst, "vreemde_woorden": vreemd,
                    "teruggehoord": round(hits / len(lang_w), 2) if lang_w else None})
    return out


def flags(res):
    f = []
    for r in res:
        if r["taal"] != "nl":
            f.append(f"STEM scène {r['scene']}: Whisper hoort '{r['taal']}' in plaats van Nederlands: \"{r['gehoord'][:80]}\"")
        elif r["zeker"] < 0.5:
            f.append(f"STEM scène {r['scene']}: twijfelachtig Nederlands (zeker {r['zeker']}).")
        if len(r["vreemde_woorden"]) >= 2:
            f.append(f"STEM scène {r['scene']}: vreemde woorden gehoord {r['vreemde_woorden']}.")
        if r["teruggehoord"] is not None and r["teruggehoord"] < 0.35:
            f.append(f"STEM scène {r['scene']}: maar {int(r['teruggehoord'] * 100)}% van het script teruggehoord (audio ontbreekt of onverstaanbaar?).")
    return f
