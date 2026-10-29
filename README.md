# R&C Radar · Datenpipeline

Wöchentliche Daten für den R&C Akquise-Radar (Top-30-Ligen Europas plus Russland, Spieler 18–26).

## Ablauf (Ziel)
1. Wyscout-Export (Spielerwerte, Vorsaison) landet in `data/wyscout/KWxx/`.
2. GitHub Action holt API-Football (Einsätze, Minuten, Trainer), Transfermarkt über Apify (Vertrag, Leihe, Berater) und ClubElo (Ligastärke).
3. Kern v7 rechnet die Scores und schreibt `radar.json` inklusive Wochen-Historie.
4. Eine geplante Claude-Aufgabe spielt `radar.json` ins R&C-Artefakt.

## Secrets (Settings → Secrets and variables → Actions)
- `API_FOOTBALL_KEY`
- `APIFY_TOKEN`

## Jetzt
- `Actions → Coverage-Check → Run workflow`: prüft, ob API-Football alle 31 Ligen abdeckt. Ergebnis in `reports/coverage.md`.
