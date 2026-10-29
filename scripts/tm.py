"""Transfermarkt über Apify, im Rahmen des Gratisguthabens.

1. Zuordnung: Kandidaten ohne Transfermarkt-Profil per Schnellsuche (Name) suchen,
   Treffer über Alter und Verein bestätigen. Höchstens TM_NEW neue Suchen pro Lauf.
2. Profile: alle zugeordneten Kandidaten plus TM_ROTATE weitere zugeordnete Spieler im Wechsel.
   Liefert Vertragsende, letzte Verlängerung, Leihe, Berater. Jede Woche ein Snapshot (Berater-Historie).
Bremse: Liegt der Apify-Verbrauch im Monat über TM_BUDGET_USD, wird nichts abgerufen.
"""
import datetime as dt, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from af import load, save

TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
ACTOR = os.environ.get("APIFY_ACTOR", "curious_coder~transfermarkt")
NEW_MAX = int(os.environ.get("TM_NEW", "120"))
ROTATE = int(os.environ.get("TM_ROTATE", "150"))
BUDGET = float(os.environ.get("TM_BUDGET_USD", "4.5"))
API = "https://api.apify.com/v2"


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def used_usd():
    try:
        d = call("GET", "/users/me/limits")["data"]
        print("Apify-Limits:", json.dumps({"current": d.get("current"), "limits": d.get("limits")})[:600])
        return float((d.get("current") or {}).get("monthlyUsageUsd") or 0)
    except Exception as e:
        print("Apify-Limits nicht lesbar:", e)
        return 0.0


def run(urls):
    """Actor-Lauf über eine URL-Liste, wartet bis fertig, gibt die Datensätze zurück."""
    if not urls:
        return []
    body = {"startUrl": urls[0], "startUrls": [{"url": u} for u in urls], "crawlDepth": 1, "pageDepth": 1, "parallels": 3,
            "proxyConfig": {"useApifyProxy": True}}
    r = call("POST", f"/acts/{ACTOR}/runs", body)["data"]
    rid, ds = r["id"], r["defaultDatasetId"]
    for _ in range(240):
        st = call("GET", f"/actor-runs/{rid}")["data"]["status"]
        if st in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(10)
    with urllib.request.urlopen(urllib.request.Request(f"{API}/datasets/{ds}/items?clean=1&format=json", headers={"Authorization": f"Bearer {TOKEN}"}), timeout=120) as f:
        return json.load(f)


def norm(s):
    if isinstance(s, (list, tuple)):
        s = " ".join(str(x) for x in s)
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)


def tokens(s):
    return {t for t in norm(s).split() if len(t) > 2 and t not in {"fc", "sc", "sv", "fk", "club", "cf", "ac", "if", "afc", "united", "city"}}


def date_iso(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", s or "")
    if m:
        mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(m.group(1)) + 1
        return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    return None


def main():
    if not TOKEN:
        sys.exit("Secret APIFY_TOKEN fehlt.")
    used = used_usd()
    if used > BUDGET:
        print(f"Apify-Verbrauch diesen Monat {used:.2f} $ > {BUDGET} $: Transfermarkt diese Woche ausgelassen.")
        return
    today = dt.date.today()
    week = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"
    cand = load("data/candidates.json", [])
    cfg = load("config/league_ids.json", None)
    metas = {}
    for key in cfg["leagues"]:
        metas.update(load(f"data/af/{key}/players.json", {"players": {}})["players"])
    tmap = load("data/tm/map.json", {})
    profiles = load("data/tm/profiles.json", {})
    snaps = load("data/tm/snapshots.json", {})

    # 1) Zuordnung
    todo = [c for c in cand if c["id"] not in tmap][:NEW_MAX]
    queries = {}
    for c in todo:
        m = metas.get(c["id"], {})
        first = (m.get("first") or "").split(" ")[0]
        q = f"{first} {m.get('last') or c['name']}".strip()
        queries[c["id"]] = q
    url_of = lambda q: "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query=" + urllib.parse.quote(q)
    cache = load("data/tm/search_cache.json", {})
    fresh = [q for q in queries.values() if url_of(q) not in cache]
    if fresh:
        got_items = run([url_of(q) for q in fresh])
        for it in got_items:
            cache.setdefault(it.get("givenUrl"), []).append(it)
        for q in fresh:
            cache.setdefault(url_of(q), [])
        save("data/tm/search_cache.json", cache)  # sofort sichern, damit bezahlte Suchen nie verloren gehen
    items = [it for q in queries.values() for it in cache.get(url_of(q), [])]
    by_given = {}
    for it in items:
        by_given.setdefault(it.get("givenUrl"), []).append(it)
    mapped = 0
    for c in todo:
        hits = [h for h in by_given.get(url_of(queries[c["id"]]), []) if "/profil/spieler/" in str(h.get("url", ""))]
        best, best_s = None, 0
        for h in hits:
            s = 0
            try:
                if abs(int(str(h.get("Age", "")).strip()) - c["age"]) <= 1:
                    s += 2
            except ValueError:
                pass
            if tokens(h.get("Club")) & tokens(c["team"]):
                s += 2
            if tokens(queries[c["id"]]) & tokens(h.get("Name/Position") or str(h.get("url", "")).split("/")[3].replace("-", " ")):
                s += 1
            if s > best_s:
                best, best_s = h, s
        if best and best_s >= 3:
            tmap[c["id"]] = {"url": best["url"], "score": best_s, "mapped": today.isoformat()}
            mapped += 1
        else:
            tmap[c["id"]] = {"url": None, "tried": today.isoformat()}
    save("data/tm/map.json", tmap)

    # 2) Profile: Kandidaten + Wechsel
    cand_ids = [c["id"] for c in cand if (tmap.get(c["id"]) or {}).get("url")]
    others = sorted((pid for pid, v in tmap.items() if v.get("url") and pid not in cand_ids), key=lambda p: (profiles.get(p) or {}).get("fetched", ""))[:ROTATE]
    ids = cand_ids + others
    items = run([tmap[p]["url"] for p in ids])
    by_url = {it.get("givenUrl") or it.get("url"): it for it in items}
    got = 0
    for pid in ids:
        it = by_url.get(tmap[pid]["url"])
        if not it:
            continue
        got += 1
        loan_from = next((it[k] for k in it if "loan from" in k.lower()), None)
        loan_until = next((date_iso(it[k]) for k in it if "contract there" in k.lower()), None)
        prof = {"url": tmap[pid]["url"], "fetched": today.isoformat(), "contractEnd": date_iso(it.get("Contract expires")),
                "lastExtension": date_iso(it.get("Last contract extension")), "agent": it.get("Player agent"),
                "club": it.get("Current club"), "position": it.get("Position"), "loanFrom": loan_from, "loanUntil": loan_until}
        if loan_from and not loan_until:
            prof["loanUntil"] = prof["contractEnd"]
        profiles[pid] = prof
        sn = snaps.setdefault(pid, [])
        rec = {"week": week, "agent": prof["agent"], "contractEnd": prof["contractEnd"]}
        if sn and sn[-1]["week"] == week:
            sn[-1] = rec
        else:
            sn.append(rec)
        snaps[pid] = sn[-30:]
    save("data/tm/profiles.json", profiles)
    save("data/tm/snapshots.json", snaps)
    print(f"Transfermarkt: {mapped}/{len(todo)} neu zugeordnet · {got}/{len(ids)} Profile · Apify diesen Monat vorher {used:.2f} $")


if __name__ == "__main__":
    main()
