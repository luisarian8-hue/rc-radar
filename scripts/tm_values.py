"""Marktwerte aller Spieler über die Kaderseiten auf Transfermarkt (ein Apify-Ergebnis pro Verein).

1. Einmal pro Saison: Vereinsliste je Liga über die Wettbewerbsseite.
2. Alle 28 Tage: Kaderseite je Verein → Name, Geburtsdatum, Marktwert.
   Zuordnung zu API-Football über Verein + Geburtsdatum (eindeutig), sonst Name.
Ergebnis: data/tm/values.json  {api_player_id: {"mv": Euro, "club": ..., "fetched": ...}}
"""
import datetime as dt, json, os, re
from af import load, save
from tm import run, used_usd, tokens, norm, BUDGET

COMP = {"ENG2": "GB2", "ESP1": "ES1", "ESP2": "ES2", "ITA1": "IT1", "ITA2": "IT2", "GER1": "L1", "GER2": "L2", "GER3": "L3",
        "FRA1": "FR1", "FRA2": "FR2", "NED1": "NL1", "NED2": "NL2", "POR1": "PO1", "BEL1": "BE1", "BEL2": "BE2", "TUR1": "TR1",
        "CZE1": "TS1", "AUT1": "A1", "SUI1": "C1", "SCO1": "SC1", "DEN1": "DK1", "NOR1": "NO1", "SWE1": "SE1", "POL1": "PL1",
        "GRE1": "GR1", "CRO1": "KR1", "SRB1": "SER1", "UKR1": "UKR1", "HUN1": "UNG1", "ROU1": "RO1", "RUS1": "RU1"}
REFRESH_DAYS = int(os.environ.get("TM_VALUES_DAYS", "28"))


def money(s):
    m = re.search(r"€\s*([\d.,]+)\s*([mk]?)", str(s or "").lower().replace("bn", "000m"))
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return int(v * (1_000_000 if m.group(2) == "m" else 1_000 if m.group(2) == "k" else 1))


def birth(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(s or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def main():
    today = dt.date.today()
    if used_usd() > BUDGET:
        print("Apify-Budget erreicht, Marktwerte übersprungen.")
        return
    clubs = load("data/tm/clubs.json", {})
    missing = [k for k in COMP if k not in clubs]
    if missing:
        items = run([f"https://www.transfermarkt.com/liga/startseite/wettbewerb/{COMP[k]}" for k in missing])
        by_comp = {}
        for it in items:
            g = str(it.get("givenUrl") or "")
            u = str(it.get("url") or "")
            if "/verein/" in u:
                code = g.rstrip("/").split("/")[-1]
                base = re.sub(r"/saison_id/\d+.*$", "", u.replace("/kader/", "/startseite/"))
                by_comp.setdefault(code, {})[base] = it.get("name") if not str(it.get("name", "")).isdigit() else base.split("/")[3].replace("-", " ")
        for k in missing:
            clubs[k] = [{"url": u, "name": n} for u, n in by_comp.get(COMP[k], {}).items()]
        save("data/tm/clubs.json", clubs)

    vals = load("data/tm/values.json", {"fetched": "2000-01-01", "players": {}})
    if (today - dt.date.fromisoformat(vals["fetched"])).days < REFRESH_DAYS:
        print(f"Marktwerte aktuell ({vals['fetched']}), kein Abruf.")
        return
    urls = [c["url"] for k in clubs for c in clubs[k]]
    items = run(urls)
    av = load("data/availability.json", {"players": {}, "teams": {}})
    # API-Spieler je Verein (alle Alter, aus den Stammdaten)
    cfg = load("config/league_ids.json", None)
    meta = {}
    for key in cfg["leagues"]:
        for pid, m in load(f"data/af/{key}/players.json", {"players": {}})["players"].items():
            meta[pid] = dict(m, league=key)
    team_names = {tid: t["name"] for tid, t in av["teams"].items()}
    by_team = {}
    for pid, m in meta.items():
        if m.get("team"):
            by_team.setdefault(str(m["team"]), []).append(pid)
    url_league = {c["url"]: k for k in clubs for c in clubs[k]}
    hit = 0
    for it in items:
        rows = it.get("players") or []
        u = re.sub(r"/saison_id/\d+.*$", "", str(it.get("givenUrl") or it.get("url") or ""))
        lg = url_league.get(u)
        cname = u.split("/")[3].replace("-", " ") if u.count("/") > 3 else ""
        cands = [tid for tid, n in team_names.items() if av["teams"][tid]["league"] == lg and tokens(n) & tokens(cname)]
        pool = [pid for tid in cands for pid in by_team.get(tid, [])]
        for r in rows:
            nm = r.get("Player")
            nm = nm[0] if isinstance(nm, list) else nm
            b, mv = birth(r.get("Date of birth/Age")), money(r.get("Market value"))
            match = [p for p in pool if b and meta[p].get("birth") == b]
            if len(match) > 1:
                match = [p for p in match if tokens(nm) & tokens(meta[p].get("name", "") + " " + (meta[p].get("last") or ""))] or match[:1]
            if not match:
                match = [p for p in pool if tokens(nm) & tokens((meta[p].get("last") or meta[p].get("name", "")))
                         and (not b or not meta[p].get("birth") or meta[p]["birth"][:4] == b[:4])][:1]
            if match:
                vals["players"][match[0]] = {"mv": mv, "club": cname, "fetched": today.isoformat()}
                hit += 1
    vals["fetched"] = today.isoformat()
    save("data/tm/values.json", vals)
    print(f"Marktwerte: {len(items)} Kader · {hit} Spieler zugeordnet")


if __name__ == "__main__":
    main()
