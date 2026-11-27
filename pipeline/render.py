"""Rendert een verticale video (1080x1920) uit een script + timeline.

Elke scène heeft een `visual` met een `type`:
  hook     : kicker + grote tekst (+ sub)
  point    : genummerd punt met kop en korte tekst
  table    : rijen label/waarde (bv. tarieven)
  calc     : rekenvoorbeeld, regels verschijnen één voor één, met resultaat
  bars     : eenvoudige staafgrafiek
  outro    : call to action
De disclaimer verschijnt ALTIJD op de eindkaart, ongeacht het script.
"""
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config as C
from .tts import display_text

W, H, FPS = C.W, C.H, C.FPS
CONTENT_W = W - C.SAFE_LEFT - C.SAFE_RIGHT


# ---------------------------------------------------------------- helpers ---
def hexrgb(h, a=255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


COL = {k: hexrgb(v) for k, v in C.COLORS.items()}


@lru_cache(None)
def font(weight: str, size: int):
    return ImageFont.truetype(str(C.FONTS / f"Inter-{weight}.otf"), size)


def ease(x):  # ease-out cubic, 0..1
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_font(draw, text, weight, size, max_w, max_lines):
    while size > 30:
        f = font(weight, size)
        widest = max((draw.textlength(w, font=f) for w in text.split()), default=0)
        if len(wrap(draw, text, f, max_w)) <= max_lines and widest <= max_w:
            return f
        size -= 4
    return font(weight, size)


@lru_cache(None)
def background():
    """Rustige achtergrond: verticaal verloop + twee zachte lichtvlekken."""
    top, bot = np.array(COL["bg_top"][:3]), np.array(COL["bg_bottom"][:3])
    t = np.linspace(0, 1, H)[:, None, None]
    arr = (top * (1 - t) + bot * t).repeat(W, axis=1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-300, -200, 700, 800), fill=hexrgb(C.COLORS["mint"], 38))
    g.ellipse((500, 1300, 1500, 2300), fill=hexrgb(C.COLORS["yellow"], 22))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.alpha_composite(img, glow)


PAD = 140  # extra rand zodat de achtergrond traag kan bewegen


@lru_cache(None)
def background_big():
    """Grotere versie van de achtergrond met lichtvlekken; per frame verschuift de uitsnede een beetje."""
    BW, BH = W + 2 * PAD, H + 2 * PAD
    top, bot = np.array(COL["bg_top"][:3]), np.array(COL["bg_bottom"][:3])
    t = np.linspace(0, 1, BH)[:, None, None]
    arr = (top * (1 - t) + bot * t).repeat(BW, axis=1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    glow = Image.new("RGBA", (BW, BH), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-160, -60, 840, 940), fill=hexrgb(C.COLORS["mint"], 44))
    g.ellipse((640, 1440, 1640, 2440), fill=hexrgb(C.COLORS["yellow"], 26))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.alpha_composite(img, glow)


def moving_background(t):
    """Trage, rustige beweging (geen stilstaand beeld, zonder af te leiden)."""
    ox = PAD + int(PAD * 0.8 * math.sin(2 * math.pi * t / 13))
    oy = PAD + int(PAD * 0.6 * math.cos(2 * math.pi * t / 17))
    return background_big().crop((ox, oy, ox + W, oy + H))


def brand_bar(d):
    """Kanaalnaam bovenaan."""
    f = font("ExtraBold", 40)
    x, y = C.SAFE_LEFT, C.SAFE_TOP - 90
    d.rounded_rectangle((x, y + 6, x + 18, y + 46), 6, fill=COL["mint"])
    d.text((x + 34, y), C.CHANNEL_NAME, font=f, fill=COL["text"])


def alpha(c, a):
    return c[:3] + (int(max(0, min(1, a)) * 255),)


def text_block(d, x, y, lines, fnt, fill, a=1.0, spacing=1.18):
    lh = int(fnt.size * spacing)
    for i, ln in enumerate(lines):
        d.text((x, y + i * lh), ln, font=fnt, fill=alpha(fill, a))
    return y + len(lines) * lh


def highlight_text(d, x, y, text, fnt, a, max_w, spacing=1.15):
    """Tekst waarin *woorden* tussen sterretjes geel gekleurd worden."""
    tokens = text.split()
    lh = int(fnt.size * spacing)
    cx, cy = x, y
    space = d.textlength(" ", font=fnt)
    for tok in tokens:
        hl = tok.startswith("*") or tok.endswith("*") or tok.strip(".,!?").endswith("*")
        clean = tok.replace("*", "")
        wlen = d.textlength(clean, font=fnt)
        if cx + wlen > x + max_w and cx > x:
            cx, cy = x, cy + lh
        d.text((cx, cy), clean, font=fnt, fill=alpha(COL["yellow"] if hl else COL["text"], a))
        cx += wlen + space
    return cy + lh


def measure_highlight(d, text, fnt, max_w, spacing=1.15):
    return len(wrap(d, text.replace("*", ""), fnt, max_w)) * int(fnt.size * spacing)


