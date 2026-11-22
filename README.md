# Fiscaal Fluitje · TikTok-pipeline

Korte educatieve video's over Belgische fiscaliteit en persoonlijke financiën voor 18-30-jarigen.
De pipeline maakt de video's. **Posten gebeurt nooit automatisch**: alles komt in `/review` terecht om na te kijken.

## Mappen
| Map | Inhoud |
|---|---|
| `onderwerpen/` | per week de gekozen onderwerpen + waarom (`2026-W48.md`) |
| `scripts/<week>/` | één JSON per video: voice-over per scène, beeld, caption, hashtags, claims + bronnen |
| `audio/<week>/` | voice-over (mp3), woordtimings, ondertitelbestand (.ass) |
| `video/<week>/` | eindvideo's 1080x1920 |
| `review/<week>/` | `review.md` (overzicht + checklist), video's, captions, bronnen per video |
| `pipeline/` | code: `config.py` (merk/stem), `tts.py`, `render.py`, `build.py` |
| `assets/fonts/` | Inter (SIL Open Font License) |

## Gebruik
```bash
pip install -r requirements.txt          # ffmpeg moet geïnstalleerd zijn
python -m pipeline.build scripts/2026-W48            # hele week
python -m pipeline.build scripts/2026-W48/01-tob.json  # één video
```
Achter een proxy pikt `tts.py` automatisch `HTTPS_PROXY` op.

## Scriptformaat (kort)
- `scenes[].say`: tekst voor de voice-over. `[TOB|T.O.B.]` = toon "TOB", spreek "T.O.B." uit.
- `scenes[].visual.type`: `hook`, `point`, `table`, `calc`, `bars`, `outro`. `*woord*` = geel accent.
  `cue` in tabelrijen/rekenregels = het woord waarop die regel verschijnt (synchroon met de stem).
- De laatste scène is altijd `outro`. De disclaimer "Algemene info, geen persoonlijk advies." wordt daar
  **altijd** door de renderer getoond.
- `claims[]`: elke bewering met bronnen (url + datum) en `status`: `ok` of `check` (= ⚠️ in review.md).

## Merk
- Naam: **Fiscaal Fluitje** (@fiscaalfluitje), "belastingen, een fluitje van een cent"
- Kleuren: nachtblauw `#0E1A2B` · petrol `#132E3F` · mint `#2EE6A6` (accent) · geel `#FFD23F` (cijfers) ·
  koraal `#FF6B6B` (kosten) · gebroken wit `#F4F6FA`
- Stem: `nl-BE-ArnaudNeural` (+10%). Alternatief `nl-BE-DenaNeural`: zie `review/stemproef/`.

## Spelregels voor de inhoud
Alleen algemene educatieve info, nooit beleggingsadvies (geen producten aanraden, geen koersvoorspellingen),
elk bedrag met een officiële bron + aanslagjaar of geldigheid, ⚠️ bij twijfel, AI-vermelding in elke caption.
