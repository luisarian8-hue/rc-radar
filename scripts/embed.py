"""Ersetzt die Radar-Daten im R&C-Artefakt durch die aktuelle radar.json.

Aufruf: python scripts/embed.py <artefakt.html> [radar.json]
Sucht <script type="application/json" id="rcRadarData">…</script> und tauscht den Inhalt aus.
"""
import re, sys

html_path = sys.argv[1]
data_path = sys.argv[2] if len(sys.argv) > 2 else "radar.json"
html = open(html_path, encoding="utf-8").read()
data = open(data_path, encoding="utf-8").read().replace("</", "<\\/")
pat = re.compile(r'(<script type="application/json" id="rcRadarData">)(.*?)(</script>)', re.S)
if not pat.search(html):
    sys.exit("Datenblock rcRadarData nicht gefunden.")
html = pat.sub(lambda m: m.group(1) + data + m.group(3), html, count=1)
open(html_path, "w", encoding="utf-8").write(html)
print("Radar-Daten eingesetzt:", len(data), "Zeichen")
