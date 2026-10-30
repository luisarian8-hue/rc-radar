"""R&C Radar · Kern v7 auf echten Daten.

Gleiche Logik wie im Artefakt (Kern v7), angepasst an die Felder von API-Football und Transfermarkt:
  A Leistung   Perzentil des ligabereinigten Positionsindex (letzte 16 Vereinsspiele), konservativ
  B Potenzial  Perzentil der 2-Jahres-Projektion aus Saison + Vorsaison + Alterskurve
  C Vertrag    Restlaufzeit bzw. Leihende (Transfermarkt), unbekannt = 0,10
  D Rolle      belegter Rollenverlust, zu wenig Spielzeit, Trainerwechsel, Liga zu klein
  E Berater    nur Signal, kein Scoreteil
  S = 0,65·max(A,B) + 0,35·min(A,B) · O = 1 − (1−C)(1−D), Synergien, Bremse · G = 0,15 + 0,85·O · P = 100·S·G

Ausgabe: data/scores.json (alle 18–26), data/candidates.json (für Transfermarkt), data/history.json, radar.json
"""
import bisect, datetime as dt, json, math, os
from collections import defaultdict
from af import load, save

WINDOW, K_SHRINK = 16, 3.0
# Ligastärke (0–1). Vorläufige Annahme, wird durch ClubElo ersetzt.
STRENGTH = {"ESP1": .95, "ITA1": .92, "GER1": .92, "FRA1": .88, "POR1": .74, "ENG2": .72, "NED1": .70, "BEL1": .68,
            "TUR1": .66, "ESP2": .64, "ITA2": .62, "GER2": .62, "RUS1": .62, "FRA2": .58, "CZE1": .56, "AUT1": .55,
            "SUI1": .55, "GRE1": .55, "DEN1": .54, "SCO1": .54, "UKR1": .52, "NOR1": .50, "POL1": .50, "CRO1": .50,
            "SWE1": .48, "SRB1": .48, "HUN1": .45, "ROU1": .45, "GER3": .42, "BEL2": .42, "NED2": .40}
LREF, LSPREAD = .6, 2.0
W = {  # Gewichte der Kernwerte je Position (API-Football-Felder)
    "IV": {"duw": .20, "duelPct": .20, "tklint": .25, "pa": .15, "passPct": .10, "rat": .10},
    "AV": {"tklint": .20, "kp": .20, "a": .15, "drs": .15, "duw": .10, "pa": .10, "rat": .10},
    "ZM": {"pa": .20, "passPct": .10, "kp": .20, "tklint": .20, "duw": .10, "rat": .20},
    "ZOM": {"kp": .25, "a": .15, "sh": .15, "g": .15, "drs": .15, "rat": .15},
    "FL": {"drs": .25, "kp": .20, "a": .15, "g": .15, "sh": .10, "rat": .15},
    "ST": {"g": .35, "sh": .20, "a": .10, "duw": .10, "kp": .10, "rat": .15},
}
LABEL = {"g": "Tore", "a": "Assists", "sh": "Schüsse", "kp": "Schlüsselpässe", "pa": "Pässe", "passPct": "Passquote",
         "tklint": "Tacklings + Abfangen", "duw": "Gewonnene Duelle", "duelPct": "Duellquote", "drs": "Dribblings", "rat": "Rating"}
POSN = {"IV": "Innenverteidiger", "AV": "Außenverteidiger", "ZM": "Zentrales Mittelfeld", "ZOM": "Offensives Mittelfeld", "FL": "Flügelspieler", "ST": "Stürmer"}
CURVE = [(0, .8), (6, .7), (12, .5), (18, .3), (24, .15), (36, .05), (60, .02)]


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def interp(m):
    for (x0, y0), (x1, y1) in zip(CURVE, CURVE[1:]):
        if m <= x1:
            return y0 + (y1 - y0) * (max(m, x0) - x0) / (x1 - x0)
    return CURVE[-1][1]


