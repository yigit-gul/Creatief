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

# --- Levendigheid (25/11) ---
SFX = True          # zelfgemaakte whoosh bij scènewissels + tik bij cijfers
SFX_VOLUME = 0.35   # ten opzichte van de stem (zacht houden)
PUNCH = 0.045       # korte zoom (4,5%) wanneer een cijfer/regel verschijnt
LANG_CHECK = True   # elke scène na het inspreken laten beluisteren door Whisper (moet Nederlands zijn)
LANG_MIN = 0.6      # minimale zekerheid dat het Nederlands is

# --- Minder 'AI-proper' klinken (27/11): stem alsof hij via een microfoon in een kamer is opgenomen ---
# warmte (150 Hz), iets meer aanwezigheid (3 kHz), lichte compressie, heel subtiele kamerklank,
# en een bijna onhoorbare ruisvloer zodat stiltes niet 'digitaal dood' klinken.
VOICE_FX = ("highpass=f=75,equalizer=f=150:t=q:w=1:g=2.5,equalizer=f=3200:t=q:w=1.2:g=1.5,"
            "equalizer=f=9000:t=q:w=1:g=-2,acompressor=threshold=-18dB:ratio=2.5:attack=8:release=120,"
            "aecho=0.85:0.6:23|37:0.10|0.06,"
            "aeval=val(0)+0.0012*(random(0)-0.5):c=same,")
