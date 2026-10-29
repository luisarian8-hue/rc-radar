"""Apify-Test: Transfermarkt-Daten für einen Kader (Fortuna Düsseldorf, 2. Bundesliga).

Prüft, ob Vertrag, Berater, Leihe und Verletzung pro Spieler ankommen und was es kostet.
Ein Kader = ca. 30 Spieler, kostet im Free-Plan nur Cent-Beträge.
"""
import json, os, sys, urllib.request

TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
ACTOR = os.environ.get("APIFY_ACTOR", "curious_coder~transfermarkt")
START = os.environ.get("TM_URL", "https://www.transfermarkt.com/fortuna-dusseldorf/kader/verein/38")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if not TOKEN:
        sys.exit("Secret APIFY_TOKEN fehlt.")
    body = {"startUrl": START, "startUrls": [{"url": START}], "crawlDepth": 1, "pageDepth": 1, "parallels": 2,
            "proxyConfig": {"useApifyProxy": True}}
    req = urllib.request.Request(f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?timeout=280",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        items = json.load(r)
    players = [x for x in items if "spieler" in str(x.get("url", "")) or str(x.get("type", "")).lower() == "player"]
    keys = sorted({k for x in players for k in x.keys()})
    def has(pat):
        return sum(1 for x in players if any(pat in k.lower() and x.get(k) for k in x))
    rows = [("Spieler-Datensätze", len(players)), ("mit Vertragsende", has("contract")), ("mit Berater", has("agent")),
            ("mit Leihe-Feld", has("loan")), ("mit Verletzung", has("injur"))]
    md = [f"# Apify-Test Transfermarkt", "", f"Actor `{ACTOR}` · Start `{START}` · {len(items)} Datensätze gesamt", "",
          "| Prüfung | Anzahl |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows] + ["", "Felder: " + ", ".join(f"`{k}`" for k in keys)]
    text = "\n".join(md) + "\n"
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    open(os.path.join(ROOT, "reports", "apify_test.md"), "w", encoding="utf-8").write(text)
    json.dump(items[:5], open(os.path.join(ROOT, "reports", "apify_sample.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
