"""Spielzeit und Verfügbarkeit je Spieler (18–26) aus den API-Football-Daten.

Status pro Vereinsspiel, ab dem ersten Spiel im Kader dieses Vereins:
  S Startelf · E eingewechselt · B auf der Bank, nicht eingesetzt
  V verletzt/krank (Verletzungsliste der Liga oder Ausfallhistorie des Spielers)
  G gesperrt (Sperre in der Ausfallliste oder Rot im Spiel davor)
  U nicht im Kader, Grund unbekannt

Regel gegen Fehlalarme: Rollenverlust zählt nur, was belegt ist. „Nicht im Kader“ zählt nur dann als
„nicht berücksichtigt“, wenn für den Spieler Ausfalldaten vorliegen (Liga mit Verletzungsliste oder
Ausfallhistorie abgefragt) und dort für das Datum nichts steht. Sonst bleibt U unbekannt und fällt
aus dem Nenner der Spielzeitquote heraus. Bank (B) und kurze Einwechslungen sind immer belastbar.
"""
import datetime as dt
from collections import defaultdict
from af import get, load, save, CALLS

AGE_MIN, AGE_MAX = 18, 26
RECENT = 6


def age_at(birth, day):
    if not birth:
        return None
    b = dt.date.fromisoformat(birth)
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))


def main():
    cfg = load("config/league_ids.json", None)
    covered = set(load("config/injury_coverage.json", []))
    today = dt.date.today()
    out, teams_out = {}, {}
    need_sidelined = []

    for key in cfg["leagues"]:
        m = load(f"data/af/{key}/matches.json", {"matches": {}})["matches"]
        meta = load(f"data/af/{key}/players.json", {"players": {}})["players"]
        inj = load(f"data/af/{key}/injuries.json", [])
        injury_by = defaultdict(dict)
        for r in inj:
            if r.get("fixture"):
                injury_by[r["player"]][r["fixture"]] = r
        has_inj = key in covered or len(inj) > 0

        by_team = defaultdict(list)
        for f in sorted(m.values(), key=lambda x: x["date"]):
            for tid in f["teams"]:
                by_team[tid].append(f)

        # Trainerwechsel je Verein
        for tid, fs in by_team.items():
            ch, last = [], None
            for f in fs:
                c = f["teams"][tid].get("coach")
                if c and last and c != last:
                    ch.append({"date": f["date"], "coach": f["teams"][tid].get("coachName")})
                last = c or last
            teams_out[tid] = {"league": key, "name": fs[-1]["teams"][tid]["name"], "coachChanges": ch, "matches": len(fs)}

        # Letzter Verein je Spieler = Verein seines letzten Kaderplatzes
        last_team = {}
        for tid, fs in by_team.items():
            for f in fs:
                t = f["teams"][tid]
                for pid in t["xi"] + t["bench"]:
                    last_team[pid] = (f["date"], tid) if pid not in last_team or f["date"] >= last_team[pid][0] else last_team[pid]

        for pid, (_, tid) in last_team.items():
            info = meta.get(str(pid), {})
            age = age_at(info.get("birth"), today)
            if age is None or not (AGE_MIN <= age <= AGE_MAX):
                continue
            fs = by_team[tid]
            first = next(i for i, f in enumerate(fs) if pid in f["teams"][tid]["xi"] + f["teams"][tid]["bench"])
            seq, prev_red = [], False
            for f in fs[first:]:
                t = f["teams"][tid]
                stat = next((p for p in f["players"] if p["id"] == pid), None)
                mins = (stat or {}).get("min", 0)
                ir = injury_by.get(pid, {}).get(f["id"])
                if pid in t["xi"]:
                    s = "S"
                elif pid in t["bench"]:
                    s = "E" if mins > 0 else "B"
                elif ir and "suspen" in (ir.get("reason") or "").lower():
                    s = "G"
                elif ir:
                    s = "V"
                elif prev_red:
                    s = "G"
                else:
                    s = "U"
                seq.append({"f": f["id"], "d": f["date"], "s": s, "min": mins, "rat": (stat or {}).get("rat")})
                prev_red = bool(stat and stat.get("rc"))
            out[str(pid)] = {"name": info.get("name") or str(pid), "birth": info.get("birth"), "age": age, "league": key, "team": tid,
                             "injuryData": has_inj, "seq": seq}
            if not has_inj and any(x["s"] == "U" for x in seq[-10:]):
                need_sidelined.append(pid)

    # Ausfallhistorie für Spieler mit unklaren Abwesenheiten in Ligen ohne Verletzungsliste
    sid = load("data/af/sidelined.json", {})
    todo = [p for p in need_sidelined if str(p) not in sid or sid[str(p)].get("checked") != today.isoformat()]
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        try:
            resp = get("sidelined", players="-".join(map(str, chunk)))["response"]
        except RuntimeError:
            break
        got = defaultdict(list)
        for r in resp:
            pid = (r.get("player") or {}).get("id") or r.get("id")
            for s in r.get("sidelined") or ([r] if r.get("start") else []):
                got[pid].append({"type": s.get("type"), "start": s.get("start"), "end": s.get("end")})
        for p in chunk:
            sid[str(p)] = {"checked": today.isoformat(), "spells": got.get(p, [])}
    save("data/af/sidelined.json", sid)

    for pid, o in out.items():
        spells = (sid.get(pid) or {}).get("spells", [])
        if pid in sid:
            o["injuryData"] = True
        for x in o["seq"]:
            if x["s"] == "U":
                for sp in spells:
                    end = sp.get("end") or "2100-01-01"
                    if sp.get("start") and sp["start"] <= x["d"] <= end:
                        x["s"] = "G" if "suspen" in (sp.get("type") or "").lower() else "V"
        summarize(o)

    save("data/availability.json", {"updated": today.isoformat(), "players": out, "teams": teams_out})
    n_unk = sum(1 for o in out.values() if o["role"]["trailingUnknown"] >= 2)
    print(f"{len(out)} Spieler 18–26 · {sum(1 for o in out.values() if o['injuryData'])} mit Ausfalldaten · {n_unk} aktuell ≥2 Spiele unklar abwesend · Abfragen: {CALLS['n']}")


