"""Holt die Wochendaten von API-Football für alle Radar-Ligen.

Pro Liga:
  1. Alle beendeten Spiele der Saison (1 Abfrage), neue Spiele in 20er-Paketen mit Aufstellung,
     Bank, Trainer und Spielerwerten (1 Abfrage pro 20 Spiele).
  2. Verletzungen/Sperren, wo die Liga sie liefert (1 Abfrage).
  3. Spielerstammdaten (Alter, Geburtsdatum) einmal pro Monat.
Bereits geholte Spiele werden nicht neu abgefragt. Erster Lauf holt die ganze bisherige Saison
(ca. 200 Abfragen), danach ca. 60 pro Woche.
"""
import datetime as dt
from af import get, pages, load, save, CALLS

STAT = lambda s, a, b: ((s.get(a) or {}).get(b))


def compact_player(p, team_id):
    st = (p.get("statistics") or [{}])[0]
    g = st.get("games") or {}
    return {
        "id": p["player"]["id"], "name": p["player"]["name"], "team": team_id,
        "min": g.get("minutes") or 0, "pos": g.get("position"), "sub": bool(g.get("substitute")),
        "rat": float(g["rating"]) if g.get("rating") else None,
        "g": STAT(st, "goals", "total") or 0, "a": STAT(st, "goals", "assists") or 0,
        "sh": STAT(st, "shots", "total") or 0, "kp": STAT(st, "passes", "key") or 0,
        "pa": STAT(st, "passes", "total") or 0, "pacc": STAT(st, "passes", "accuracy"),
        "tk": STAT(st, "tackles", "total") or 0, "int": STAT(st, "tackles", "interceptions") or 0,
        "du": STAT(st, "duels", "total") or 0, "duw": STAT(st, "duels", "won") or 0,
        "dra": STAT(st, "dribbles", "attempts") or 0, "drs": STAT(st, "dribbles", "success") or 0,
        "yc": STAT(st, "cards", "yellow") or 0, "rc": STAT(st, "cards", "red") or 0,
    }


def compact_fixture(f):
    lu = {x["team"]["id"]: x for x in (f.get("lineups") or [])}
    teams = {}
    for side in ("home", "away"):
        t = f["teams"][side]
        l = lu.get(t["id"], {})
        teams[str(t["id"])] = {
            "name": t["name"], "side": side,
            "coach": (l.get("coach") or {}).get("id"), "coachName": (l.get("coach") or {}).get("name"),
            "xi": [x["player"]["id"] for x in l.get("startXI") or [] if x.get("player")],
            "bench": [x["player"]["id"] for x in l.get("substitutes") or [] if x.get("player")],
            "form": l.get("formation"),
            "grid": {str(x["player"]["id"]): x["player"].get("grid") for x in l.get("startXI") or [] if x.get("player")},
        }
    players = [compact_player(p, blk["team"]["id"]) for blk in (f.get("players") or []) for p in blk.get("players") or []]
    return {"id": f["fixture"]["id"], "date": f["fixture"]["date"][:10], "round": f["league"].get("round"),
            "teams": teams, "players": players, "hasLineup": bool(lu), "hasPlayers": bool(players)}


def main():
    cfg = load("config/league_ids.json", None)
    season = cfg["season"]
    today = dt.date.today().isoformat()
    log = []
    for key, lg in cfg["leagues"].items():
        store = load(f"data/af/{key}/matches.json", {"league": lg, "season": season, "matches": {}})
        fx = get("fixtures", league=lg["id"], season=season, status="FT-AET-PEN")["response"]
        def stale(fid):
            m = store["matches"].get(str(fid))
            return m is None or any("form" not in t for t in m["teams"].values())
        new = [f["fixture"]["id"] for f in fx if stale(f["fixture"]["id"])]
        for i in range(0, len(new), 20):
            for f in get("fixtures", ids="-".join(map(str, new[i:i + 20])))["response"]:
                store["matches"][str(f["fixture"]["id"])] = compact_fixture(f)
        store["updated"] = today
        save(f"data/af/{key}/matches.json", store)

        inj = []
        try:
            for r in get("injuries", league=lg["id"], season=season)["response"]:
                inj.append({"player": r["player"]["id"], "team": r["team"]["id"], "fixture": (r.get("fixture") or {}).get("id"),
                            "date": ((r.get("fixture") or {}).get("date") or "")[:10], "type": r["player"].get("type"), "reason": r["player"].get("reason")})
        except RuntimeError:
            pass
        save(f"data/af/{key}/injuries.json", inj)

        meta = load(f"data/af/{key}/players.json", {"updated": "2000-01-01", "players": {}})
        if (dt.date.fromisoformat(today) - dt.date.fromisoformat(meta["updated"])).days >= 28:
            for r in pages("players", league=lg["id"], season=season):
                pl = r["player"]
                meta["players"][str(pl["id"])] = {"name": pl["name"], "first": pl.get("firstname"), "last": pl.get("lastname"),
                                                  "birth": (pl.get("birth") or {}).get("date"), "nat": pl.get("nationality"),
                                                  "team": ((r.get("statistics") or [{}])[0].get("team") or {}).get("id")}
            meta["updated"] = today
            save(f"data/af/{key}/players.json", meta)
        if load(f"data/af/{key}/prev.json", None) is None:
            prev = {}
            for r in pages("players", league=lg["id"], season=season - 1):
                st = (r.get("statistics") or [{}])[0]
                g = st.get("games") or {}
                if not g.get("minutes"):
                    continue
                prev[str(r["player"]["id"])] = {
                    "min": g.get("minutes") or 0, "apps": g.get("appearences") or 0, "pos": g.get("position"),
                    "rat": float(g["rating"]) if g.get("rating") else None, "team": (st.get("team") or {}).get("name"),
                    "g": STAT(st, "goals", "total") or 0, "a": STAT(st, "goals", "assists") or 0, "sh": STAT(st, "shots", "total") or 0,
                    "kp": STAT(st, "passes", "key") or 0, "pa": STAT(st, "passes", "total") or 0, "pacc": STAT(st, "passes", "accuracy"),
                    "tk": STAT(st, "tackles", "total") or 0, "int": STAT(st, "tackles", "interceptions") or 0,
                    "du": STAT(st, "duels", "total") or 0, "duw": STAT(st, "duels", "won") or 0,
                    "dra": STAT(st, "dribbles", "attempts") or 0, "drs": STAT(st, "dribbles", "success") or 0}
            save(f"data/af/{key}/prev.json", {"season": season - 1, "players": prev})
        log.append(f"{key}: {len(store['matches'])} Spiele ({len(new)} neu), {len(inj)} Ausfälle, {len(meta['players'])} Spieler")
    print("\n".join(log))
    print(f"Abfragen in diesem Lauf: {CALLS['n']}")


if __name__ == "__main__":
    main()
