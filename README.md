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

## Stand (29.10.2026)
- Coverage-Check: API-Football Pro deckt alle 31 Ligen ab (Aufstellungen, Spielerwerte, Minuten). Verletzungen nur in 11 Ligen.
- Apify-Test: Transfermarkt-Profile liefern Vertragsende, letzte Verlängerung, Berater (Familie = „Relatives“), Verein, Position. Keine Verletzungen. Vereinsseiten liefern keine Profil-Links, deshalb einmalige Zuordnung API-Football → Transfermarkt nötig.

## Budget Apify (Free-Plan, 5 $ / Monat)
- Wöchentlich nur ~300 Kandidaten (sportlich relevant laut API-Football) → ca. 1.300 Profile / Monat.
- Zusätzlich ~150 übrige Spieler pro Woche im Wechsel → ca. 650 Profile / Monat, jeder Spieler etwa alle 4 Monate frisch.
- Zuordnung zu Transfermarkt anfangs nur für Kandidaten, Rest verteilt über 1–2 Monate.
- Falls es knapp wird: Wechsel-Auslesung auf ~80 pro Woche senken.

## Nächste Schritte
1. Spieler-Zuordnung API-Football → Transfermarkt.
2. Wochenlauf: API-Football alle 31 Ligen, Transfermarkt für Kandidaten plus Wechsel.
3. Kern v7 auf echte Daten, `radar.json` mit Wochen-Historie, Übergabe ins Artefakt.
