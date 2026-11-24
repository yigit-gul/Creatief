"""Echte foto's van Wikimedia Commons zoeken en downloaden, met licentie en naamsvermelding.

Alleen licenties die we zonder gedoe in een video mogen gebruiken:
publiek domein, CC0 en CC BY (naamsvermelding). CC BY-SA en strengere licenties slaan we over.

Gebruik:
  python -m pipeline.fotos zoek "Jensen Huang"          # toont kandidaten met licentie
  python -m pipeline.fotos haal "File:Naam.jpg" slug     # downloadt naar assets/fotos/<slug>.jpg (+ .json)
In een script: "visual": {..., "photo": "jensen"}  -> assets/fotos/jensen.jpg als achtergrond.
"""
import json
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from . import config as C

API = "https://commons.wikimedia.org/w/api.php"
UA = "FiscaalFluitjeVideoPipeline/1.0 (educational video renderer)"
DIR = C.ROOT / "assets" / "fotos"
OK_LICENSES = ("public domain", "pd", "cc0", "cc by 1.0", "cc by 2.0", "cc by 2.5", "cc by 3.0", "cc by 4.0")


def _get(url):
    import time
    for attempt in range(5):  # Wikimedia beperkt het aantal verzoeken (429): rustig opnieuw proberen
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(15 * (attempt + 1))


def _clean(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def license_ok(lic: str) -> bool:
    l = lic.lower().strip()
    if "sa" in l.replace("cc by-sa", "SA").split() or "by-sa" in l or "nc" in l or "nd" in l:
        return False
    return l.startswith(OK_LICENSES) or l in ("public domain", "cc0")


def zoek(term, limit=12):
    q = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{term} filetype:bitmap",
         "gsrnamespace": 6, "gsrlimit": limit, "prop": "imageinfo",
         "iiprop": "url|size|extmetadata", "iiurlwidth": 1400}
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(q)))
    out = []
    for p in (data.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = _clean(md.get("LicenseShortName", {}).get("value", ""))
        out.append({"title": p["title"], "license": lic, "ok": license_ok(lic),
                    "author": _clean(md.get("Artist", {}).get("value", ""))[:80],
                    "w": ii.get("width"), "h": ii.get("height"),
                    "thumb": ii.get("thumburl"), "page": ii.get("descriptionurl")})
    return sorted(out, key=lambda x: (not x["ok"], -(x["w"] or 0)))


def haal(title, slug):
    q = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
         "iiprop": "url|extmetadata", "iiurlwidth": 1280}  # standaardmaat van Wikimedia
    p = next(iter(json.loads(_get(API + "?" + urllib.parse.urlencode(q)))["query"]["pages"].values()))
    ii = p["imageinfo"][0]
    md = ii.get("extmetadata", {})
    lic = _clean(md.get("LicenseShortName", {}).get("value", ""))
    if not license_ok(lic):
        raise SystemExit(f"Licentie '{lic}' niet toegestaan voor {title}")
    DIR.mkdir(parents=True, exist_ok=True)
    # standaard-thumbnail (thumb.wikimedia.org), zoals Wikimedia vraagt
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(_get(ii.get("thumburl") or ii["url"]))).convert("RGB")
    im.thumbnail((1600, 1600))
    im.save(DIR / f"{slug}.jpg", quality=88)
    meta = {"title": title, "license": lic, "author": _clean(md.get("Artist", {}).get("value", "")),
            "source": ii.get("descriptionurl"), "credit": None}
    meta["credit"] = f"{meta['author'] or 'onbekend'} / Wikimedia Commons ({lic})"
    (DIR / f"{slug}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta


def credits(script):
    """Naamsvermeldingen voor alle foto's in een script (voor de caption)."""
    out = []
    for sc in script["scenes"]:
        slug = sc["visual"].get("photo")
        if slug and (DIR / f"{slug}.json").exists():
            c = json.loads((DIR / f"{slug}.json").read_text())["credit"]
            if c not in out:
                out.append(c)
    return out


if __name__ == "__main__":
    if sys.argv[1] == "zoek":
        for x in zoek(" ".join(sys.argv[2:])):
            print(("OK " if x["ok"] else "-- ") + f"{x['w']}x{x['h']} | {x['license']} | {x['title']} | {x['author']}")
    elif sys.argv[1] == "haal":
        print(haal(sys.argv[2], sys.argv[3]))