# ---------------------------------------------------------------- scenes ----
def draw_hook(d, v, t, dur):
    y = 430
    if v.get("kicker"):
        a = ease(t / 0.35)
        f = font("Bold", 46)
        tw = d.textlength(v["kicker"].upper(), font=f)
        d.rounded_rectangle((C.SAFE_LEFT, y, C.SAFE_LEFT + tw + 56, y + 80), 40,
                            fill=alpha(COL["mint"], a))
        d.text((C.SAFE_LEFT + 28, y + 12), v["kicker"].upper(), font=f, fill=alpha(COL["bg_top"], a))
        y += 140
    f = fit_font(d, v["big"].replace("*", ""), "Black", 108, CONTENT_W, 5)
    a = ease((t - 0.15) / 0.4)
    off = int((1 - a) * 40)
    y = highlight_text(d, C.SAFE_LEFT, y + off, v["big"], f, a, CONTENT_W, 1.1)
    if v.get("sub"):
        a2 = ease((t - 0.8) / 0.4)
        fs = font("SemiBold", 52)
        text_block(d, C.SAFE_LEFT, y + 40, wrap(d, v["sub"], fs, CONTENT_W), fs, COL["muted"], a2)


def draw_point(d, v, t, dur):
    y = 430
    a = ease(t / 0.35)
    # nummer-badge
    r = 70
    cx, cy = C.SAFE_LEFT + r, y + r
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=alpha(COL["mint"], a))
    fn = font("Black", 80)
    num = str(v.get("n", ""))
    tw = d.textlength(num, font=fn)
    d.text((cx - tw / 2, cy - 50), num, font=fn, fill=alpha(COL["bg_top"], a))
    y += 2 * r + 50
    fh = fit_font(d, v["head"].replace("*", ""), "Black", 92, CONTENT_W, 4)
    a = ease((t - 0.15) / 0.4)
    y = highlight_text(d, C.SAFE_LEFT, y + int((1 - a) * 30), v["head"], fh, a, CONTENT_W, 1.1)
    if v.get("body"):
        a2 = ease((t - 0.6) / 0.4)
        fb = font("SemiBold", 52)
        text_block(d, C.SAFE_LEFT, y + 36, wrap(d, v["body"], fb, CONTENT_W), fb, COL["muted"], a2)


def draw_table(d, v, t, dur):
    y = 400
    fh = font("Black", 76)
    y = text_block(d, C.SAFE_LEFT, y, wrap(d, v["title"], fh, CONTENT_W), fh, COL["text"], ease(t / 0.3)) + 40
    rows = v["rows"]
    row_h = 230
    for i, row in enumerate(rows):
        st = v["at"][i] if v.get("at") else 0.35 + i * 0.45
        a = ease((t - st) / 0.35)
        if a <= 0:
            continue
        x0 = C.SAFE_LEFT + int((1 - a) * 60)
        d.rounded_rectangle((x0, y, x0 + CONTENT_W, y + row_h - 24), 28,
                            fill=alpha(COL["card"], a), outline=alpha(COL["card_line"], a), width=3)
        fv = font("Black", 92)
        d.text((x0 + 36, y + (row_h - 24) / 2 - 56), row["value"], font=fv, fill=alpha(COL["yellow"], a))
        vw = d.textlength(row["value"], font=fv)
        lx, lw = x0 + vw + 70, CONTENT_W - vw - 110
        fl = fit_font(d, row["label"], "SemiBold", 46, lw, 2)
        lines = wrap(d, row["label"], fl, lw)
        fm = font("Bold", 40)
        block_h = len(lines) * int(fl.size * 1.15) + (52 if row.get("max") else 0)
        ly = y + (row_h - 24) / 2 - block_h / 2
        ly = text_block(d, lx, ly, lines, fl, COL["text"], a, 1.15)
        if row.get("max"):
            d.text((lx, ly + 6), row["max"], font=fm, fill=alpha(COL["mint"], a))
        y += row_h
    if v.get("note"):
        fn = font("Medium", 38)
        text_block(d, C.SAFE_LEFT, y + 10, wrap(d, v["note"], fn, CONTENT_W), fn, COL["muted"],
                   ease((t - 0.4 - len(rows) * 0.45) / 0.4))


