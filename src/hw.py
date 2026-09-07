#!/usr/bin/env python3
"""hw -- ask the catalogue things, from any directory, in one line.

Headwaters only helps when someone remembers it exists. Reading a JSON record needs
a path, a glob and a json.load; that is enough friction that a session researches a
source from scratch instead. This collapses all of it to `hw find tide`.

    hw find tide                 both layers, ranked
    hw show noaa-coops           the whole record, readably
    hw gotchas census            the traps -- read these before writing the loop
    hw recipe openalex           copy-paste starting points
    hw add https://x.org/api     do we know this already? if not, scaffold a record
    hw probe noaa-coops          does it still answer, right now?
    hw joins tt-2024-01-09       what could this be joined with, and on what key
    hw health                    what broke since the last run
    hw used-by openalex still-cited   record that a project consumed a source
    hw stats

Every command takes --json for a machine reader. Stdlib only.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import Index, normalise, registrable, host_of   # noqa: E402
from probe import state_of                                 # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HEALTH = ROOT / "health.json"
JOINS = ROOT / "joins.json"

BOLD, DIM, OFF = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"


def plain():
    return not sys.stdout.isatty()


def c(text, code):
    return text if plain() else code + text + OFF


def wrap(text, width=96, indent="  "):
    words, lines, line = (text or "").split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    return "\n".join(indent + l for l in lines)


# ---------------------------------------------------------------- searching

def haystack_source(s):
    """Every string in a source record worth matching, weighted by where it appeared."""
    return [
        (s.get("name", ""), 6), (s.get("id", ""), 6),
        (s.get("description", ""), 3),
        (" ".join(s.get("topics", [])), 4),
        (" ".join(s.get("fields", [])), 3),
        (s.get("publisher", ""), 2), (s.get("geography", ""), 1),
        (" ".join(g.get("trap", "") for g in s.get("gotchas", [])), 1),
    ]


def haystack_dataset(d):
    cols = " ".join(col for t in d.get("tables", []) for col in t.get("columns", []))
    return [
        (d.get("title", ""), 6), (d.get("id", ""), 5),
        (" ".join(d.get("subjects", [])), 4),
        (cols, 3),                                   # the best search key in the catalogue
        (d.get("hook", ""), 2),
        ((d.get("provider") or {}).get("name", ""), 2),
        (d.get("geography", ""), 1),
    ]


def score(terms, fields):
    """Sum of weights for fields matching each term; zero unless every term hits.

    All terms must appear somewhere -- "tide station" should not return everything
    about tides -- but they may appear in different fields.

    A term matches at the start of a word, not anywhere in it, so "tide" finds
    tide/tides/tidegauge and not lipoglycopep*tide*s. Free substring matching looks
    generous and is mostly noise: column names are long compound words and almost any
    short query lands inside one. A whole-word hit then outranks a prefix hit, so
    "water" ranks a `water` column above `water_temperature_daily_mean`.
    """
    total = 0
    for term in terms:
        prefix = re.compile(r"\b%s" % re.escape(term))
        whole = re.compile(r"\b%s\b" % re.escape(term))
        best = 0
        for text, weight in fields:
            low = (text or "").lower()
            if prefix.search(low):
                best = max(best, weight * (2 if whole.search(low) else 1))
        if not best:
            return 0
        total += best
    return total


def search(idx, query, kinds, limit):
    terms = [t for t in query.lower().split() if t]
    out = []
    if "sources" in kinds:
        for s in idx.sources:
            n = score(terms, haystack_source(s))
            if n:
                out.append((n, "source", s))
    if "datasets" in kinds:
        for d in idx.datasets:
            n = score(terms, haystack_dataset(d))
            if n:
                out.append((n, "dataset", d))
    out.sort(key=lambda r: (-r[0], r[2].get("id", "")))
    return out[:limit], len(out)


def matched_columns(d, terms):
    return [col for t in d.get("tables", []) for col in t.get("columns", [])
            if any(term in col.lower() for term in terms)]


def cmd_find(args, idx):
    kinds = {"both": ("sources", "datasets"), "sources": ("sources",),
             "datasets": ("datasets",)}[args.layer]
    hits, total = search(idx, args.query, kinds, args.limit)
    terms = [t for t in args.query.lower().split() if t]
    if args.json:
        print(json.dumps([{"kind": k, "id": r["id"], "score": n,
                           "title": r.get("name") or r.get("title")} for n, k, r in hits], indent=2))
        return 0
    if not hits:
        print("nothing for %r. `hw stats` shows what is in here; leads.json has %d unpromoted."
              % (args.query, idx.counts()["leads_new"]))
        return 1
    for n, kind, r in hits:
        if kind == "source":
            status = r.get("status", "live")
            tag = c("source", GREEN if status == "live" else YELLOW)
            print("%s  %s  %s" % (tag, c(r["id"], BOLD), r.get("name", "")))
            print(wrap(r.get("description", ""), indent="        ")[:400])
            bits = ["auth: %s" % r.get("access", {}).get("auth", "?")]
            if r.get("gotchas"):
                bits.append("%d gotchas" % len(r["gotchas"]))
            if r.get("recipes"):
                bits.append("%d recipes" % len(r["recipes"]))
            if status != "live":
                bits.append(c("STATUS: %s" % status, YELLOW))
            print(c("        " + "  ·  ".join(bits), DIM))
        else:
            print("%s %s  %s" % (c("dataset", DIM), c(r["id"], BOLD), r.get("title", "")))
            cols = matched_columns(r, terms)
            line = "; ".join(r.get("subjects", []))
            if cols:
                line += "  ·  columns: " + ", ".join(cols[:6])
            print(c("        " + line, DIM))
    if total > len(hits):
        print(c("\n%d more; --limit to see them" % (total - len(hits)), DIM))
    return 0


# ---------------------------------------------------------------- showing

def load_record(idx, rid):
    for rec in idx.sources:
        if rec["id"] == rid:
            return "source", rec
    for rec in idx.datasets:
        if rec["id"] == rid:
            return "dataset", rec
    if rid in idx.leads:
        return "lead", idx.leads[rid]
    return None, None


def health_for(sid):
    if not HEALTH.exists():
        return {}
    return json.loads(HEALTH.read_text(encoding="utf-8")).get("results", {}).get(sid, {})


def show_source(s):
    print(c(s.get("name", ""), BOLD) + c("   (%s)" % s["id"], DIM))
    print(wrap(s.get("description", "")))
    print()
    lic = s.get("license", {})
    acc = s.get("access", {})
    rows = [
        ("publisher", s.get("publisher", "")),
        ("homepage", s.get("homepage", "")),
        ("status", s.get("status", "live")),
        ("licence", lic.get("name", "") + (" -- %s" % lic["redistribution"]
                                           if lic.get("redistribution") else "")),
        ("auth", acc.get("auth", "") + (" (%s)" % acc["auth_note"] if acc.get("auth_note") else "")),
        ("formats", ", ".join(acc.get("formats", []))),
        ("rate limit", acc.get("rate_limit", "")),
        ("etiquette", acc.get("etiquette", "")),
        ("pagination", acc.get("pagination", "")),
        ("bulk", "yes" if acc.get("bulk") else ("no" if "bulk" in acc else "")),
        ("size", acc.get("size_hint", "")),
        ("geography", s.get("geography", "")),
        ("topics", ", ".join(s.get("topics", []))),
        ("fields", ", ".join(s.get("fields", []))),
        ("verified", s.get("verified", "")),
        ("used by", ", ".join(s.get("used_by", []))),
    ]
    for label, value in rows:
        if value:
            print("  %-11s %s" % (c(label, DIM), value))
    if s.get("gotchas"):
        print("\n" + c("gotchas", BOLD) + c("  -- the reason this record exists", DIM))
        for g in s["gotchas"]:
            print("  " + c("!", YELLOW) + " " + g["trap"])
            if g.get("fix"):
                print(wrap("-> " + g["fix"], indent="      "))
    if s.get("recipes"):
        print("\n" + c("recipes", BOLD))
        for r in s["recipes"]:
            print("  " + c(r.get("title", r["lang"]), DIM) + "  [%s]" % r["lang"])
            for line in r["code"].splitlines():
                print("    " + line)
    results = health_for(s["id"])
    if results:
        print("\n" + c("probes", BOLD))
        for pid, r in results.items():
            if r.get("ok"):
                mark = c("ok  ", GREEN)
            elif r.get("known_broken"):
                mark = c("dead", DIM)
            else:
                mark = c("FAIL", RED)
            print("  %s %-22s %s %s" % (mark, pid, str(r.get("status") or "---"),
                                        c("; ".join(r.get("why", []))[:70], DIM)))
        print(c("  checked %s -- `hw probe %s` to re-run now"
                % (list(results.values())[0].get("checked", "?")[:16], s["id"]), DIM))
    if s.get("related"):
        print("\n  " + c("related", DIM) + " " + ", ".join(s["related"]))


def show_dataset(d):
    print(c(d.get("title", ""), BOLD) + c("   (%s)" % d["id"], DIM))
    if d.get("hook"):
        print(wrap(d["hook"][:600]))
    print()
    prov = d.get("provider") or {}
    for label, value in [("subjects", "; ".join(d.get("subjects", []))),
                         ("publisher", "%s  (%s)" % (prov.get("name", "?"), d.get("provider_type", "")))
                         if prov else ("publisher", ""),
                         ("geography", d.get("geography", "")),
                         ("added", d.get("added", ""))]:
        if value:
            print("  %-11s %s" % (c(label, DIM), value))
    for f in d.get("found_in", []):
        print("  %-11s %s %s  %s" % (c("surfaced", DIM), f.get("aggregation", ""),
                                     f.get("date", ""), c(f.get("url", ""), DIM)))
    for s in d.get("sources", []):
        print("  %-11s %s  %s" % (c("upstream", DIM), s.get("name", ""), c(s.get("url", ""), DIM)))
    if d.get("questions"):
        print("\n" + c("questions", BOLD))
        for q in d["questions"]:
            print("  - " + q)
    print("\n" + c("tables", BOLD))
    for t in d.get("tables", []):
        size = "  %s KB" % (t["bytes"] // 1024) if t.get("bytes") else ""
        print("  " + c(t.get("file", ""), BOLD) + c(size, DIM))
        print(wrap(", ".join(t.get("columns", [])), indent="      "))
        if t.get("url"):
            print(c("      " + t["url"], DIM))


def cmd_show(args, idx):
    kind, rec = load_record(idx, args.id)
    if not rec:
        hit = idx.lookup(args.id)
        print("no record %r." % args.id + (" Did you mean %s %s?" % (hit.kind, hit.id) if hit else
                                           " `hw find %s` to search." % args.id), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    if kind == "source":
        show_source(rec)
    elif kind == "dataset":
        show_dataset(rec)
    else:
        print(c("lead", DIM) + " " + args.id)
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        print(c("\nA lead is not a source. Promoting one means researching it and writing a "
                "record with working probes.", DIM))
    return 0


# ---------------------------------------------------------------- gotchas

def cmd_gotchas(args, idx):
    terms = [t for t in (args.query or "").lower().split()]
    ranked = []
    for s in idx.sources:
        n = score(terms, haystack_source(s)) if terms else 1
        if n:
            ranked.append((n, s))
    ranked.sort(key=lambda r: (-r[0], r[1]["id"]))
    out = [(s["id"], g) for _, s in ranked for g in s.get("gotchas", [])]
    if args.json:
        print(json.dumps([{"source": sid, **g} for sid, g in out], indent=2))
        return 0
    if not out:
        print("no gotchas recorded for %r" % (args.query or "anything"))
        return 1
    current = None
    for sid, g in out:
        if sid != current:
            print(("\n" if current else "") + c(sid, BOLD))
            current = sid
        print("  " + c("!", YELLOW) + " " + g["trap"])
        if g.get("fix"):
            print(wrap("-> " + g["fix"], indent="      "))
    print(c("\n%d trap%s. Read them before writing the loop, not after it fails."
            % (len(out), "" if len(out) == 1 else "s"), DIM))
    return 0


def cmd_recipe(args, idx):
    _, rec = load_record(idx, args.id)
    if not rec or "recipes" not in rec:
        print("no recipes for %r" % args.id, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rec["recipes"], indent=2))
        return 0
    for r in rec["recipes"]:
        print(c("# " + r.get("title", r["lang"]), DIM))
        print(r["code"].rstrip() + "\n")
    return 0


# ---------------------------------------------------------------- add / write-back

STUB = {
    "id": "", "name": "", "publisher": "", "homepage": "",
    "description": "What is in it and what it is good for. Written for someone who has "
                   "never heard of it. At least 40 characters.",
    "topics": [], "geography": "", "license": {"name": "unclear"},
    "access": {"auth": "none", "formats": [], "bulk": False, "rate_limit": "", "etiquette": ""},
    "probes": [{"id": "smoke", "url": "", "description": "",
                "expect": {"status": [200], "body_contains": []}}],
    "recipes": [], "gotchas": [], "fields": [], "added": "", "status": "live",
}


def cmd_add(args, idx):
    hit = idx.lookup(args.url, args.title)
    known = bool(hit)
    if args.json:
        print(json.dumps({"url": args.url, "known": known,
                          "hit": hit._asdict() if hit else None,
                          "host": normalise(args.url), "domain": registrable(args.url)}, indent=2))
        return 0 if not known else 1
    if hit:
        print("%s %s %s -- %s" % (c("already known:", YELLOW), hit.kind, c(hit.id, BOLD), hit.name))
        print(c("  matched on %s" % hit.why, DIM))
        if hit.kind == "source":
            print(c("  `hw show %s`. Extend that record rather than adding a second one." % hit.id, DIM))
        elif hit.kind == "lead":
            print(c("  A lead, not a record yet. Promote it: write the record, run the probes,\n"
                    "  then `python3 src/harvest.py --mark %s catalogued`." % hit.id, DIM))
        else:
            print(c("  A dataset record names this publisher. A source record for the endpoint\n"
                    "  is still worth adding -- they answer different questions.", DIM))
        return 1
    host = normalise(args.url)
    sid = args.id or re.sub(r"[^a-z0-9]+", "-", registrable(host).rsplit(".", 1)[0]).strip("-")
    path = ROOT / "sources" / ("%s.json" % sid)
    print("%s %s" % (c("new:", GREEN), args.url))
    print(c("  host %s   domain %s   proposed id %s" % (host, registrable(host), sid), DIM))
    if path.exists():
        print(c("  %s exists already -- pick another id with --id" % path.name, YELLOW))
        return 1
    if not args.write:
        print(c("  --write to scaffold sources/%s.json" % sid, DIM))
        return 0
    from datetime import date
    stub = json.loads(json.dumps(STUB))
    stub["id"] = sid
    stub["name"] = args.title or sid
    stub["homepage"] = args.url
    stub["added"] = date.today().isoformat()
    stub["probes"][0]["url"] = args.url
    path.write_text(json.dumps(stub, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  wrote %s" % c("sources/%s.json" % sid, BOLD))
    print(c("  Fill it in, then: python3 src/validate.py %s && python3 src/probe.py %s\n"
            "  Do not commit a record whose probes you have not run." % (sid, sid), DIM))
    return 0


def cmd_used_by(args, idx):
    path = ROOT / "sources" / ("%s.json" % args.id)
    if not path.exists():
        print("no source %r" % args.id, file=sys.stderr)
        return 1
    rec = json.loads(path.read_text(encoding="utf-8"))
    used = rec.setdefault("used_by", [])
    if args.project in used:
        print("%s already lists %s" % (args.id, args.project))
        return 0
    used.append(args.project)
    used.sort()
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("%s used_by: %s" % (c(args.id, BOLD), ", ".join(used)))
    return 0


# ---------------------------------------------------------------- health / stats

def health_markdown(h):
    """The issue body the weekly run files when something flips. Exit 1 if nothing did.

    Written so the issue is actionable on its own: what changed, what the record already
    says about that source, and the command to reproduce. An alert that only says
    "something is red" makes the reader go and find out, which is the work.
    """
    changes = h.get("changes", [])
    if not changes:
        return 1
    broke = [c for c in changes if c["change"] in ("broke", "new")]
    fixed = [c for c in changes if c["change"] == "recovered"]
    gone = [c for c in changes if c["change"] == "removed"]
    slowed = [c for c in changes if c["change"] == "throttled"]
    if not broke and not gone:
        # Recoveries and rate limits are worth printing, never worth an issue. A watcher
        # that opens one for "the publisher throttled us this week" gets ignored, and
        # then the week something really closes gets ignored with it.
        return 1
    print("Probe run %s found %d change%s."
          % (h.get("checked", "?")[:16], len(changes), "" if len(changes) == 1 else "s"))
    idx = Index.load(ROOT)
    by_id = {s["id"]: s for s in idx.sources}
    for label, group in (("Stopped answering", broke), ("Probe removed", gone),
                         ("Recovered", fixed), ("Rate-limited, not broken", slowed)):
        if not group:
            continue
        print("\n## %s\n" % label)
        for ch in group:
            s = by_id.get(ch["source"], {})
            print("- **%s** / `%s` — %s" % (ch["source"], ch["probe"], ch["detail"]))
            print("  - record says: status `%s`, %d gotcha(s), last verified %s"
                  % (s.get("status", "?"), len(s.get("gotchas", [])), s.get("verified", "never")))
            print("  - reproduce: `python3 src/probe.py %s`" % ch["source"])
    print("\n---\nIf a source has genuinely closed, keep the record: set `status` to "
          "`closed` or `degraded` and give the probe a `known_broken` note saying what "
          "was tried and when. A dead endpoint documented is worth as much as a live one.")
    return 0



def joins_for(rid):
    if not JOINS.exists():
        return []
    return json.loads(JOINS.read_text(encoding="utf-8")).get("joins", {}).get(rid, [])


def cmd_joins(args, idx):
    kind, rec = load_record(idx, args.id)
    if not rec:
        print("no record %r" % args.id, file=sys.stderr)
        return 1
    edges = joins_for(args.id)
    if args.json:
        print(json.dumps(edges, indent=2))
        return 0
    print(c(rec.get("title", args.id), BOLD))
    if not edges:
        print(c("  no join candidates. Either no entity key was found in its columns or "
                "description,\n  or nothing else shares one.", DIM))
        return 1
    titles = {d["id"]: d.get("title", "") for d in idx.datasets}
    for e in edges:
        print("  %s on %s" % (c("join", GREEN if e["basis"] == "columns" else YELLOW),
                              c(e["key"], BOLD)))
        print("     %s  %s" % (c(e["other"], DIM), titles.get(e["other"], e.get("title", ""))))
        print(c("     evidence: %s" % {
            "columns": "both declare the key as a column",
            "mixed": "one declares the column; the other only describes it",
            "inferred": "read out of both descriptions - a guess, not a fact",
        }[e["basis"]], DIM))
    return 0


def cmd_probe(args, idx):
    cmd = [sys.executable, str(ROOT / "src" / "probe.py")] + args.ids
    return subprocess.call(cmd)


def cmd_health(args, idx):
    if not HEALTH.exists():
        print("no health.json -- run `hw probe`", file=sys.stderr)
        return 1
    h = json.loads(HEALTH.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(h, indent=2))
        return 0
    if args.markdown:
        return health_markdown(h)
    by_state = {"ok": [], "failing": [], "throttled": [], "dead": []}
    for sid, probes in h.get("results", {}).items():
        for pid, r in probes.items():
            by_state[state_of(r)].append((sid, pid, r))
    total = sum(len(v) for v in by_state.values())
    print("%d probes, %s, %s, %s, %s   %s" % (
        total, c("%d ok" % len(by_state["ok"]), GREEN),
        c("%d failing" % len(by_state["failing"]), RED if by_state["failing"] else DIM),
        c("%d throttled" % len(by_state["throttled"]), YELLOW if by_state["throttled"] else DIM),
        c("%d known-dead" % len(by_state["dead"]), DIM),
        c("checked %s" % h.get("checked", "?")[:16], DIM)))
    for label, colour, group in (("FAIL", RED, by_state["failing"]),
                                 ("slow", YELLOW, by_state["throttled"])):
        for sid, pid, r in group:
            print("  %s %-24s %-20s %s" % (c(label, colour), sid, pid,
                                           c("; ".join(r.get("why", []))[:70], DIM)))
    if by_state["throttled"]:
        print(c("  throttled = 429, 503 or a read timeout. Us asking too often, not the "
                "endpoint breaking.", DIM))
    return 1 if by_state["failing"] else 0


def cmd_stats(args, idx):
    counts = idx.counts()
    if args.json:
        print(json.dumps(counts, indent=2))
        return 0
    import collections
    subj = collections.Counter(s for d in idx.datasets for s in d.get("subjects", []))
    agg = collections.Counter(f.get("aggregation") for d in idx.datasets
                              for f in d.get("found_in", []))
    feeds = collections.Counter(v.get("feed") for v in idx.leads.values()
                                if v.get("state") == "new")
    print(c("datasets", BOLD) + "  %d   %d columns across %d files"
          % (counts["datasets"],
             sum(len(t.get("columns", [])) for d in idx.datasets for t in d.get("tables", [])),
             sum(len(d.get("tables", [])) for d in idx.datasets)))
    print("  surfaced by: " + ", ".join("%s %d" % (k, v) for k, v in agg.most_common()))
    print("  subjects: " + ", ".join("%s %d" % (k, v) for k, v in subj.most_common(6)) + " ...")
    live = sum(1 for s in idx.sources if s.get("status", "live") == "live")
    print(c("sources", BOLD) + "   %d   %d live, %d probes, %d gotchas"
          % (counts["sources"], live, sum(len(s.get("probes", [])) for s in idx.sources),
             sum(len(s.get("gotchas", [])) for s in idx.sources)))
    print(c("leads", BOLD) + "     %d new of %d   (%s)"
          % (counts["leads_new"], counts["leads"],
             ", ".join("%s %d" % (k, v) for k, v in feeds.most_common())))
    return 0


# ---------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(prog="hw", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def add(name, fn, help):
        p = sub.add_parser(name, help=help)
        p.set_defaults(fn=fn)
        p.add_argument("--json", action="store_true", help="machine-readable output")
        return p

    p = add("find", cmd_find, "search both layers")
    p.add_argument("query", nargs="+")
    p.add_argument("--layer", choices=["both", "sources", "datasets"], default="both")
    p.add_argument("--limit", type=int, default=12)

    p = add("show", cmd_show, "the whole record")
    p.add_argument("id")

    p = add("gotchas", cmd_gotchas, "the traps, optionally filtered")
    p.add_argument("query", nargs="*")

    p = add("recipe", cmd_recipe, "copy-paste starting points")
    p.add_argument("id")

    p = add("add", cmd_add, "is this source already known? if not, scaffold it")
    p.add_argument("url")
    p.add_argument("--title", default=None)
    p.add_argument("--id", default=None, help="override the derived record id")
    p.add_argument("--write", action="store_true", help="write the stub record")

    p = add("joins", cmd_joins, "what this dataset could be joined with")
    p.add_argument("id")

    p = add("used-by", cmd_used_by, "record that a project consumed a source")
    p.add_argument("id")
    p.add_argument("project")

    p = add("probe", cmd_probe, "run the probes now")
    p.add_argument("ids", nargs="*")

    p = add("health", cmd_health, "what is failing today")
    p.add_argument("--markdown", action="store_true",
                   help="issue body for what changed since the run before; exit 1 if nothing did")
    add("stats", cmd_stats, "what is in here")

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    if hasattr(args, "query") and isinstance(args.query, list):
        args.query = " ".join(args.query)
    return args.fn(args, Index.load(ROOT))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
