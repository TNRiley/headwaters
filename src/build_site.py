#!/usr/bin/env python3
"""Splice the source records and the latest probe results into index.html.

Reads sources/*.json, health.json and leads.json; writes index.html from
src/template.html by replacing __PAYLOAD__. Then runs the two catalogue tools
that a Quick Project page needs, if they are reachable: wrap_for_pages.py (a
standalone document rather than an Artifact fragment) and add_catalog_link.py.

    python3 src/build_site.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "src" / "template.html"
OUT = ROOT / "index.html"


def workspace_root(start):
    """Walk up to the directory that holds projects/ - same idiom as the catalogue tools."""
    p = start
    while True:
        if (p / "projects").is_dir():
            return p
        parent = p.parent
        if parent == p:
            return None
        p = parent


def main():
    sources = []
    for f in sorted((ROOT / "sources").glob("*.json")):
        sources.append(json.loads(f.read_text(encoding="utf-8")))

    health = {}
    hp = ROOT / "health.json"
    if hp.exists():
        health = json.loads(hp.read_text(encoding="utf-8"))

    leads_new = 0
    lp = ROOT / "leads.json"
    if lp.exists():
        leads = json.loads(lp.read_text(encoding="utf-8"))
        leads_new = sum(1 for x in leads.get("leads", {}).values() if x.get("state") == "new")

    payload = {"sources": sources, "health": health, "leads_new": leads_new}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # The payload lives in a <script type="application/json">; the only sequence
    # that can end it early is a literal </script.
    blob = blob.replace("</", "<\\/")

    html = TEMPLATE.read_text(encoding="utf-8")
    if "__PAYLOAD__" not in html:
        sys.exit("template has no __PAYLOAD__ placeholder")
    html = html.replace("__PAYLOAD__", blob)
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print("index.html: %d sources, %d bytes" % (len(sources), OUT.stat().st_size))

    ws = workspace_root(ROOT)
    tools = ws / "catalog" / "tools" if ws else None
    if tools and tools.is_dir():
        for script in ("wrap_for_pages.py", "add_catalog_link.py"):
            path = tools / script
            if path.exists():
                subprocess.run([sys.executable, str(path), str(OUT)], check=True)
    else:
        print("note: catalogue tools not found; index.html is an unwrapped fragment")


if __name__ == "__main__":
    main()