def pct(sorted_vals, v):
    if not sorted_vals:
        return 50
    return int(clamp(round(100 * bisect.bisect_right(sorted_vals, v) / len(sorted_vals)), 1, 99))


# ---------- Position aus der Aufstellung (Formation + Grid) ----------
def role_from_grid(form, grid):
    try:
        rows = [1] + [int(x) for x in form.split("-")]
        r, c = (int(x) for x in grid.split(":"))
    except Exception:
        return None
    if r == 1:
        return "GK"
    n, last = rows[r - 1], len(rows)
    if r == 2:
        return "AV" if n >= 4 and c in (1, n) else "IV"
    if r == last:
        return "FL" if n == 3 and c in (1, 3) else "ST"
    if r == last - 1 and rows[-1] <= 2:
        if n == 3:
            return "FL" if c in (1, 3) else "ZOM"
        if n == 1:
            return "ZOM"
        if n == 2 and rows[-1] == 1:
            return "FL"
    if n >= 4 and c in (1, n):
        return "FL" if r >= 3 else "AV"
    return "ZM"


# ---------- Werte je Spieler ----------
def add(acc, m):
    mins = m["min"] or 0
    acc["min"] += mins
    for k in ("g", "a", "sh", "kp", "pa", "tk", "int", "du", "duw", "dra", "drs"):
        acc[k] += m.get(k) or 0
    try:
        acc["pacc"] += int(m.get("pacc") or 0)
    except ValueError:
        pass
    if m.get("rat") and mins >= 20:
        acc["ratw"] += m["rat"] * mins
        acc["ratm"] += mins


def empty():
    return defaultdict(float)


def rates(acc, pacc_is_pct=False):
    n90 = acc["min"] / 90
    r = {k: acc[k] for k in ("g", "a", "sh", "kp", "pa", "duw", "drs")}
    r["tklint"] = acc["tk"] + acc["int"]
    r["n90"] = n90
    r["passPct"] = (acc["pacc"] if pacc_is_pct else (100 * acc["pacc"] / acc["pa"] if acc["pa"] else None))
    r["passN"] = acc["pa"]
    r["duelPct"] = 100 * acc["duw"] / acc["du"] if acc["du"] else None
    r["duelN"] = acc["du"]
    r["rat"] = acc["ratw"] / acc["ratm"] if acc["ratm"] else None
    r["ratN"] = acc["ratm"] / 90
    return r


COUNT = ("g", "a", "sh", "kp", "pa", "duw", "drs", "tklint")


def build_pop(rows):
    """Mittelwert/Streuung je Position und Wert (Spieler ab 5×90 Minuten)."""
    pop = {}
    for pos in W:
        rs = [r for r in rows if r["pos"] == pos and r["n90"] >= 5]
        st = {}
        for k in list(COUNT) + ["passPct", "duelPct", "rat"]:
            vals = [(r[k] / r["n90"] if k in COUNT else r[k]) for r in rs if (r[k] is not None)]
            if len(vals) < 5:
                st[k] = (0, 1)
                continue
            mu = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1
            st[k] = (mu, sd)
        pop[pos] = st
    return pop


def zvals(r, pos, pop):
    st, z = pop[pos], {}
    for k in W[pos]:
        mu, sd = st[k]
        if k in COUNT:
            v = (r[k] + K_SHRINK * mu) / (r["n90"] + K_SHRINK)
        elif k == "rat":
            v = r["rat"] if r["rat"] is not None else mu
            w = r["ratN"] / (r["ratN"] + K_SHRINK)
            v = w * v + (1 - w) * mu
        else:
            n = r["passN"] if k == "passPct" else r["duelN"]
            v = r[k] if r[k] is not None else mu
            w = n / (n + 40)
            v = w * v + (1 - w) * mu
        z[k] = (v - mu) / sd
    return z


