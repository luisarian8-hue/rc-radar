"""Kleiner API-Football-Client: Key aus der Umgebung, Pausen gegen das Minutenlimit, Zähler für Abfragen."""
import json, os, sys, time, urllib.parse, urllib.request

BASE = "https://v3.football.api-sports.io"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALLS = {"n": 0}


def key():
    k = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not k:
        sys.exit("Secret API_FOOTBALL_KEY fehlt.")
    return k


def get(path, **params):
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        req = urllib.request.Request(url, headers={"x-apisports-key": key()})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.load(r)
        except Exception as e:  # Netzfehler: kurz warten, neu versuchen
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
            continue
        CALLS["n"] += 1
        err = data.get("errors")
        if err and "rateLimit" in str(err):
            time.sleep(8)
            continue
        if err:
            raise RuntimeError(f"{path} {params}: {err}")
        time.sleep(0.25)  # Pro-Plan: 300 Abfragen pro Minute
        return data
    raise RuntimeError(f"{path} {params}: zu viele Fehlversuche")


def pages(path, **params):
    """Alle Seiten einer paginierten Abfrage."""
    out, page = [], 1
    while True:
        d = get(path, page=page, **params)
        out += d["response"]
        tot = (d.get("paging") or {}).get("total", 1)
        if page >= tot:
            return out
        page += 1


def load(rel, default):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(rel, obj):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
