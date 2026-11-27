"""3D-iconen (Microsoft Fluent Emoji 3D, MIT-licentie) voor de 'uitleg'-stijl.

Een icoon wordt in een script aangeduid met
  - het emoji-teken zelf, bv. "💶", of
  - de Unicode-naam (Engels, hoofdletterongevoelig), bv. "banknote with euro sign", "pig face".
Gebruikte iconen worden naar assets/icons/ gekopieerd zodat de repo zelfstandig blijft.

  python -m pipeline.iconen zoek euro      # namen opzoeken
"""
import shutil
import subprocess
import sys
import tarfile
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image

from . import config as C

PKG = "@lobehub/fluent-emoji-3d@1.1.0"
CACHE = Path.home() / ".cache" / "fiscaalfluitje" / "fluent"
REPO = C.ROOT / "assets" / "icons"


def _pakket():
    assets = CACHE / "package" / "assets"
    if not assets.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["npm", "pack", PKG, "--silent"], cwd=CACHE, check=True, capture_output=True)
        tgz = next(CACHE.glob("*.tgz"))
        with tarfile.open(tgz) as tf:
            tf.extractall(CACHE, filter="data")
        tgz.unlink()
    return assets


def _code(ch):
    return "-".join(f"{ord(c):x}" for c in ch if ord(c) != 0xFE0F)


@lru_cache(None)
def _namen():
    out = {}
    for p in _pakket().glob("*.webp"):
        cps = [int(x, 16) for x in p.stem.split("-") if x != "fe0f"]
        if len(cps) == 1:
            try:
                out[unicodedata.name(chr(cps[0])).lower()] = p
            except ValueError:
                pass
    return out


def _slug(key):
    return "".join(c if c.isalnum() else "-" for c in key.lower()).strip("-") or _code(key)


def pad(key: str) -> Path:
    """Pad naar het icoon (eerst in assets/icons, anders uit het pakket kopiëren)."""
    local = REPO / f"{_slug(key) if key.isascii() else _code(key)}.png"
    if local.exists():
        return local
    if key.isascii():
        src = _namen().get(key.lower())
    else:
        src = _pakket() / f"{_code(key)}.webp"
        if not src.exists():
            src = None
    if not src:
        raise KeyError(f"icoon niet gevonden: {key!r} (zoek met: python -m pipeline.iconen zoek <woord>)")
    REPO.mkdir(parents=True, exist_ok=True)
    Image.open(src).convert("RGBA").save(local)
    return local


@lru_cache(64)
def beeld(key: str, size: int) -> Image.Image:
    return Image.open(pad(key)).convert("RGBA").resize((size, size), Image.LANCZOS)


def zoek(woord):
    return sorted(n for n in _namen() if woord.lower() in n)


if __name__ == "__main__":
    if sys.argv[1] == "zoek":
        print("\n".join(zoek(" ".join(sys.argv[2:]))))
