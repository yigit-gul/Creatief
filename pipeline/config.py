"""Vaste instellingen voor het kanaal: merk, kleuren, stem en videoformaat."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"

# --- Merk -------------------------------------------------------------------
CHANNEL_NAME = "Fiscaal Fluitje"
CHANNEL_HANDLE = "@fiscaalfluitje"
TAGLINE = "Belastingen, een fluitje van een cent"
DISCLAIMER = "Algemene info, geen persoonlijk advies."

# Kleurenpalet (hex)
COLORS = {
    "bg_top": "#0E1A2B",     # nachtblauw
    "bg_bottom": "#132E3F",  # diep petrol
    "card": "#1B2C44",       # kaartjes
    "card_line": "#2A3F5E",
    "text": "#F4F6FA",       # gebroken wit
    "muted": "#93A3B8",      # grijsblauw
    "mint": "#2EE6A6",       # hoofdaccent
    "yellow": "#FFD23F",     # cijfers / highlight
    "coral": "#FF6B6B",      # kosten / waarschuwing
}

# --- Stem -------------------------------------------------------------------
VOICE = "en-US-AndrewMultilingualNeural"   # gekozen in de Studio (stem E); spreekt Nederlands
VOICE_RATE = "+22%"   # TikTok-tempo (sneller op vraag, 24/11)
VOICE_PITCH = "+0Hz"
VOICE_LANG = None  # NIET aanpassen: een eigen taal-instructie maakte de taalwissels erger. Standaard laten.
SCENE_GAP = 0.16  # korte adempauze tussen scènes
FLOW_SENTENCES = True  # elke scène = één doorlopende zin -> de meertalige stem blijft Nederlands (zoals de oude video's)
# De zinsgrenzen worden daarna hoorbaar gemaakt door zelf een korte stilte in te voegen.
SENTENCE_GAP = 0.22   # totale stilte op een zinsgrens (wordt ingevoegd)
QUESTION_GAP = 0.28   # na een vraag iets langer
SHORT_GAP = 0.18      # na een korte uitroep korter

# --- Video ------------------------------------------------------------------
W, H = 1080, 1920
FPS = 30
# Veilige zone voor TikTok-UI (knoppen rechts, caption onderaan)
SAFE_LEFT, SAFE_RIGHT, SAFE_TOP, SAFE_BOTTOM = 80, 150, 210, 480
SUB_Y = 1440  # verticale positie (midden) van de ondertitels
OUTRO_HOLD = 2.5  # seconden dat de eindkaart (disclaimer) blijft staan na de stem
