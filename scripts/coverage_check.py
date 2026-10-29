"""Coverage-Check: Liefert API-Football für alle Radar-Ligen das, was der Radar braucht?

Prüft je Liga für die aktuelle Saison: Spiele, Aufstellungen, Spieler-Statistiken pro Spiel,
Spielerdaten (Minuten), Verletzungen. Schreibt reports/coverage.md und eine Zusammenfassung
in den GitHub-Job. Braucht nur die Standardbibliothek und den Secret API_FOOTBALL_KEY.
"""
import json, os, sys, time, urllib.parse, urllib.request
from collections import defaultdict

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEED = [("fixtures.lineups", "Aufstellungen"), ("fixtures.statistics_players", "Spielerwerte je Spiel"), ("players", "Spielerdaten"), ("injuries", "Verletzungen")]


def get(path, **params):
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        raise RuntimeError(f"{path} {params}: {data['errors']}")
    time.sleep(0.3)
    return data


def flag(cov, dotted):
    v = cov
    for part in dotted.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    return bool(v)


def norm(s):
    return s.lower().replace("ü", "u").replace("é", "e").replace("ó", "o").strip()


def main():
    if not KEY:
        sys.exit("Secret API_FOOTBALL_KEY fehlt (Repo → Settings → Secrets and variables → Actions).")
    cfg = json.load(open(os.path.join(ROOT, "config", "leagues.json"), encoding="utf-8"))
    season = cfg["season"]
    status = get("status")["response"]
    plan = (status.get("subscription") or {}).get("plan", "?")
    used = (status.get("requests") or {}).get("current", "?")
    limit = (status.get("requests") or {}).get("limit_day", "?")

    by_country = defaultdict(list)
    for lg in cfg["leagues"]:
        by_country[lg["country"]].append(lg)

    rows, resolved = [], {}
    for country, lgs in by_country.items():
        resp = get("leagues", country=country, season=season, type="league")["response"]
        for lg in lgs:
            wanted = [norm(n) for n in lg["names"]]
            hit = next((x for w in wanted for x in resp if norm(x["league"]["name"]) == w), None)
            if not hit:
                cands = ", ".join(sorted({x["league"]["name"] for x in resp})) or "keine Liga gefunden"
                rows.append([lg["key"], country, "NICHT GEFUNDEN", "", "", "", "", "", f"Kandidaten: {cands}"])
                continue
            seas = next((s for s in hit["seasons"] if s["year"] == season), None)
            cov = (seas or {}).get("coverage", {})
            marks = ["ja" if flag(cov, k) else "NEIN" for k, _ in NEED]
            ok = all(m == "ja" for m in marks)
            resolved[lg["key"]] = {"id": hit["league"]["id"], "name": hit["league"]["name"], "country": country}
            rows.append([lg["key"], country, hit["league"]["name"], str(hit["league"]["id"]), *marks, "OK" if ok else "Lücke"])

    ok_n = sum(1 for r in rows if r[-1] == "OK")
    head = ["Key", "Land", "Liga", "ID", *[n for _, n in NEED], "Status"]
    md = [f"# Coverage-Check API-Football, Saison {season}/{(season + 1) % 100:02d}", "",
          f"Plan: **{plan}** · Abfragen heute: {used}/{limit} · **{ok_n} von {len(rows)} Ligen vollständig**", "",
          "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    md += ["| " + " | ".join(r) + " |" for r in rows]
    text = "\n".join(md) + "\n"

    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    open(os.path.join(ROOT, "reports", "coverage.md"), "w", encoding="utf-8").write(text)
    json.dump({"season": season, "leagues": resolved}, open(os.path.join(ROOT, "config", "league_ids.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
