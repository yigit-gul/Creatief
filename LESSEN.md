# Lessen uit de views

Wordt elke zaterdag bijgewerkt op basis van de cijfers die je in de Studio invult (views, likes, gedeeld, bewaard,
% volledig bekeken). Elke dagelijkse run leest dit bestand vóór het schrijven.

## Stand op 2026-11-23
Nog geen cijfers. Tot dan gelden de regels uit de feedback:
- Korte, eenvoudige zinnen (max. ~10 woorden): anders klinkt de stem AI.
- Geen "hè". Spreektaal, maar geen voorleesstijl.
- Hook met een herkenbare tegenstrijdigheid of een groot cijfer.
- Net boven 1 minuut, langer alleen als de inhoud het draagt.
- Humor moet de uitleg dienen.
- Nooit twee keer tekst tegelijk in beeld (reuzenwoorden + ondertitel) en niets dat overlapt.
- Het belangrijkste cijfer meteen in de eerste seconde in beeld (bv. reuzengroot '+35%').

## Stem: alleen Nederlands (belangrijkste les, 23/11)
- De meertalige stem kiest de taal PER ZIN. Korte losse zinnen ("Plus 35%.", "En waarom?") werden Frans of Engels.
- Daarom: elke scène gaat als ÉÉN doorlopende zin naar de stem (punten/vraagtekens -> komma's), en de pipeline
  voegt daarna zelf korte stiltes (~0,3 s) in op de zinsgrenzen. Zo blijft het Nederlands én hoor je elke zin apart.
- Cijfers altijd uitgeschreven in het Nederlands naar de stem ("vijfendertig procent"); ondertitels tonen cijfers.
- Nooit de taal-instructie van de spraakdienst aanpassen (maakte het erger).
- De zelfreview bewaakt dit automatisch (TAAL-controle op de gesproken tekst).

## Referentievideo (goedgekeurd door de gebruiker, 24/11)
`scripts/2026-W48/05-nasdaq-dotcom-crash.json` = de stijl die werkt. Gebruik hem als voorbeeld:
- spreektaal als uitleg ("Kijk", "Stel je voor"), korte zinnen, humor die de uitleg dient ("langer dan TikTok bestaat")
- sneller tempo (+22%), korte pauzes, alleen Nederlands
- echte foto's achter hook/uitlegscènes, niet achter grafieken of rekenvoorbeelden
- een concreet voorbeeld als eigen scène (Pets.com), net boven 1 minuut

## Bereik blijft hangen rond 300 views (24/11)
- Eerste 3 video's (marktnieuws, Nvidia) bleven rond ~300 views steken: de testgroep van TikTok, niet doorgeschoven.
- Gevonden fout: het EERSTE BEELD was leeg (hook fadete pas na 0,3-0,5 s binnen). Nu staat de hook op frame 0;
  de zelfreview controleert dit automatisch.
- Volgende lessen pas trekken als er kijktijd-cijfers zijn (% volledig bekeken, waar haken mensen af).

## 'Te duidelijk AI' (27/11)
- De gebruiker vermoedt dat de video's te duidelijk AI zijn. Geen eigen stem en geen betaalde stem gewenst.
- Daarom: stem met microfoon- en kamerklank (config VOICE_FX), scripts met eigen reacties/meningen en vragen
  aan de kijker, meer echte foto's. Volgende weken meten of de kijktijd stijgt.

## Voorbeeldvideo met veel views (27/11): stijl 'uitleg'
De gebruiker stuurde een video ("Instagram is gratis, maar Meta verdient €50 per jaar aan jou") die veel views haalt.
Gemeten tegenover onze loonbriefvideo:
- **Pauzes:** 11 per minuut (voorbeeld) tegenover 38 (wij). Wij hakten alles in korte zinnetjes met telkens een
  pauze: dat klinkt als voorlezen = AI. Het voorbeeld vertelt in doorlopende zinnen met en/maar/want/dan.
- Tempo 3,2 tegenover 3,0 woorden/s; in de eerste 3 s 9 woorden tegenover 6.
- Volume gelijkmatiger (2,3 dB spreiding tegenover 4,5): sterkere compressie (`VOICE_FX_UITLEG`).
- Toonhoogte/melodie ongeveer gelijk: de stem zelf was niet het grootste verschil, de zinsbouw wel.
- Beeld: zwarte achtergrond, één groot 3D-icoon of getal in het midden dat elke 1-2 s wisselt, getallen die optellen,
  ondertitels van 1-2 woorden met het belangrijke woord in kleur, geen outro maar een twist op het einde.
Meten op een nieuwe video: `python -m pipeline.stemanalyse review/<map>/<id>.mp4`.

## Gratis stem (Chatterbox, variant C) – tempo (27/11)
Eerst versneld (atempo 1.12) + alle pauzes tot 0,18 s + 0,08 s tussen scènes = 3,8 woorden/s: de gebruiker vond
het "gehaast, alsof hij aan het lopen is". Nu: niet versnellen (CB_TEMPO 1.0), alleen pauzes > 0,45 s inkorten tot
0,3 s, 0,2 s tussen scènes = 3,4 woorden/s. Richtwaarde: 3,2-3,5 woorden/s. Sneller gaan = meestal niet beter.