def composite(z, pos):
    w = W[pos]
    return sum(w[k] * z[k] for k in w) / math.sqrt(sum(x * x for x in w.values()))


# ---------- Hauptlauf ----------
def main():
    cfg = load("config/league_ids.json", None)
    av = load("data/availability.json", {"players": {}, "teams": {}})
    tm = load("data/tm/profiles.json", {})
    snaps = load("data/tm/snapshots.json", {})
    clients = set(load("config/clients.json", []))
    MV_MAX = int(os.environ.get("MV_MAX", "2000000"))
    from tm_values import money
    vals = load("data/tm/values.json", {"players": {}})["players"]
    tmap = load("data/tm/map.json", {})
    def market_value(pid):
        v = (vals.get(pid) or {}).get("mv")
        if v is None and (tmap.get(pid) or {}).get("mv"):
            v = money(tmap[pid]["mv"])
        return v
    today = dt.date.today()
    week = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"

    # 1) Alle Spieler (jedes Alter) aus den Spielen der Saison: letzte 16 Vereinsspiele, Position aus Grid
    rows, by_pid, prev_all = [], {}, {}
    for key in cfg["leagues"]:
        st = load(f"data/af/{key}/matches.json", {"matches": {}})
        fs = sorted(st["matches"].values(), key=lambda f: f["date"])
        team_fs = defaultdict(list)
        for f in fs:
            for tid in f["teams"]:
                team_fs[tid].append(f)
        per = defaultdict(lambda: {"ms": [], "roles": defaultdict(int), "letters": defaultdict(int), "team": None})
        for f in fs:
            for m in f["players"]:
                if m.get("pos") == "G":
                    continue
                t = f["teams"].get(str(m["team"]), {})
                d = per[m["id"]]
                d["team"] = str(m["team"])
                if m["min"]:
                    d["ms"].append(m)
                    d["letters"][m.get("pos")] += 1
                g = (t.get("grid") or {}).get(str(m["id"]))
                ro = role_from_grid(t.get("form"), g) if g else None
                if ro and ro != "GK":
                    d["roles"][ro] += 1
                d.setdefault("names", m["name"])
        for pid, d in per.items():
            if not d["ms"]:
                continue
            pos = max(d["roles"], key=d["roles"].get) if d["roles"] else {"D": "IV", "M": "ZM", "F": "ST"}.get(max(d["letters"], key=d["letters"].get) if d["letters"] else "M", "ZM")
            last = d["ms"][-WINDOW:]
            acc, acc_wo = empty(), empty()
            for i, m in enumerate(last):
                add(acc, m)
                if i < len(last) - 1:
                    add(acc_wo, m)
            r = rates(acc)
            r.update({"pid": str(pid), "pos": pos, "posSrc": "grid" if d["roles"] else "letter", "league": key, "team": d["team"], "name": d["names"]})
            r["wo"] = rates(acc_wo)
            rows.append(r)
            by_pid[str(pid)] = r
        for pid, pv in (load(f"data/af/{key}/prev.json", {"players": {}})["players"]).items():
            if pid not in prev_all or pv["min"] > prev_all[pid][0]["min"]:
                prev_all[pid] = (pv, key)

    pop = build_pop(rows)
    for r in rows:
        z = zvals(r, r["pos"], pop)
        r["z"] = z
        r["comp"] = composite(z, r["pos"])
        r["comp_wo"] = composite(zvals(r["wo"], r["pos"], pop), r["pos"]) if r["wo"]["n90"] > 0 else r["comp"]
    # Komposit standardisieren je Position, dann Ligastärke
    for pos in W:
        cs = [r["comp"] for r in rows if r["pos"] == pos and r["n90"] >= 5]
        mu = sum(cs) / len(cs) if cs else 0
        sd = math.sqrt(sum((c - mu) ** 2 for c in cs) / len(cs)) if cs else 1
        for r in rows:
            if r["pos"] == pos:
                shift = LSPREAD * (STRENGTH.get(r["league"], .5) - LREF)
                r["idx"] = (r["comp"] - mu) / (sd or 1) + shift
                r["idx_wo"] = (r["comp_wo"] - mu) / (sd or 1) + shift
                r["se"] = 1.2 / math.sqrt(r["n90"] + 1)
    # Vorsaison im selben Maßstab
    prev_rows = []
    for pid, (pv, key) in prev_all.items():
        r0 = by_pid.get(pid)
        pos = r0["pos"] if r0 else {"Defender": "IV", "Midfielder": "ZM", "Attacker": "ST"}.get(pv.get("pos"), "ZM")
        acc = empty()
        for k in ("g", "a", "sh", "kp", "pa", "tk", "int", "du", "duw", "dra", "drs", "min"):
            acc[k] = pv.get(k) or 0
        acc["pacc"] = pv.get("pacc") or 0
        if pv.get("rat"):
            acc["ratw"], acc["ratm"] = pv["rat"] * pv["min"], pv["min"]
        pr = rates(acc, pacc_is_pct=True)
        pr.update({"pid": pid, "pos": pos, "league": key})
        prev_rows.append(pr)
    ppop = build_pop(prev_rows)
    prev_idx = {}
    for pos in W:
        sub = [pr for pr in prev_rows if pr["pos"] == pos]
        comps = [composite(zvals(pr, pos, ppop), pos) for pr in sub]
        ref = [c for c, pr in zip(comps, sub) if pr["n90"] >= 5]
        mu = sum(ref) / len(ref) if ref else 0
        sd = math.sqrt(sum((c - mu) ** 2 for c in ref) / len(ref)) if ref else 1
        for c, pr in zip(comps, sub):
            prev_idx[pr["pid"]] = ((c - mu) / (sd or 1) + LSPREAD * (STRENGTH.get(pr["league"], .5) - LREF), pr["n90"])

    # A und B als Perzentile je Position
    qpop, ppop_s, prevpop = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in rows:
        if r["n90"] >= 5:
            qpop[r["pos"]].append(r["idx"] - .5 * r["se"])
    for v in qpop.values():
        v.sort()
    players = av["players"]
    for r in rows:
        info = players.get(r["pid"])
        age = info["age"] if info else 27
        pv = prev_idx.get(r["pid"])
        cur_w = r["n90"]
        num, den = r["idx"] * cur_w, cur_w
        if pv and pv[1] >= 3:
            num += pv[0] * pv[1] * .7
            den += pv[1] * .7
        base = num / den if den else r["idx"]
        r["proj"] = base + .12 * max(0, 24.5 - age)
        r["prevIdx"] = pv[0] if pv else None
        if r["n90"] >= 5:
            ppop_s[r["pos"]].append(r["proj"])
        if pv and pv[1] >= 5:
            prevpop[r["pos"]].append(pv[0])
    for v in list(ppop_s.values()) + list(prevpop.values()):
        v.sort()

    # 2) Score je Spieler 18–26
    out, teams = {}, av.get("teams", {})
    for pid, info in players.items():
        r = by_pid.get(pid)
        if not r or info["age"] < 18 or info["age"] > 26 or pid in clients:
            continue
        mv = market_value(pid)
        if mv is not None and mv >= MV_MAX:  # Vorgabe Luis: nur Spieler unter 2 Mio. Marktwert
            continue
        A = pct(qpop[r["pos"]], r["idx"] - .5 * r["se"])
        A_wo = pct(qpop[r["pos"]], r["idx_wo"] - .5 * r["se"])
        spike = A - A_wo > 8
        if spike:
            A = A_wo + 8
        B = pct(ppop_s[r["pos"]], r["proj"])
        prevPct = pct(prevpop[r["pos"]], r["prevIdx"]) if r["prevIdx"] is not None and prevpop[r["pos"]] else None
        role = info["role"]
        # C · Vertrag / Leihe
        prof = dict(tm.get(pid) or {})
        if prof.get("loanFrom") and not prof.get("v2"):  # alte Profile: Felder waren vertauscht
            prof["contractEnd"], prof["loanUntil"] = prof.get("loanUntil") or prof.get("contractEnd"), prof.get("contractEnd")
        months, cend, loan_left = None, prof.get("contractEnd"), None
        if cend:
            ce = dt.date.fromisoformat(cend)
            months = max(0, (ce.year - today.year) * 12 + ce.month - today.month)
        C = interp(months) if months is not None else .10
        if prof.get("loanUntil"):
            lu = dt.date.fromisoformat(prof["loanUntil"])
            loan_left = max(0, (lu.year - today.year) * 12 + lu.month - today.month)
            # Vorgabe Luis: bei Leihen zählt nur der Vertrag beim Heimatverein
        ext_recent = False
        if prof.get("lastExtension"):
            ext_recent = (today - dt.date.fromisoformat(prof["lastExtension"])).days <= 182
        # D · Rolle & Umfeld
        b, rc = role["before"], role["recent"]
        loss_s = clamp((b["share"] - rc["share"]) / b["share"], 0, 1) if role["loss"] and b["share"] else 0
        d_loss = .7 * min(1, loss_s / .6) if role["loss"] else 0
        all_avail = b["avail"] + rc["avail"]
        share_all = ((b["share"] or 0) * b["avail"] + (rc["share"] or 0) * rc["avail"]) / all_avail if all_avail else None
        unter = share_all is not None and share_all < .45 and A >= 60 and not role["loss"] and all_avail >= 5
        d_under = .55 * clamp((.45 - share_all) / .3) if unter else 0
        tinfo = teams.get(info["team"], {})
        cc = (tinfo.get("coachChanges") or [])
        coach_weeks, coach_date = None, None
        if cc:
            coach_date = cc[-1]["date"]
            coach_weeks = (today - dt.date.fromisoformat(coach_date)).days / 7
        d_coach = .2 * 0.5 ** (coach_weeks / 8) if coach_weeks is not None and coach_weeks <= 12 else 0
        strength = STRENGTH.get(r["league"], .5)
        liga = .35 * clamp((A - 85) / 10) if A >= 85 and strength < .55 and (rc["share"] or 0) >= .7 else 0
        D = 1 - (1 - max(d_loss, d_under, d_coach)) * (1 - liga)
        # E · Berater (nur Signal)
        ag = agent_state(snaps.get(pid, []))
        # Synergien und Bremse
        syn = []
        if role["loss"] and loss_s >= .45 and C >= .45 and A >= 60 and months is not None:
            syn.append(("rolle_vertrag", "Rollenverlust + kurzer Vertrag", .4 * min(loss_s, C / .7, 1)))
        if prevPct is not None and prevPct >= 75 and (role["loss"] or unter) and coach_weeks is not None and coach_weeks <= 12:
            syn.append(("historie_trainer", "Starke Vorsaison + Rollenverlust nach Trainerwechsel", .35 * clamp((prevPct - 60) / 30) * clamp(D / .5)))
        if loan_left is not None and loan_left <= 9 and A >= 65:
            syn.append(("leihe_perspektive", "Leihende + Qualität", .15))
        damp = [("verlaengert_rolle", "Verlängert trotz Rollenverlust", .8)] if ext_recent and D >= .3 else []
        S = (.65 * max(A, B) + .35 * min(A, B)) / 100
        O0 = 1 - (1 - C) * (1 - D)
        syn_sum = min(.6, sum(x[2] for x in syn))
        O1 = O0 + (1 - O0) * syn_sum
        O = O1 * math.prod(x[2] for x in damp) if damp else O1
        G = .15 + .85 * O
        P = round(100 * S * G)
        sample = clamp((r["n90"] * 90 + .5 * ((prev_all.get(pid) or ({"min": 0},))[0]["min"])) / 1500)
        rest = (1 if months is not None else .7) * (1 if info["injuryData"] else .85) * (1 if r["posSrc"] == "grid" else .85)
        conf = round(100 * math.sqrt(sample * rest))
        out[pid] = {
            "id": pid, "name": info["name"], "age": info["age"], "birth": info["birth"], "pos": r["pos"], "posName": POSN[r["pos"]],
            "league": r["league"], "leagueName": cfg["leagues"][r["league"]]["name"], "team": info["team"], "teamName": tinfo.get("name"),
            "P": P, "S": round(S, 4), "O0": round(O0, 4), "O1": round(O1, 4), "O": round(O, 4), "G": round(G, 4),
            "crit": {"A": A, "B": B, "C": round(C, 3), "D": round(D, 3), "E": ag["v"]}, "spike": spike, "prevPct": prevPct,
            "syn": [{"k": k, "l": l, "v": round(v, 3)} for k, l, v in syn], "damp": [{"k": k, "l": l, "f": f} for k, l, f in damp],
            "conf": conf, "mins": round(r["n90"] * 90), "posSrc": r["posSrc"],
            "role": {"statusLine": role["statusLine"], "before": b["share"], "recent": rc["share"], "loss": role["loss"], "under": unter,
                     "trailingUnknown": role["trailingUnknown"], "injuredNow": role["injuredNow"], "starts": b["starts"] + rc["starts"]},
            "contract": {"end": cend, "months": months, "lastExtension": prof.get("lastExtension"), "loanFrom": prof.get("loanFrom"), "loanUntil": prof.get("loanUntil"), "loanLeft": loan_left},
            "agent": ag, "coach": {"date": coach_date, "name": cc[-1]["coach"] if cc else None, "weeks": round(coach_weeks, 1) if coach_weeks is not None else None},
            "ligaSmall": liga > 0, "tm": prof.get("url"), "mv": mv,
            "metrics": {k: {"l": LABEL[k], "v": round(r[k] / r["n90"], 2) if k in COUNT and r["n90"] else (round(r[k], 1) if r[k] is not None else None)} for k in W[r["pos"]]},
        }

    # Ligavergleich: Rang je Kernwert unter Spielern derselben Position in derselben Liga (ab 450 Min.)
    peers = defaultdict(list)
    for r in rows:
        if r["n90"] >= 5:
            peers[(r["league"], r["pos"])].append(r)
    for pid, o in out.items():
        grp = peers.get((o["league"], o["pos"]), [])
        for k, m in o["metrics"].items():
            vals = sorted(((x[k] / x["n90"] if k in COUNT else x[k]) for x in grp if x[k] is not None), reverse=True)
            if m["v"] is None or not vals or o["mins"] < 450:
                continue
            rank = next((i + 1 for i, v in enumerate(vals) if v <= m["v"] + 1e-9), len(vals))
            m["rank"], m["n"] = rank, len(vals)
            m["pct"] = round(100 * (len(vals) - rank) / (len(vals) - 1)) if len(vals) > 1 else 50

    # Historie und Kategorien
    hist = load("data/history.json", {})
    hist[week] = {pid: o["P"] for pid, o in out.items() if o["P"] >= 40}
    weeks = sorted(hist)[-104:]
    hist = {w: hist[w] for w in weeks}
    prev_week = weeks[-2] if len(weeks) > 1 else None
    for pid, o in out.items():
        o["hist"] = [hist[w].get(pid) for w in weeks]
        o["inRadar"] = o["P"] >= 70
        was = prev_week and hist[prev_week].get(pid, 0) >= 70
        o["status"] = "neu" if o["inRadar"] and prev_week and not was else None
    save("data/history.json", hist)
    save("data/scores.json", {"updated": today.isoformat(), "week": week, "players": out})

    # Kandidaten für Transfermarkt: sportlich relevant oder belegter Rollenverlust
    cand = sorted((o for o in out.values() if o["mins"] >= 450 and (o["S"] >= .75 or (o["role"]["loss"] and o["S"] >= .6))), key=lambda o: -o["S"])[:300]
    save("data/candidates.json", [{"id": o["id"], "name": o["name"], "age": o["age"], "team": o["teamName"], "league": o["league"]} for o in cand])

    # Rang diese Woche und Vorwoche (für ▲/▼ in der Top-Liste)
    for i, o in enumerate(sorted(out.values(), key=lambda o: -o["P"])):
        o["rank"] = i + 1
    if prev_week:
        for i, pid in enumerate(sorted(hist[prev_week], key=lambda k: -hist[prev_week][k])):
            if pid in out:
                out[pid]["prevRank"] = i + 1
    at = all_time(hist, out, weeks)
    # Im Radar nur Spieler mit bestätigtem Marktwert unter der Grenze (unbekannt = noch nicht anzeigen)
    shown = {pid for pid, o in out.items() if o["mv"] is not None}
    at = [x for x in at if x["id"] in shown]
    keep = {o["id"] for o in out.values() if o["P"] >= 50 and o["id"] in shown} | {x["id"] for x in at[:60]}
    radar = sorted((out[k] for k in keep if k in out), key=lambda o: -o["P"])
    save("radar.json", {"updated": today.isoformat(), "week": week, "weeks": weeks, "players": radar, "allTime": at[:60],
                        "stats": {"rated": len(out), "inRadar": sum(1 for o in out.values() if o["P"] >= 70 and o["mv"] is not None), "leagues": len(cfg["leagues"]),
                                  "withContract": sum(1 for o in out.values() if o["contract"]["end"])}})
    n70 = sum(1 for o in out.values() if o["P"] >= 70)
    print(f"{len(out)} Spieler bewertet · {n70} im Radar (ab 70) · {len(cand)} Kandidaten für Transfermarkt · max {max((o['P'] for o in out.values()), default=0)}")