def summarize(o):
    """Spielzeitquote vorher gegen letzte 6 Spiele, nur über belastbare Spiele."""
    seq, known = o["seq"], o["injuryData"]
    # Lange Abwesenheiten (ab 4 Spielen am Stück ohne Eintrag) sind eher Verletzung, Wechsel oder
    # Sonderfall als eine Trainerentscheidung: nicht als „nicht berücksichtigt“ werten.
    i = 0
    while i < len(seq):
        if seq[i]["s"] == "U":
            j = i
            while j < len(seq) and seq[j]["s"] == "U":
                j += 1
            # Wer nach der Abwesenheit sofort wieder in der Startelf steht, war ausgefallen, nicht aussortiert.
            # Gleiches gilt, wenn er davor Stammspieler war (letzte 3 Spiele vor der Lücke in der Startelf)
            # und die Lücke noch andauert: Grund unklar, kein Rollenverlust.
            back_start = any(x["s"] == "S" for x in seq[j:j + 2])  # spätestens im zweiten Spiel danach wieder Startelf
            prev = [x["s"] for x in seq[max(0, i - 3):i]]
            was_regular = len(prev) >= 2 and all(c == "S" for c in prev)
            for x in seq[i:j]:
                x["long"] = j - i >= 4 or back_start or (j == len(seq) and was_regular)
            i = j
        else:
            i += 1
    def counts(xs):
        avail = [x for x in xs if x["s"] in "SEB" or (x["s"] == "U" and known and not x.get("long"))]
        mins = sum(x["min"] for x in avail)
        return {"n": len(xs), "avail": len(avail), "share": round(mins / (90 * len(avail)), 3) if avail else None,
                "starts": sum(1 for x in xs if x["s"] == "S"), "bench": sum(1 for x in xs if x["s"] == "B"),
                "out": sum(1 for x in xs if x["s"] in "VG"), "unknown": sum(1 for x in xs if x["s"] == "U" and (not known or x.get("long")))}
    recent, before = seq[-RECENT:], seq[:-RECENT]
    trail = 0
    for x in reversed(seq):
        if x["s"] == "U":
            trail += 1
        else:
            break
    injured_now = bool(seq) and seq[-1]["s"] == "V"
    # Comeback: Nach einem Ausfall (ab 2 Spielen verletzt/gesperrt) in den letzten 9 Spielen ist wenig Spielzeit normal
    tail9 = "".join(x["s"] for x in seq[-9:])
    comeback = "VV" in tail9 or "GG" in tail9
    o["role"] = {"before": counts(before), "recent": counts(recent), "trailingUnknown": trail, "injuredNow": injured_now,
                 "statusLine": "".join(x["s"] for x in seq[-16:]), "comeback": comeback}
    # Rollenverlust nur bei Belegen: genug belastbare Spiele in beiden Fenstern
    b, r = o["role"]["before"], o["role"]["recent"]
    o["role"]["loss"] = bool(b["share"] is not None and r["share"] is not None and b["avail"] >= 4 and r["avail"] >= 3
                             and b["share"] >= .45 and r["share"] <= .5 and r["share"] <= b["share"] - .3 and not injured_now and not comeback)


if __name__ == "__main__":
    main()