def draw_calc(d, v, t, dur):
    y = 400
    fh = font("Black", 76)
    y = text_block(d, C.SAFE_LEFT, y, wrap(d, v["title"], fh, CONTENT_W), fh, COL["text"], ease(t / 0.3)) + 10
    if v.get("note"):  # notitie boven de kaart, zodat ze nooit onder de ondertitels zit
        fn = font("Medium", 38)
        y = text_block(d, C.SAFE_LEFT, y, wrap(d, v["note"], fn, CONTENT_W), fn, COL["muted"], ease(t / 0.3)) + 20
    else:
        y += 20
    lines = v["lines"]
    # regels verdelen over de scène: elke regel verschijnt wanneer hij aan bod komt
    starts = v.get("at") or [0.4 + i * (dur * 0.75 / max(1, len(lines))) for i in range(len(lines))]
    pad = 44
    # regelhoogte zo kiezen dat de kaart nooit tot bij de ondertitels komt
    lh = int(min(150, (C.SUB_Y - 110 - y - 2 * pad + 20) / max(1, len(lines))))
    box_h = len(lines) * lh + 2 * pad - 20
    box_a = ease(t / 0.3)
    d.rounded_rectangle((C.SAFE_LEFT, y, C.SAFE_LEFT + CONTENT_W, y + box_h), 36,
                        fill=alpha(COL["card"], box_a), outline=alpha(COL["card_line"], box_a), width=3)
    ly = y + pad
    for i, ln in enumerate(lines):
        a = ease((t - starts[i]) / 0.35)
        if a > 0:
            is_res = ln.get("result")
            fv = font("Black", 80 if is_res else 70)
            colv = COL["coral"] if is_res else COL["yellow"] if ln.get("hl") else COL["text"]
            val = ln["value"]
            vw = d.textlength(val, font=fv)
            room = CONTENT_W - 2 * pad - vw - 28  # label mag nooit onder het bedrag lopen
            size = 50
            while size > 30 and d.textlength(ln["label"], font=font("SemiBold", size)) > room:
                size -= 2
            fl = font("SemiBold", size)
            d.text((C.SAFE_LEFT + pad, ly + 44 + (50 - size) // 2), ln["label"], font=fl, fill=alpha(COL["muted"], a))
            d.text((C.SAFE_LEFT + CONTENT_W - pad - vw, ly + 30 - (8 if is_res else 0)), val, font=fv,
                   fill=alpha(colv, a))
            if i < len(lines) - 1:
                d.line((C.SAFE_LEFT + pad, ly + lh - 14, C.SAFE_LEFT + CONTENT_W - pad, ly + lh - 14),
                       fill=alpha(COL["card_line"], a), width=2)
        ly += lh


def draw_bars(d, v, t, dur):
    """Staafgrafiek. Negatieve waarden hangen naar beneden vanaf een nullijn bovenaan."""
    y = 400
    fh = font("Black", 76)
    y = text_block(d, C.SAFE_LEFT, y, wrap(d, v["title"], fh, CONTENT_W), fh, COL["text"], ease(t / 0.3)) + 40
    bars = v["bars"]
    neg = any(b["value"] < 0 for b in bars)
    mx = max(abs(b["value"]) for b in bars)
    chart_h = 520
    gap = 34
    bw = (CONTENT_W - gap * (len(bars) - 1)) / len(bars)
    fl, fv = font("SemiBold", 38), font("Black", 52)
    if neg:
        zero = y + 70  # labels boven de nullijn
        d.line((C.SAFE_LEFT, zero, C.SAFE_LEFT + CONTENT_W, zero), fill=COL["card_line"], width=3)
    else:
        zero = y + chart_h
    for i, b in enumerate(bars):
        st = v["at"][i] if v.get("at") else 0.3 + i * 0.3
        p = ease((t - st) / 0.8)
        h = chart_h * 0.8 * abs(b["value"]) / mx * p
        x0 = C.SAFE_LEFT + i * (bw + gap)
        col = COL[b.get("color", "coral" if b["value"] < 0 else "mint")]
        lab = b.get("display", str(b["value"]))
        tw = d.textlength(lab, font=fv)
        if neg:
            for j, ln in enumerate(wrap(d, b["label"], fl, bw + gap - 6)):
                lw = d.textlength(ln, font=fl)
                d.text((x0 + bw / 2 - lw / 2, zero - 56 - j * 0), ln, font=fl, fill=COL["muted"])
            if h > 1:
                d.rounded_rectangle((x0, zero + 4, x0 + bw, zero + 4 + h), 16, fill=col)
            if p > 0.05:
                d.text((x0 + bw / 2 - tw / 2, zero + 18 + h), lab, font=fv, fill=alpha(COL["text"], p))
        else:
            d.rounded_rectangle((x0, zero - max(h, 2), x0 + bw, zero), 18, fill=col)
            if p > 0.05:
                d.text((x0 + bw / 2 - tw / 2, zero - h - 74), lab, font=fv, fill=alpha(COL["text"], p))
            for j, ln in enumerate(wrap(d, b["label"], fl, bw)):
                lw = d.textlength(ln, font=fl)
                d.text((x0 + bw / 2 - lw / 2, zero + 24 + j * 46), ln, font=fl, fill=COL["muted"])
    if v.get("note"):
        fn = font("Medium", 36)
        text_block(d, C.SAFE_LEFT, zero + chart_h * 0.8 + 110 if neg else zero + 110, wrap(d, v["note"], fn, CONTENT_W),
                   fn, COL["muted"], ease((t - 1.0) / 0.4))


def draw_line(d, v, t, dur):
    """Lijngrafiek die zich tekent: bv. slotkoersen van een week."""
    y = 400
    fh = font("Black", 76)
    y = text_block(d, C.SAFE_LEFT, y, wrap(d, v["title"], fh, CONTENT_W), fh, COL["text"], ease(t / 0.3)) + 10
    if v.get("sub"):
        fs = font("Medium", 38)
        y = text_block(d, C.SAFE_LEFT, y, wrap(d, v["sub"], fs, CONTENT_W), fs, COL["muted"], ease(t / 0.3)) + 30
    pts = v["points"]
    vals = [p["value"] for p in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    x0, x1 = C.SAFE_LEFT + 10, C.SAFE_LEFT + CONTENT_W - 10
    top, bot = y + 90, y + 560
    X = lambda i: x0 + (x1 - x0) * i / (len(pts) - 1)
    Y = lambda val: bot - (bot - top) * (val - lo) / (hi - lo)
    for k in range(4):  # zacht raster
        gy = top + (bot - top) * k / 3
        d.line((x0, gy, x1, gy), fill=alpha(COL["card_line"], 0.8), width=2)
    prog = ease((t - 0.4) / max(1.2, dur * 0.55)) * (len(pts) - 1)
    full = int(prog)
    coords = [(X(i), Y(vals[i])) for i in range(full + 1)]
    if full < len(pts) - 1:
        f = prog - full
        coords.append((X(full) + (X(full + 1) - X(full)) * f, Y(vals[full]) + (Y(vals[full + 1]) - Y(vals[full])) * f))
    if len(coords) > 1:
        area = coords + [(coords[-1][0], bot), (coords[0][0], bot)]
        d.polygon(area, fill=alpha(COL[v.get("color", "coral")], 0.18))
        d.line(coords, fill=COL[v.get("color", "coral")], width=9, joint="curve")
    fl = font("SemiBold", 36)
    fvv = font("Bold", 38)
    for i, ptn in enumerate(pts):
        lw = d.textlength(ptn["label"], font=fl)
        d.text((X(i) - lw / 2, bot + 22), ptn["label"], font=fl, fill=COL["muted"])
        if i <= prog + 1e-6:
            r = 11 if i in (0, len(pts) - 1) else 8
            d.ellipse((X(i) - r, Y(vals[i]) - r, X(i) + r, Y(vals[i]) + r), fill=COL["text"])
    # start- en eindwaarde
    if pts[0].get("display"):
        d.text((X(0), Y(vals[0]) - 66), pts[0]["display"], font=fvv, fill=COL["text"])
    if prog >= len(pts) - 1 - 1e-6 and pts[-1].get("display"):
        a = ease((t - 0.4 - max(1.2, dur * 0.55)) / 0.4)
        txt = pts[-1]["display"]
        tw = d.textlength(txt, font=fvv)
        d.text((X(len(pts) - 1) - tw, Y(vals[-1]) + 26), txt, font=fvv, fill=alpha(COL["text"], a))
        if v.get("badge"):
            fb = font("Black", 64)
            bw_ = d.textlength(v["badge"], font=fb)
            bx, by = x1 - bw_ - 40, top - 70
            d.rounded_rectangle((bx - 10, by - 6, bx + bw_ + 30, by + 84), 24, fill=alpha(COL["coral"], a))
            d.text((bx + 10, by + 4), v["badge"], font=fb, fill=alpha(COL["bg_top"], a))


def draw_slam(d, v, t, dur):
    """Opvallend: één of twee reuzenwoorden die met een 'klap' binnenkomen (schaal 1,5 → 1)."""
    lines = v["words"]  # bv. ["TERUG."] of ["TERUG.", "+35%"]
    base = d._image
    y = v.get("y", 620)
    for i, word in enumerate(lines):
        st = v["at"][i] if v.get("at") and i < len(v["at"]) else i * v.get("stagger", 0.55)
        p = (t - st) / 0.28
        if p <= 0:
            continue
        sc = 1 + 0.5 * (1 - ease(p))
        cols = v.get("colors", ["text", "yellow"])
        col = COL[cols[i % len(cols)]]
        sizes = v.get("sizes")
        f = fit_font(d, word, "Black", sizes[i] if sizes and i < len(sizes) else v.get("size", 230), CONTENT_W, 1)
        tw = int(d.textlength(word, font=f)) + 20
        th = int(f.size * 1.25)
        tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((10, 0), word, font=f, fill=alpha(col, min(1, p * 2)))
        if sc != 1:
            tile = tile.resize((int(tw * sc), int(th * sc)), Image.LANCZOS)
        x = (W - tile.width) // 2 - 20
        base.alpha_composite(tile, (max(0, x), int(y - (tile.height - th) / 2)))
        y += th + 20
    if v.get("sub"):
        fs = font("Bold", 52)
        sub_at = v["at"][len(lines)] if v.get("at") and len(v["at"]) > len(lines) else len(lines) * v.get("stagger", 0.55)
        a = ease((t - sub_at) / 0.4)
        for j, ln in enumerate(wrap(d, v["sub"], fs, CONTENT_W)):
            lw = d.textlength(ln, font=fs)
            d.text(((W - lw) / 2 - 20, y + 30 + j * 64), ln, font=fs, fill=alpha(COL["muted"], a))
    if v.get("kicker"):
        fk = font("Bold", 46)
        kt = v["kicker"].upper()
        kw = d.textlength(kt, font=fk)
        kx = (W - kw) / 2 - 48
        d.rounded_rectangle((kx, 430, kx + kw + 56, 510), 40, fill=COL["coral"])
        d.text((kx + 28, 442), kt, font=fk, fill=COL["bg_top"])


def draw_outro(d, v, t, dur):
    y = 480
    f = fit_font(d, v.get("big", "Volg voor meer").replace("*", ""), "Black", 104, CONTENT_W, 3)
    a = ease(t / 0.4)
    y = highlight_text(d, C.SAFE_LEFT, y, v.get("big", "Volg voor *meer*"), f, a, CONTENT_W, 1.1)
    fh = font("ExtraBold", 60)
    a2 = ease((t - 0.4) / 0.4)
    tw = d.textlength(C.CHANNEL_HANDLE, font=fh)
    d.rounded_rectangle((C.SAFE_LEFT, y + 50, C.SAFE_LEFT + tw + 70, y + 150), 50,
                        fill=alpha(COL["mint"], a2))
    d.text((C.SAFE_LEFT + 35, y + 64), C.CHANNEL_HANDLE, font=fh, fill=alpha(COL["bg_top"], a2))
    draw_disclaimer(d, 1.0, max(1130, y + 210))


def draw_disclaimer(d, a, y=1130):
    """Verplichte disclaimer, groot en goed leesbaar boven de ondertitelzone."""
    f = font("Bold", 46)
    txt = C.DISCLAIMER
    tw = d.textlength(txt, font=f)
    y = min(y, C.SUB_Y - 150)  # altijd boven de ondertitels
    x = (W - tw) / 2 - 40
    d.rounded_rectangle((x - 10, y - 18, x + tw + 90, y + 82), 22,
                        fill=alpha(COL["bg_top"], 0.85 * a), outline=alpha(COL["yellow"], a), width=4)
    d.text((x + 40, y), txt, font=f, fill=alpha(COL["yellow"], a))


# ------------------------------------------------- stijl 'uitleg' (27/11) ---
# Naar het voorbeeld dat veel views haalt: zwarte achtergrond, één groot 3D-icoon of cijfer in het midden
# dat elke 1-2 s wisselt (op het woord dat het noemt), cijfers die optellen, korte ondertitels van 1-2 woorden.
import re as _re

STAGE_TOP = 330


def ease_back(x):
    x = max(0.0, min(1.0, x))
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def _paste(base, img, cx, cy, sc=1.0, a=1.0):
    if sc <= 0.02 or a <= 0.01:
        return
    if sc != 1:
        img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.BILINEAR)
    if a < 1:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    base.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2)))