def all_time(hist, out, weeks):
    tot = defaultdict(list)
    for w in weeks:
        for pid, p in hist[w].items():
            tot[pid].append(p)
    rows = []
    for pid, ps in tot.items():
        full = ps + [40] * (len(weeks) - len(ps))  # Wochen unter 40 zählen als 40
        rows.append({"id": pid, "avg": round(sum(full) / len(full), 1), "weeksIn": sum(1 for p in ps if p >= 70), "n": len(weeks),
                     "name": (out.get(pid) or {}).get("name"), "P": (out.get(pid) or {}).get("P")})
    return sorted(rows, key=lambda x: -x["avg"])[:100]


def agent_state(sn):
    """Berater-Signal aus den wöchentlichen Transfermarkt-Snapshots."""
    if not sn:
        return {"state": "unbekannt", "v": 0, "name": None, "since": None}
    cur = sn[-1].get("agent")
    if cur and "relative" in cur.lower():
        return {"state": "familie", "v": .2, "name": "Familie", "since": None}
    if not cur:
        prev = [s for s in sn[:-1] if s.get("agent")]
        if prev:
            gone = 0
            for s in reversed(sn):
                if s.get("agent"):
                    break
                gone += 1
            since = sn[-gone]["week"]
            return {"state": "trennung" if gone >= 2 else "trennung_hint", "v": .5 if gone >= 2 else .15, "name": prev[-1]["agent"], "since": since}
        return {"state": "nie", "v": .1, "name": None, "since": None}
    older = [s.get("agent") for s in sn[:-1] if s.get("agent")]
    if older and older[-1] != cur:
        return {"state": "neu", "v": 0, "name": cur, "since": sn[-1]["week"]}
    return {"state": "ruhig", "v": .05, "name": cur, "since": None}


if __name__ == "__main__":
    main()
