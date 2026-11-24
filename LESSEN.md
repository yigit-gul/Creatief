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
