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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quality                                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# (directory, schema, label) - sources are probed access routes, datasets are things to work with
COLLECTIONS = [
    (ROOT / "sources", ROOT / "schema" / "source.schema.json", "source"),
    (ROOT / "datasets", ROOT / "schema" / "dataset.schema.json", "dataset"),
]

TYPES = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool,
}


def check(node, schema, path, errs):
    if "enum" in schema and node not in schema["enum"]:
        errs.append("%s: %r is not one of %s" % (path, node, schema["enum"]))
        return
    t = schema.get("type")
    if isinstance(t, list):                       # e.g. ["integer", "null"]
        if node is None and "null" in t:
            return
        allowed = tuple(TYPES[x] for x in t if x != "null")
        if allowed and not isinstance(node, allowed):
            errs.append("%s: expected one of %s, got %s" % (path, t, type(node).__name__))
            return
        t = next((x for x in t if x != "null"), None)
        if not t:
            return
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


def load_records(directory, only=None):
    for f in sorted(directory.glob("*.json")):
        if only and f.stem not in only:
            continue
        with f.open(encoding="utf-8") as fh:
            yield f, json.load(fh)


def main(argv):
    only = set(argv) or None
    total, bad = 0, 0
    for directory, schema_path, label in COLLECTIONS:
        if not directory.is_dir():
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        seen_ids, n = {}, 0
        for f, rec in load_records(directory, only):
            n += 1
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
                print("FAIL %s/%s" % (directory.name, f.name))
                for e in errs:
                    print("     %s" % e)

        if label == "source" and not only:
            ids = set(seen_ids)
            for f, rec in load_records(directory):
                for ref in rec.get("related", []):
                    if ref not in ids:
                        print("WARN %s: related id %r has no record" % (f.name, ref))

        if label == "dataset" and not only:
            # Prose quality is a schema-shaped question the schema cannot ask: whether a
            # hook describes this dataset or the publisher's standing boilerplate is only
            # answerable by comparing it with every other record. Warnings, not failures --
            # a readme that genuinely says nothing is a fact about the week, not a defect.
            known = quality.load_learned()
            if not known:
                print("WARN no boilerplate.json; run `python3 src/quality.py --learn`")
            else:
                # Summarised, not listed. Sixty WARN lines on every run is how a warning
                # becomes wallpaper; the count is enough to notice a regression, and
                # src/quality.py prints the detail when someone wants to act on it.
                kinds = {}
                affected = 0
                for f, rec in load_records(directory):
                    found = quality.problems(rec, known)
                    affected += bool(found)
                    for problem in found:
                        kinds[re.sub(r"\d+", "N", problem)] = \
                            kinds.get(re.sub(r"\d+", "N", problem), 0) + 1
                if affected:
                    print("WARN %d record(s) with prose problems: %s"
                          % (affected, ", ".join("%s x%d" % (k, v) for k, v in
                                                 sorted(kinds.items(), key=lambda kv: -kv[1]))))
                    print("     `python3 src/quality.py` lists them; `--sweep` strips boilerplate")

        print("%d %s%s checked" % (n, label, "" if n == 1 else "s"))

    print("%d record%s total, %d with problems" % (total, "" if total == 1 else "s", bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
