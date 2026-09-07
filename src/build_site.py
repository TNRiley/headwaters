#!/usr/bin/env python3
"""Splice the source records and the latest probe results into index.html.

Reads sources/*.json, health.json and leads.json; writes index.html from
src/template.html by replacing __PAYLOAD__. Then runs the two catalogue tools
that a Quick Project page needs, if they are reachable: wrap_for_pages.py (a
standalone document rather than an Artifact fragment) and add_catalog_link.py.

    python3 src/build_site.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import normalise                                  # noqa: E402

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


def link_datasets_to_sources(datasets, sources):
    """A dataset's publisher is sometimes an endpoint we already document.

    Derived at build time, not stored, so adding a source record retro-links every
    dataset that came from it without touching a single dataset file."""
    # Host normalisation lives in match.py, which is also what `hw add` and the lead
    # harvester ask. Three private copies of this rule is how they drift apart.
    norm = normalise

    host_to_source = {}
    for s in sources:
        urls = [s["homepage"]] + [p["url"] for p in s.get("probes", [])]
        for u in urls:
            host = norm(urlsplit(u).netloc)
            if host:
                host_to_source.setdefault(host, s["id"])
    back = {}
    for d in datasets:
        host = norm((d.get("provider") or {}).get("host") or "")
        if "." not in host:                            # a name key, not a host
            continue
        sid = host_to_source.get(host)
        if not sid:                                   # api.nhle.com -> nhle.com
            parts = host.split(".")
            for i in range(1, len(parts) - 1):
                sid = host_to_source.get(".".join(parts[i:]))
                if sid:
                    break
        if sid:
            d["source_id"] = sid
            back.setdefault(sid, []).append(d["id"])
    for s in sources:
        if s["id"] in back:
            s["datasets_from_here"] = sorted(back[s["id"]])[:40]
    return sum(1 for d in datasets if d.get("source_id"))


def main():
    sources = []
    for f in sorted((ROOT / "sources").glob("*.json")):
        sources.append(json.loads(f.read_text(encoding="utf-8")))
    datasets = []
    for f in sorted((ROOT / "datasets").glob("*.json")):
        datasets.append(json.loads(f.read_text(encoding="utf-8")))
    linked = link_datasets_to_sources(datasets, sources)

    health = {}
    hp = ROOT / "health.json"
    if hp.exists():
        health = json.loads(hp.read_text(encoding="utf-8"))

    leads_new = 0
    lp = ROOT / "leads.json"
    if lp.exists():
        leads = json.loads(lp.read_text(encoding="utf-8"))
        leads_new = sum(1 for x in leads.get("leads", {}).values() if x.get("state") == "new")

    # Only what the panel draws: the partner id, the key and how good the evidence is.
    # Titles are looked up client-side from the records already in the payload, which keeps
    # a 968-record graph to about a tenth of the space the full edge list would take.
    joins = {}
    jp = ROOT / "joins.json"
    if jp.exists():
        for rid, edges in json.loads(jp.read_text(encoding="utf-8")).get("joins", {}).items():
            joins[rid] = [{"other": e["other"], "key": e["key"], "basis": e["basis"]}
                          for e in edges[:4]]

    payload = {"sources": sources, "datasets": datasets, "health": health,
               "leads_new": leads_new, "joins": joins}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # The payload lives in a <script type="application/json">; the only sequence
    # that can end it early is a literal </script.
    blob = blob.replace("</", "<\\/")

    html = TEMPLATE.read_text(encoding="utf-8")
    if "__PAYLOAD__" not in html:
        sys.exit("template has no __PAYLOAD__ placeholder")
    html = html.replace("__PAYLOAD__", blob)

    # The template is an Artifact-shaped fragment: no doctype, no head. wrap_for_pages.py
    # turns it into a standalone document, and GitHub Pages needs that -- served raw, a
    # fragment lands in quirks mode with no charset and renders UTF-8 as Latin-1. So keep
    # the previous file until it is clear this run can produce an equivalent one.
    was_standalone = OUT.exists() and OUT.read_text(encoding="utf-8").lstrip()[:9].lower() == "<!doctype"
    previous = OUT.read_bytes() if OUT.exists() else None

    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print("index.html: %d datasets (%d linked to a source), %d sources, %d with join "
          "candidates, %d KB"
          % (len(datasets), linked, len(sources), len(joins), OUT.stat().st_size // 1024))

    ws = workspace_root(ROOT)
    tools = Path(os.environ["HEADWATERS_TOOLS"]) if os.environ.get("HEADWATERS_TOOLS") \
        else (ws / "catalog" / "tools" if ws else None)
    wrapped = False
    if tools and tools.is_dir():
        for script in ("wrap_for_pages.py", "add_catalog_link.py"):
            path = tools / script
            if path.exists():
                subprocess.run([sys.executable, str(path), str(OUT)], check=True)
                wrapped = wrapped or script == "wrap_for_pages.py"

    if not wrapped and was_standalone:
        # Publishing a fragment over a standalone document is a silent, ugly break that
        # nobody notices until the live page is mojibake. Refusing is the safe answer;
        # a caller that cannot wrap (CI, say) should skip the rebuild, not ship this.
        OUT.write_bytes(previous)
        sys.exit("refusing to replace a standalone index.html with an unwrapped fragment:\n"
                 "  wrap_for_pages.py was not found. Set HEADWATERS_TOOLS to the directory\n"
                 "  holding it, or run this from the Quick Projects workspace.\n"
                 "  index.html is unchanged.")
    if not wrapped:
        print("note: catalogue tools not found; index.html is an unwrapped fragment")


if __name__ == "__main__":
    main()
