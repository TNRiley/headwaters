#!/usr/bin/env python3
"""Validate every sources/*.json against schema/source.schema.json.

Deliberately dependency-free: this repo should be usable by an agent that has a
shell and nothing else, on a machine where `pip install` is not an option.
Supports the subset of JSON Schema draft-07 that source.schema.json actually
uses -- type, required, properties, additionalProperties:false, items, enum,
pattern, minItems, minLength, minimum. `format` is documentation only.

    python3 src/validate.py            # all sources
    python3 src/validate.py ghcn-daily # one
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "source.schema.json"
SOURCES = ROOT / "sources"

TYPES = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool,
}


def check(node, schema, path, errs):
    if "enum" in schema and node not in schema["enum"]:
        errs.append("%s: %r is not one of %s" % (path, node, schema["enum"]))
        return
    t = schema.get("type")
    if t:
        py = TYPES[t]
        # bool is a subclass of int in Python; do not let True pass as integer
        if t in ("integer", "number") and isinstance(node, bool):
            errs.append("%s: expected %s, got boolean" % (path, t))
            return
        if not isinstance(node, py):
            errs.append("%s: expected %s, got %s" % (path, t, type(node).__name__))
            return

    if isinstance(node, str):
        if "minLength" in schema and len(node) < schema["minLength"]:
            errs.append("%s: needs at least %d characters, has %d"
                        % (path, schema["minLength"], len(node)))
        pat = schema.get("pattern")
        if pat and not re.search(pat, node):
            errs.append("%s: %r does not match %s" % (path, node, pat))

    if isinstance(node, list):
        if "minItems" in schema and len(node) < schema["minItems"]:
            errs.append("%s: needs at least %d item(s)" % (path, schema["minItems"]))
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(node):
                check(item, item_schema, "%s[%d]" % (path, i), errs)

    if isinstance(node, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in node:
                errs.append("%s: missing required field %r" % (path, req))
        if schema.get("additionalProperties") is False:
            for key in node:
                if key not in props:
                    errs.append("%s: unknown field %r" % (path, key))
        for key, value in node.items():
            if key in props:
                check(value, props[key], "%s.%s" % (path, key) if path else key, errs)

    if isinstance(node, (int, float)) and "minimum" in schema:
        if node < schema["minimum"]:
            errs.append("%s: %s is below minimum %s" % (path, node, schema["minimum"]))


def load_sources(only=None):
    for f in sorted(SOURCES.glob("*.json")):
        if only and f.stem not in only:
            continue
        with f.open(encoding="utf-8") as fh:
            yield f, json.load(fh)


def main(argv):
    only = set(argv) or None
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    seen_ids, total, bad = {}, 0, 0

    for f, rec in load_sources(only):
        total += 1
        errs = []
        check(rec, schema, "", errs)
        if rec.get("id") != f.stem:
            errs.append("id %r does not match filename %s" % (rec.get("id"), f.name))
        if rec.get("id") in seen_ids:
            errs.append("duplicate id, also in %s" % seen_ids[rec["id"]])
        seen_ids[rec.get("id")] = f.name
        pids = [p.get("id") for p in rec.get("probes", [])]
        if len(pids) != len(set(pids)):
            errs.append("duplicate probe ids: %s" % pids)
        if errs:
            bad += 1
            print("FAIL %s" % f.name)
            for e in errs:
                print("     %s" % e)

    # cross-references resolve
    ids = set(seen_ids)
    if not only:
        for f, rec in load_sources():
            for ref in rec.get("related", []):
                if ref not in ids:
                    print("WARN %s: related id %r has no record" % (f.name, ref))

    print("%d source%s checked, %d with problems" % (total, "" if total == 1 else "s", bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
