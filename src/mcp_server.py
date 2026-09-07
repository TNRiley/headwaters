#!/usr/bin/env python3
"""Serve the catalogue to any Claude session as MCP tools, over stdio.

The CLI helps a session that is already in this directory. Most sessions are not.
This makes the catalogue a tool the model can reach from any project, which is the
difference between a reference that gets consulted and one that gets forgotten --
and it is the half of the write-back loop that matters: a session that can query
Headwaters while building something is a session that can add to it afterwards.

Register it once (Claude Code):

    claude mcp add headwaters -- /usr/bin/python3 /abs/path/to/headwaters/src/mcp_server.py

Then any session has headwaters_find, headwaters_show, headwaters_gotchas,
headwaters_recipe, headwaters_known, headwaters_used_by and headwaters_health.

Hand-rolled JSON-RPC rather than the MCP SDK, for the same reason as everything else
here: no pip. The protocol surface actually needed is three methods.

Protocol note: every byte of protocol goes to stdout and nothing else ever may --
one stray print() corrupts the stream and the server dies with an unhelpful parse
error on the client side. Diagnostics go to stderr.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw                                             # noqa: E402
from match import Index                               # noqa: E402
from probe import state_of                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2024-11-05"

# The index is read once and reused. The catalogue is a few MB of JSON and changes
# only when a session edits it, so a long-lived server would go stale; _index()
# reloads when any record file is newer than the load.
_cache = {"index": None, "stamp": None}


def _stamp():
    newest = 0.0
    for directory in ("sources", "datasets"):
        d = ROOT / directory
        if d.is_dir():
            for f in d.glob("*.json"):
                newest = max(newest, f.stat().st_mtime)
    return newest


def _index():
    now = _stamp()
    if _cache["index"] is None or now != _cache["stamp"]:
        _cache["index"] = Index.load(ROOT)
        _cache["stamp"] = now
    return _cache["index"]


# ------------------------------------------------------------------ tools

def t_find(args):
    idx = _index()
    layer = args.get("layer", "both")
    kinds = {"both": ("sources", "datasets"), "sources": ("sources",),
             "datasets": ("datasets",)}.get(layer, ("sources", "datasets"))
    query = args.get("query", "")
    hits, total = hw.search(idx, query, kinds, int(args.get("limit", 10)))
    terms = [t for t in query.lower().split() if t]
    if not hits:
        return ("Nothing in the catalogue for %r.\n"
                "leads.json holds %d unpromoted candidates that are not searchable here; "
                "a lead is a name and a link, not a record."
                % (query, idx.counts()["leads_new"]))
    lines = []
    for n, kind, r in hits:
        if kind == "source":
            lines.append("SOURCE %s -- %s [%s]" % (r["id"], r.get("name", ""),
                                                   r.get("status", "live")))
            lines.append("  " + (r.get("description", "")[:280]))
            acc = r.get("access", {})
            lines.append("  auth=%s formats=%s gotchas=%d recipes=%d"
                         % (acc.get("auth", "?"), ",".join(acc.get("formats", [])),
                            len(r.get("gotchas", [])), len(r.get("recipes", []))))
        else:
            lines.append("DATASET %s -- %s" % (r["id"], r.get("title", "")))
            cols = hw.matched_columns(r, terms)
            lines.append("  subjects: %s" % "; ".join(r.get("subjects", [])))
            if cols:
                lines.append("  matching columns: %s" % ", ".join(cols[:8]))
    if total > len(hits):
        lines.append("\n(%d more matches; raise `limit`)" % (total - len(hits)))
    lines.append("\nUse headwaters_show for the whole record. For a source, read its "
                 "gotchas before writing any fetching code.")
    return "\n".join(lines)


def t_show(args):
    idx = _index()
    kind, rec = hw.load_record(idx, args.get("id", ""))
    if not rec:
        hit = idx.lookup(args.get("id", ""))
        return "No record %r.%s" % (args.get("id"),
                                    (" Closest: %s %s." % (hit.kind, hit.id)) if hit else
                                    " Try headwaters_find.")
    if kind == "source":
        rec = dict(rec)
        rec["_probe_results"] = hw.health_for(rec["id"])
        rec["_note"] = ("The gotchas field is the most valuable part of this record. "
                        "Probe results say what answered when health.json was last written, "
                        "not necessarily now.")
    return json.dumps(rec, indent=2, ensure_ascii=False)


def t_gotchas(args):
    idx = _index()
    terms = [t for t in args.get("query", "").lower().split()]
    ranked = []
    for s in idx.sources:
        n = hw.score(terms, hw.haystack_source(s)) if terms else 1
        if n:
            ranked.append((n, s))
    ranked.sort(key=lambda r: (-r[0], r[1]["id"]))
    out = []
    for _, s in ranked[:int(args.get("limit", 8))]:
        for g in s.get("gotchas", []):
            out.append("[%s] %s%s" % (s["id"], g["trap"],
                                      "\n    FIX: " + g["fix"] if g.get("fix") else ""))
    return "\n".join(out) if out else "No gotchas recorded matching that."


def t_recipe(args):
    idx = _index()
    _, rec = hw.load_record(idx, args.get("id", ""))
    if not rec or not rec.get("recipes"):
        return "No recipes for %r." % args.get("id")
    return "\n\n".join("# %s [%s]\n%s" % (r.get("title", ""), r["lang"], r["code"])
                       for r in rec["recipes"])


def t_known(args):
    """The dedup question, exposed. Ask before researching a source from scratch."""
    idx = _index()
    hit = idx.lookup(args.get("url", ""), args.get("title"))
    if not hit:
        return ("Not in the catalogue. If you end up using it, add a source record: "
                "see CLAUDE.md in the headwaters repo, or run `hw add <url> --write`. "
                "A record needs at least one probe you have actually run.")
    return ("Already known: %s %s -- %s (matched on %s).\n%s"
            % (hit.kind, hit.id, hit.name, hit.why,
               {"source": "Extend that record rather than adding a second one.",
                "lead": "A queued candidate, not a record yet. Promoting it means "
                        "researching it and writing a record with working probes.",
                "dataset": "A dataset record names this publisher. A source record for the "
                           "endpoint itself may still be worth adding."}[hit.kind]))


def t_used_by(args):
    # Deliberately not delegating to hw.cmd_used_by: that writes to stdout, which here
    # is the JSON-RPC stream. One stray line and the client sees a parse error instead
    # of a result. Anything reused from hw.py must be a pure function.
    sid, project = args.get("id", ""), args.get("project", "")
    path = ROOT / "sources" / ("%s.json" % sid)
    if not path.exists():
        return "No source %r." % sid
    rec = json.loads(path.read_text(encoding="utf-8"))
    used = rec.setdefault("used_by", [])
    if project in used:
        return "%s already lists %s." % (sid, project)
    used.append(project)
    used.sort()
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return "Recorded: %s used_by %s." % (sid, ", ".join(used))


def t_health(args):
    path = ROOT / "health.json"
    if not path.exists():
        return "No health.json yet; nothing has been probed."
    h = json.loads(path.read_text(encoding="utf-8"))
    lines = ["checked %s" % h.get("checked", "?"), json.dumps(h.get("summary", {}))]
    for sid, probes in h.get("results", {}).items():
        for pid, r in probes.items():
            state = state_of(r)
            if state == "failing":
                lines.append("FAILING %s/%s: %s" % (sid, pid, "; ".join(r.get("why", []))))
            elif state == "throttled":
                # Worth saying, worth not alarming about: the endpoint answered, it just
                # asked us to slow down. Reported the same way by `hw health`.
                lines.append("THROTTLED %s/%s (rate limit or timeout, not an outage): %s"
                             % (sid, pid, "; ".join(r.get("why", []))))
    for ch in h.get("changes", []):
        lines.append("%s %s/%s: %s" % (ch["change"].upper(), ch["source"], ch["probe"],
                                       ch["detail"]))
    return "\n".join(lines)


TOOLS = [
    {
        "name": "headwaters_find",
        "description": "Search the Headwaters open-data catalogue: 40 probed API/endpoint "
                       "records (how to get data) and 428 dataset records (what data exists, "
                       "searchable by column name). Use this BEFORE researching a data source "
                       "from scratch or writing any fetching code.",
        "handler": t_find,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "keywords; column names work well"},
                "layer": {"type": "string", "enum": ["both", "sources", "datasets"]},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "headwaters_show",
        "description": "The full record for a source or dataset id, including gotchas, "
                       "recipes, licence, auth, rate limits and latest probe results.",
        "handler": t_show,
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "headwaters_gotchas",
        "description": "The recorded traps for matching sources -- silent failures, wrong "
                       "defaults, undocumented caps. Read before writing a fetch loop.",
        "handler": t_gotchas,
        "inputSchema": {"type": "object",
                        "properties": {"query": {"type": "string"},
                                       "limit": {"type": "integer"}}},
    },
    {
        "name": "headwaters_recipe",
        "description": "Copy-paste working requests for a source id.",
        "handler": t_recipe,
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "headwaters_known",
        "description": "Is this URL or dataset already catalogued? Answers by host, publisher "
                       "domain or title. Ask before adding anything, to avoid a duplicate record.",
        "handler": t_known,
        "inputSchema": {"type": "object",
                        "properties": {"url": {"type": "string"},
                                       "title": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "headwaters_used_by",
        "description": "Record that a project consumed a catalogued source. Call this after "
                       "building something that used one, so the catalogue knows what earns "
                       "its keep.",
        "handler": t_used_by,
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "string"},
                                       "project": {"type": "string",
                                                   "description": "project slug"}},
                        "required": ["id", "project"]},
    },
    {
        "name": "headwaters_health",
        "description": "Which catalogued endpoints failed their probes at the last run, and "
                       "what changed since the run before.",
        "handler": t_health,
        "inputSchema": {"type": "object", "properties": {}},
    },
]
BY_NAME = {t["name"]: t for t in TOOLS}


# ------------------------------------------------------------------ transport

def result(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg):
    """One request in, one response out -- or None for a notification, which gets no reply."""
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "headwaters", "version": "1.0.0"},
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "tools/list":
        return result(rid, {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")}
                                      for t in TOOLS]})
    if method == "tools/call":
        params = msg.get("params") or {}
        tool = BY_NAME.get(params.get("name"))
        if not tool:
            return error(rid, -32602, "no such tool: %s" % params.get("name"))
        try:
            text = tool["handler"](params.get("arguments") or {})
        except Exception as e:                      # a broken record must not kill the server
            return result(rid, {"content": [{"type": "text",
                                             "text": "%s: %s" % (type(e).__name__, e)}],
                                "isError": True})
        return result(rid, {"content": [{"type": "text", "text": text}]})
    if rid is None:
        return None                                 # unknown notification: ignore silently
    return error(rid, -32601, "method not found: %s" % method)


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError as e:
            out.write(json.dumps(error(None, -32700, "parse error: %s" % e)) + "\n")
            out.flush()
            continue
        response = handle(msg)
        if response is not None:
            out.write(json.dumps(response, ensure_ascii=False) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