def _text_tile(text, weight, size, col, max_w=CONTENT_W + 40):
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    f = fit_font(tmp, text, weight, size, max_w, 1)
    tw, th = int(tmp.textlength(text, font=f)) + 24, int(f.size * 1.3)
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((12, int(f.size * 0.05)), text, font=f, fill=col)
    return tile


_NUM = _re.compile(r"\d[\d.]*(?:,\d+)?")


def _num_parts(s):
    m = _NUM.search(s)
    if not m:
        return None
    raw = m.group(0)
    dec = len(raw.split(",")[1]) if "," in raw else 0
    val = float(raw.replace(".", "").replace(",", "."))
    return s[:m.start()], val, dec, s[m.end():]


def _fmt(val, dec):
    txt = f"{val:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return txt


def _photo_card(slug, w, h):
    return _photo_card_cached(slug, w, h)


@lru_cache(16)
def _photo_card_cached(slug, w, h):
    im = Image.open(C.ROOT / "assets" / "fotos" / f"{slug}.jpg").convert("RGB")
    sc = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
    x0, y0 = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((x0, y0, x0 + w, y0 + h)).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 48, fill=255)
    im.putalpha(mask)
    return im


def draw_beats(d, v, t, dur):
    """Eén 'beat' tegelijk in beeld; de volgende beat verschijnt op zijn cue-woord en vervangt de vorige."""
    from . import iconen
    base = d._image
    beats = v["beats"]
    at = v.get("at") or [i * 1.6 for i in range(len(beats))]
    cur = max([i for i, a in enumerate(at) if t >= a] or [0])
    b = beats[cur]
    p = (t - at[cur]) / 0.28 if t >= at[cur] else 0.0
    if p <= 0 and not (cur == 0 and at[0] < 0):
        return
    pop = 0.55 + 0.45 * ease_back(p)
    a = min(1.0, p * 3)
    end_fade = 1.0
    if v.get("eind") and t > dur:
        end_fade = max(0.0, 1 - (t - dur) / 0.3)
    a *= end_fade
    cx = (C.SAFE_LEFT + W - C.SAFE_RIGHT) / 2 + 10
    y = STAGE_TOP
    accent = COL[b.get("kleur", "yellow")]
    if end_fade <= 0.01:
        b = {}
    if b.get("label"):
        f = font("ExtraBold", 40)
        lt = b["label"].upper()
        lw = d.textlength(lt, font=f)
        d.rounded_rectangle((cx - lw / 2 - 26, y, cx + lw / 2 + 26, y + 66), 33, fill=alpha(COL["card"], a))
        d.text((cx - lw / 2, y + 9), lt, font=f, fill=alpha(COL["muted"], a))
        y += 96
    if b.get("num"):
        parts = _num_parts(b["num"])
        shown = b["num"]
        if parts and b.get("tel", True):
            pre, val, dec, post = parts
            start = b.get("van", 0)
            if start == "vorige":
                prev = next((x for x in reversed(beats[:cur]) if x.get("num")), None)
                start = _num_parts(prev["num"])[1] if prev and _num_parts(prev["num"]) else 0
            k = ease(max(0.0, (t - at[cur]) / 0.75)) if not (cur == 0 and at[0] < 0) else 1.0
            shown = pre + _fmt(start + (val - start) * k, dec) + post
        tile = _text_tile(shown, "Black", b.get("size", 250 if not b.get("icon") else 220), alpha(accent, 1))
        _paste(base, tile, cx, y + tile.height / 2, pop, a)
        y += tile.height + 10
    if b.get("tekst"):
        col = COL[b.get("tekstkleur", "text")]
        tile = _text_tile(b["tekst"], "Black", b.get("size", 150 if (b.get("icon") or b.get("icons")) else 190), alpha(col, 1))
        _paste(base, tile, cx, y + tile.height / 2, pop, a)
        y += tile.height + 10
    bottom = C.SUB_Y_UITLEG - 120
    if b.get("foto"):
        h = int(min(860, bottom - y - 20))
        card = _photo_card(b["foto"], 760, h)
        _paste(base, card, cx, y + 20 + h / 2, 0.85 + 0.15 * ease(p), a)
    elif b.get("icons"):
        n = len(b["icons"])
        size = 300 if n <= 2 else 250
        gap = (CONTENT_W + 40) / n
        cy = (y + bottom) / 2
        for j, key in enumerate(b["icons"]):
            pj = (t - at[cur] - 0.12 * j) / 0.28
            if pj <= 0 and not (cur == 0 and at[0] < 0):
                continue
            img = iconen.beeld(key, size)
            _paste(base, img, C.SAFE_LEFT - 20 + gap * (j + 0.5), cy, 0.55 + 0.45 * ease_back(pj), min(1, pj * 3) * end_fade)
    elif b.get("icon"):
        space = bottom - y
        size = int(max(300, min(b.get("iconsize", 620), space - 20)))
        img = iconen.beeld(b["icon"], size)
        _paste(base, img, cx, y + space / 2, pop, a)
    if b.get("bron"):
        f = font("Medium", 30)
        bw = d.textlength(b["bron"], font=f)
        d.text((cx - bw / 2, C.SUB_Y_UITLEG + 90), b["bron"], font=f, fill=alpha(COL["muted"], a))
    if v.get("eind") and t > dur:
        k = ease((t - dur) / 0.4)
        f = font("Black", 84)
        hw = d.textlength(C.CHANNEL_HANDLE, font=f)
        d.text((cx - hw / 2, 620), C.CHANNEL_HANDLE, font=f, fill=alpha(COL["mint"], k))
        draw_disclaimer(d, k, 800)


