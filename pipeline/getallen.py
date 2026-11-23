"""Getallen in de gesproken tekst omzetten naar Nederlandse woorden.

De meertalige stem leest "35%" soms in het Frans ("trente-cinq pourcent"). Uitgeschreven
Nederlandse woorden ("vijfendertig procent") leest hij altijd in het Nederlands.
De ondertitels blijven cijfers tonen: `to_spoken` geeft ook een lijst vervangingen terug
(gesproken woorden -> getoonde tekst) waarmee tts.py de woordtimings weer samenvoegt.
"""
import re

EENHEDEN = ["nul", "een", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien",
            "elf", "twaalf", "dertien", "veertien", "vijftien", "zestien", "zeventien", "achttien", "negentien"]
TIENTALLEN = {20: "twintig", 30: "dertig", 40: "veertig", 50: "vijftig", 60: "zestig",
              70: "zeventig", 80: "tachtig", 90: "negentig"}


def _onder100(n):
    if n < 20:
        return EENHEDEN[n]
    t, e = n // 10 * 10, n % 10
    if e == 0:
        return TIENTALLEN[t]
    eenheid = "één" if e == 1 else EENHEDEN[e]
    verbind = "ën" if eenheid.endswith("e") else "en"
    return eenheid + verbind + TIENTALLEN[t]


def _onder1000(n):
    h, r = divmod(n, 100)
    s = ("" if h == 0 else ("honderd" if h == 1 else EENHEDEN[h] + "honderd"))
    if r:
        s += _onder100(r)
    return s or "nul"


def getal(n: int) -> str:
    if n == 1:
        return "één"
    if n < 0:
        return "min " + getal(-n)
    if n < 1000:
        return _onder1000(n)
    if n < 1_000_000:
        d, r = divmod(n, 1000)
        s = ("duizend" if d == 1 else _onder1000(d) + "duizend")
        return s + (" " + _onder1000(r) if r else "")
    if n < 1_000_000_000:
        m, r = divmod(n, 1_000_000)
        s = getal(m) + " miljoen"
        return s + (" " + getal(r) if r else "")
    mld, r = divmod(n, 1_000_000_000)
    return getal(mld) + " miljard" + (" " + getal(r) if r else "")


def jaartal(n: int) -> str:
    if 1100 <= n <= 1999:
        h, r = divmod(n, 100)
        return _onder100(h) + "honderd" + (_onder100(r) if r else "")
    return getal(n)


def decimaal(txt: str) -> str:
    """'0,35' -> 'nul komma vijfendertig' ; '5,3' -> 'vijf komma drie'."""
    heel, dec = txt.split(",")
    return getal(int(heel.replace(".", ""))) + " komma " + (
        " ".join(EENHEDEN[int(c)] for c in dec) if dec.startswith("0") else getal(int(dec)))


NUM = r"\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?"
PATROON = re.compile(
    rf"(?P<cur>[€$])?(?P<num>{NUM})(?P<pct>%)?(?P<ord>de|ste|e)?(?![\w])"
    rf"|(?<=[A-Za-z])-(?P<suf>\d+)\b")


def _woorden(m):
    if m.group("suf"):
        return " " + getal(int(m.group("suf")))
    num = m.group("num")
    if "," in num:
        w = decimaal(num)
    else:
        n = int(num.replace(".", ""))
        is_jaar = "." not in num and len(num) == 4 and 1100 <= n <= 2099 and not m.group("cur") and not m.group("pct")
        w = jaartal(n) if is_jaar else getal(n)
    if m.group("ord"):
        w = {"een": "eerste", "drie": "derde", "acht": "achtste"}.get(w, w + ("ste" if w.endswith(("ig", "rd", "nd", "joen")) else "de"))
    if m.group("pct"):
        w += " procent"
    if m.group("cur"):
        w += " euro" if m.group("cur") == "€" else " dollar"
    return w


def to_spoken(text: str):
    """Geeft (gesproken tekst, vervangingen) terug. Vervanging = (gesproken woorden, getoond token)."""
    repl = []

    def sub(m):
        w = _woorden(m)
        repl.append((w.split(), m.group(0), bool(m.group("suf"))))
        return w

    return PATROON.sub(sub, text), repl


if __name__ == "__main__":
    for t in ["Plus 35%.", "€2.000 en 0,35% is €7.", "Op 10 maart 2000 sloot hij op 5.048.",
              "In 1993 en 2015.", "De Nasdaq-100.", "de 2de maand", "min 5,3% en 1,32%", "125 dollar, 170."]:
        print(t, "->", to_spoken(t)[0])