DRAW = {"hook": draw_hook, "point": draw_point, "table": draw_table,
        "calc": draw_calc, "bars": draw_bars, "line": draw_line, "slam": draw_slam, "outro": draw_outro,
        "beats": draw_beats}


def progress_bar(d, frac):
    y = H - 14
    d.rectangle((0, y, W, H), fill=alpha(COL["card"], 1))
    d.rectangle((0, y, int(W * frac), H), fill=COL["mint"])


def render_layer(scene, t_in_scene, dur):
    """Alleen de inhoud (tekst, grafieken), transparant; wordt gecachet zolang er niets beweegt."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    brand_bar(d)
    v = scene["visual"]
    DRAW[v["type"]](d, v, t_in_scene, dur)
    return layer


@lru_cache(8)
def _photo_base(slug, dim):
    """Foto schermvullend (cover) + donkere laag zodat tekst leesbaar blijft; onderaan extra donker voor ondertitels."""
    im = Image.open(C.ROOT / "assets" / "fotos" / f"{slug}.jpg").convert("RGB")
    BW, BH = int(W * 1.1), int(H * 1.1)
    sc = max(BW / im.width, BH / im.height)
    im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
    x0, y0 = (im.width - BW) // 2, (im.height - BH) // 2
    im = im.crop((x0, y0, x0 + BW, y0 + BH)).convert("RGBA")
    shade = np.zeros((BH, BW, 4), np.uint8)
    shade[..., :3] = COL["bg_top"][:3]
    grad = np.linspace(dim, min(0.92, dim + 0.25), BH)[:, None]  # onderaan donkerder (ondertitels)
    shade[..., 3] = (grad * 255).astype(np.uint8)
    return Image.alpha_composite(im, Image.fromarray(shade, "RGBA"))


def photo_background(slug, t_local, dur, dim=0.62):
    """Traag inzoomen (Ken Burns): rustige beweging, geen stilstaand beeld."""
    base = _photo_base(slug, dim)
    z = 1 + 0.09 * min(1.0, max(0.0, t_local / max(dur, 1)))
    cw, ch = int(base.width / z), int(base.height / z)
    x0, y0 = (base.width - cw) // 2, (base.height - ch) // 2
    return base.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)


def punch_curve(dt):
    """0 -> 1 -> 0 in ~0,3 s rond het moment dat een cijfer verschijnt."""
    if dt < 0 or dt > 0.3:
        return 0.0
    return math.sin(math.pi * dt / 0.3)


def punch(layer, scale):
    w, h = int(W * scale), int(H * scale)
    big = layer.resize((w, h), Image.BILINEAR)
    x0, y0 = (w - W) // 2, (h - H) // 2
    return big.crop((x0, y0, x0 + W, y0 + H))


def make_sfx(path, total, whooshes, pops, sr=48000):
    """Zelf gesynthetiseerde, rechtenvrije effecten: zachte 'whoosh' bij scènewissels, 'tik' bij cijfers."""
    import wave
    n = int(total * sr) + sr
    out = np.zeros(n, np.float32)
    rng = np.random.default_rng(7)
    # whoosh: gefilterde ruis die aanzwelt en wegsterft (0,35 s)
    L = int(0.35 * sr)
    noise = rng.standard_normal(L).astype(np.float32)
    k = 40
    noise = np.convolve(noise, np.ones(k) / k, mode="same")
    env = np.sin(np.linspace(0, np.pi, L)) ** 2
    wh = noise * env * 0.9
    # tik/pop: korte sinus met snel uitsterven (0,09 s)
    Lp = int(0.09 * sr)
    tt = np.arange(Lp) / sr
    pop = np.sin(2 * np.pi * (1300 - 5000 * tt) * tt) * np.exp(-tt * 45) * 0.7
    for t0, snd in [(w, wh) for w in whooshes] + [(p, pop) for p in pops]:
        i0 = int(max(0, t0) * sr)
        seg = snd[: max(0, min(len(snd), n - i0))]
        out[i0:i0 + len(seg)] += seg
    out = np.clip(out, -1, 1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes((out * 32767).astype(np.int16).tobytes())


@lru_cache(None)
def zwart():
    """Achtergrond van de uitleg-stijl: bijna zwart met een heel zachte lichtkern achter het icoon."""
    img = Image.new("RGBA", (W, H), (10, 10, 12, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((90, 380, 990, 1280), fill=(255, 255, 255, 14))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(140)))


def compose(layer, t, frac, bg=None):
    arr = np.asarray(Image.alpha_composite(bg if bg is not None else moving_background(t), layer).convert("RGB")).copy()
    y = H - 14
    arr[y:, :] = COL["card"][:3]
    arr[y:, : int(W * frac)] = COL["mint"][:3]
    return arr.tobytes()


def render_frame(scene, t_in_scene, dur, frac):
    img = background().copy()
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    brand_bar(d)
    v = scene["visual"]
    DRAW[v["type"]](d, v, t_in_scene, dur)
    progress_bar(d, frac)
    return Image.alpha_composite(img, layer).convert("RGB")


# ------------------------------------------------------------- subtitles ----
def ass_time(s):
    s = max(0, s)
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def chunk_words(words, max_words=3, max_chars=20, pause=0.22):
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur and (cur[-1].get("eos") or w["start"] - cur[-1]["end"] > pause):  # zinsgrens of pauze = nieuwe regel
            chunks.append(cur)
            cur = []
        cur.append(w)
        txt = " ".join(x["text"] for x in cur)
        if len(cur) >= max_words or len(txt) >= max_chars or w["text"][-1] in ".,!?:":
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words, path: Path, hide=(), stijl=None):
    words = [w for w in words if not any(a - 0.05 <= w["start"] < b for a, b in hide)]
    uitleg = stijl == "uitleg"
    def bgr(h):
        h = h.lstrip("#")
        return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Inter Black,{96 if uitleg else 84},{bgr(C.COLORS['text'])},&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,7,3,5,{C.SAFE_LEFT},{C.SAFE_RIGHT},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    yellow = bgr(C.COLORS["yellow"])
    pos = f"{{\\an5\\pos({(C.SAFE_LEFT + W - C.SAFE_RIGHT) // 2},{C.SUB_Y_UITLEG if uitleg else C.SUB_Y})}}"
    # uitleg-stijl: 1-2 woorden tegelijk, in hoofdletters (zoals het voorbeeld)
    chunks = chunk_words(words, 2, 14) if uitleg else chunk_words(words)
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else ch[-1]["end"] + 0.4
        for wi, w in enumerate(ch):
            start = w["start"]
            end = ch[wi + 1]["start"] if wi + 1 < len(ch) else min(nxt, ch[-1]["end"] + 0.6)
            parts = []
            for k, x in enumerate(ch):
                t = x["text"].replace("{", "").replace("}", "")
                t = t.upper() if uitleg else t
                parts.append(f"{{\\c{yellow}}}{t}{{\\c}}" if k == wi else t)
            # uitleg-stijl: lange woorden ('BEDRIJFSVOORHEFFING') verkleinen zodat ze binnen het beeld blijven
            n_chars = len(" ".join(x["text"] for x in ch))
            fit = min(100, int(100 * 15 / max(1, n_chars))) if uitleg else 100
            pop = (f"{{\\fscx{int(fit * 1.08)}\\fscy{int(fit * 1.08)}\\t(0,90,\\fscx{fit}\\fscy{fit})}}" if wi == 0
                   else f"{{\\fscx{fit}\\fscy{fit}}}")
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{pos}{pop}{' '.join(parts)}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ main ----
def render_video(script: dict, timing: dict, out_mp4: Path, work: Path):
    work.mkdir(parents=True, exist_ok=True)
    scenes = script["scenes"]
    total = timing["duration"] + C.OUTRO_HOLD
    n_frames = int(math.ceil(total * FPS))
    ass = work / f"{script['id']}.ass"
    # geen ondertitels waar het beeld zelf al de gesproken woorden toont (slam), anders staat er 2x tekst
    hide = [(t["start"], t["end"] + C.SCENE_GAP) for sc, t in zip(script["scenes"], timing["scenes"])
            if not sc["visual"].get("subs", sc["visual"]["type"] != "slam")]
    stijl = script.get("stijl")
    fx_voice = C.VOICE_FX_UITLEG if stijl == "uitleg" else C.VOICE_FX
    if timing.get("engine") == "chatterbox":  # klinkt al natuurlijk: geen kamerklank, alleen gelijkmatig volume
        fx_voice = C.VOICE_FX_CB
    build_ass(timing["words"], ass, hide, stijl)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(config_path(timing["audio"])),
           "-filter_complex", f"[0:v]ass={ass}:fontsdir={C.FONTS}[v];[1:a]{fx_voice}apad,loudnorm=I=-14:TP=-1.5[a]",
           "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_mp4)]
    sc_times = timing["scenes"]
    apply_cues(scenes, sc_times, timing["words"])
    v0 = scenes[0]["visual"]
    if v0["type"] in ("slam", "beats") and v0.get("at"):
        v0["at"][0] = -1.0  # eerste reuzenwoord staat er al op frame 0
    # --- levendiger: korte 'punch'-zoom en zelfgemaakte geluidseffecten op belangrijke momenten ---
    punches = []   # absolute tijden: cijfers/regels die verschijnen
    whooshes = []  # scènewissels
    for i, (sc, tm) in enumerate(zip(scenes, sc_times)):
        v = sc["visual"]
        if i > 0:
            whooshes.append(tm["start"] - 0.12)
        for a in (v.get("at") or []):
            if a >= 0:
                punches.append(tm["start"] + a)
    if getattr(C, "SFX", True):
        sfx = work / f"{script['id']}.sfx.wav"
        make_sfx(sfx, total, whooshes, punches)
        cmd[cmd.index("-filter_complex") + 1] = (
            f"[0:v]ass={ass}:fontsdir={C.FONTS}[v];[1:a]{fx_voice}apad,loudnorm=I=-14:TP=-1.5[vo];"
            f"[2:a]volume={C.SFX_VOLUME}[fx];[vo][fx]amix=inputs=2:duration=first:normalize=0[a]")
        cmd[cmd.index("-filter_complex"):cmd.index("-filter_complex")] = ["-i", str(sfx)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache = {}
    for fi in range(n_frames):
        t = fi / FPS
        idx = next((i for i, s in enumerate(sc_times) if t < s["end"] + C.SCENE_GAP), len(scenes) - 1)
        s = sc_times[idx]
        dur = s["end"] - s["start"]
        local = t - s["start"]
        # statische frames hergebruiken zodra de animaties klaar zijn
        anim_end = animation_end(scenes[idx]["visual"], dur)
        key = (idx, round(local * FPS) if local < anim_end else "static")
        if key not in cache:
            # EERSTE BEELD MOET METEEN DE HOOK TONEN (kijkers beslissen in 0,5 s; TikTok gebruikt het als voorbeeld):
            # in de openingsscène staat de hooktekst er vanaf frame 0, zonder fade-in.
            draw_t = local
            if idx == 0 and scenes[0]["visual"]["type"] == "hook":
                draw_t = local + 2.0
            cache = {key: render_layer(scenes[idx], draw_t, dur)}
        v = scenes[idx]["visual"]
        bg = photo_background(v["photo"], local, dur + C.SCENE_GAP, v.get("photo_dim", 0.62)) if v.get("photo") else (
            zwart() if stijl == "uitleg" else None)
        layer = cache[key]
        pk = max((punch_curve(t - pt) for pt in punches), default=0.0)
        if pk > 0.001:
            layer = punch(layer, 1 + C.PUNCH * pk)
        proc.stdin.write(compose(layer, t, fi / n_frames, bg))
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg faalde")
    return out_mp4


def animation_end(v, dur):
    """Tot wanneer beweegt er iets in deze scène? Daarna mag het beeld gecachet worden."""
    end = max([2.0] + v.get("at", [])) + 1.2
    if v["type"] == "line":
        end = max(end, 0.4 + max(1.2, dur * 0.55) + 0.8)
    elif v["type"] == "slam":
        n = len(v.get("words", []))
        end = max(end, (max(v["at"]) if v.get("at") else n * v.get("stagger", 0.55)) + 0.9)
    elif v["type"] == "beats":
        end = max(end, (max(v["at"]) if v.get("at") else 0) + 1.0)
        if v.get("eind"):
            end = max(end, dur + 0.6)
    elif v["type"] == "bars" and not v.get("at"):
        end = max(end, 0.3 + len(v.get("bars", [])) * 0.3 + 1.0)
    return end


def apply_cues(scenes, sc_times, words):
    """`cue` in een regel/rij = woord waarop die regel verschijnt (synchroon met de stem)."""
    for sc, tm in zip(scenes, sc_times):
        v = sc["visual"]
        items = v.get("lines") or v.get("rows") or v.get("bars") or v.get("beats") or [{"cue": c} for c in v.get("cues", [])]
        if not items or not any("cue" in it for it in items):
            continue
        sw = [w for w in words if tm["start"] - 0.01 <= w["start"] <= tm["end"] + 0.01]
        at, last, pos = [], 0.3, 0
        for it in items:
            cue = it.get("cue", "").lower()
            hit = None
            for j in range(pos, len(sw)):
                if cue and cue in sw[j]["text"].lower():
                    hit, pos = sw[j]["start"] - tm["start"], j + 1
                    break
            last = hit if hit is not None else last + 0.5
            at.append(max(0.0, last - 0.1))
        v["at"] = at


def config_path(rel):
    return C.ROOT / rel
