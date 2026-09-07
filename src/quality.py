#!/usr/bin/env python3
"""Catch text that describes the aggregation instead of the dataset.

The browsing layer lives on its hooks. A quarter of the first 428 records opened with
TidyTuesday's standing request to add alt text to your charts -- three paragraphs about
writing accessible visualisations, filed as the description of a dataset about technology
adoption. It is not a typo to fix week by week: the same block appears in 106 records, and
the next aggregation will have its own.

The generalisable signal is repetition. **A paragraph that appears verbatim in several
records is not a description of any of them** -- it is the publisher's boilerplate, and no
amount of reading one record tells you that. So this is a corpus-level judgement, computed
once and then applied per record, which is also why it belongs here rather than in a
fetcher: every future ingest gets it for free by consulting the same learned set.

    python3 src/quality.py                # report on the corpus
    python3 src/quality.py --learn        # (re)learn the boilerplate set -> boilerplate.json
    python3 src/quality.py --fix          # strip learned boilerplate from stored hooks

Learning is deliberately conservative: at least MIN_RECORDS distinct records and
MIN_CHARS characters. Repetition of a short line ("Data source:") is normal; repetition
of a paragraph is not.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"
LEARNED = ROOT / "boilerplate.json"

# A paragraph in 3+ records is boilerplate. Two records can legitimately share prose --
# a publisher's series described the same way twice -- and three is where coincidence stops.
MIN_RECORDS = 3
MIN_CHARS = 40

# Hooks shorter than this say nothing. The median good hook runs to several hundred.
SHORT_HOOK = 80


def fingerprint(text):
    """Comparable form of a paragraph: letters and digits only.

    The same boilerplate arrives with different markdown, spacing and curly quotes from
    one week to the next -- comparing raw strings split the alt-text block into a group
    of 93 and a group of 14.
    """
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def paragraphs(text):
    """Split a hook the way the prose was originally written.

    Hooks are stored as one joined string, so the paragraph breaks are gone. What survives
    is sentence structure and the heading fragments the markdown stripper left behind
    ("### Chart type" becomes "Chart type" mid-string), so split on sentence ends and keep
    the pieces long enough to judge.
    """
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    out, buf = [], ""
    for p in parts:
        buf = (buf + " " + p).strip()
        if len(buf) >= MIN_CHARS:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def learn(texts, min_records=MIN_RECORDS, min_chars=MIN_CHARS):
    """Fingerprints that recur across records, with a sample of the original wording."""
    seen, sample = defaultdict(set), {}
    for i, text in enumerate(texts):
        for p in paragraphs(text):
            if len(p) < min_chars:
                continue
            fp = fingerprint(p)
            if len(fp) < min_chars:
                continue
            seen[fp].add(i)
            sample.setdefault(fp, p)
    return {fp: {"records": len(ids), "sample": sample[fp][:200]}
            for fp, ids in seen.items() if len(ids) >= min_records}


def load_learned():
    """The learned set, minus the fragments a reader has judged to be real content.

    Repetition is a good signal, not a perfect one: three different weeks genuinely drew
    on IMDb and said so in the same words. Rather than raising the threshold until that
    one survives -- which would also let real boilerplate through -- the exception is
    recorded with its reason, the way classify.py records a misleading title. Learning
    again preserves them.
    """
    if not LEARNED.exists():
        return {}
    payload = json.loads(LEARNED.read_text(encoding="utf-8"))
    keep = payload.get("not_boilerplate", {})
    return {fp: v for fp, v in payload.get("boilerplate", {}).items() if fp not in keep}


def strip(text, known):
    """Drop the boilerplate sentences, keep the rest, and tidy the seams."""
    kept = [p for p in paragraphs(text) if fingerprint(p) not in known]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def problems(rec, known):
    """What is wrong with this record's prose, worst first. Empty list means fine."""
    out = []
    hook = (rec.get("hook") or "").strip()
    if not hook:
        out.append("no hook")
        return out
    paras = paragraphs(hook)
    if paras:
        boiler = sum(len(p) for p in paras if fingerprint(p) in known)
        share = boiler / max(1, len(hook))
        if share > 0.6:
            out.append("hook is %d%% publisher boilerplate" % round(share * 100))
        elif share > 0.15:
            out.append("hook contains %d%% boilerplate" % round(share * 100))
    if len(hook) < SHORT_HOOK:
        out.append("hook is %d characters" % len(hook))
    tail = hook.rstrip()
    last = tail.split()[-1] if tail.split() else ""
    # A hook ending "…" was cut by the length cap. Otherwise, missing terminal punctuation
    # means cut mid-sentence -- unless the last word contains a dot, because plenty of real
    # sentences end on a filename or a domain ("via scrapebeers.R", "the Independent.ie").
    if tail.endswith("…") or (not re.search(r"[.!?\"')\]]$", tail) and "." not in last):
        out.append("hook looks truncated mid-sentence")
    return out


def load_records():
    return [(f, json.loads(f.read_text(encoding="utf-8")))
            for f in sorted(DATASETS.glob("*.json"))]


MAX_ROUNDS = 8


def sweep(args):
    """Learn and strip until the corpus stops changing.

    One pass is never enough, and the reason is worth understanding before trusting the
    result. Fragments are compared as groups of whole sentences, so removing the first
    half of a boilerplate block re-groups what is left: sentences that were buried mid-chunk
    become the head of a new chunk, with a fingerprint nobody had seen. Stripping the
    alt-text block's opening paragraphs exposed eight more fragments underneath, in the
    same 107 records. Alternating until a round changes nothing is what converges.
    """
    for round_no in range(1, MAX_ROUNDS + 1):
        records = load_records()
        found = learn([r.get("hook") for _, r in records])
        previous = json.loads(LEARNED.read_text(encoding="utf-8")) if LEARNED.exists() else {}
        keep = previous.get("not_boilerplate", {})
        merged = dict(previous.get("boilerplate", {}))
        merged.update(found)                       # accumulate: each round sees a new layer
        LEARNED.write_text(json.dumps(
            {"learned_from": "datasets/*.json (%d records)" % len(records),
             "min_records": MIN_RECORDS, "min_chars": MIN_CHARS,
             "not_boilerplate": keep, "boilerplate": merged},
            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        known = {fp: v for fp, v in merged.items() if fp not in keep}
        changed = 0
        for path, rec in records:
            if rec.get("hook_source") == "manual":
                continue
            before = rec.get("hook") or ""
            after = strip(before, known)
            if after != before:
                rec["hook"] = after
                path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
                changed += 1
        print("round %d: %d fragment(s) known, %d record(s) changed"
              % (round_no, len(known), changed))
        if not changed:
            print("converged.")
            return 0
    print("still changing after %d rounds -- look at boilerplate.json before trusting it"
          % MAX_ROUNDS, file=sys.stderr)
    return 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--learn", action="store_true", help="rewrite boilerplate.json")
    ap.add_argument("--fix", action="store_true",
                    help="strip learned boilerplate from stored hooks")
    ap.add_argument("--sweep", action="store_true",
                    help="learn and strip repeatedly until nothing changes")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.sweep:
        return sweep(args)

    records = load_records()
    if args.learn:
        found = learn([r.get("hook") for _, r in records])
        previous = json.loads(LEARNED.read_text(encoding="utf-8")) if LEARNED.exists() else {}
        payload = {"learned_from": "datasets/*.json (%d records)" % len(records),
                   "min_records": MIN_RECORDS, "min_chars": MIN_CHARS,
                   # judgements survive relearning; the learned set does not
                   "not_boilerplate": previous.get("not_boilerplate", {}),
                   "boilerplate": found}
        LEARNED.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        print("learned %d boilerplate fragment(s) -> %s" % (len(found), LEARNED.name))
        for fp, info in sorted(found.items(), key=lambda kv: -kv[1]["records"])[:10]:
            print("  %3d records  %s" % (info["records"], info["sample"][:96]))
        return 0

    known = load_learned()
    if not known:
        print("no boilerplate.json; run `python3 src/quality.py --learn` first", file=sys.stderr)
        return 1

    if args.fix:
        changed = 0
        for path, rec in records:
            if rec.get("hook_source") == "manual":     # a written hook is never regenerated
                continue
            before = rec.get("hook") or ""
            after = strip(before, known)
            if after != before:
                rec["hook"] = after
                path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
                changed += 1
                if not args.quiet:
                    print("%-16s %4d -> %4d chars  %s"
                          % (rec["id"], len(before), len(after), (after[:60] or "(now empty)")))
        print("\nstripped boilerplate from %d record(s)." % changed)
        print("Records left with nothing are the honest outcome: the readme said nothing "
              "about the data.\nRe-run src/fetch_tidytuesday.py to recover prose the "
              "boilerplate had pushed past the length cap.")
        return 0

    counts = Counter()
    for _, rec in records:
        for p in problems(rec, known):
            counts[re.sub(r"\d+", "N", p)] += 1
            if not args.quiet:
                print("%-16s %s" % (rec["id"], p))
    print("\n%d of %d records have something wrong with their prose:"
          % (sum(1 for _, r in records if problems(r, known)), len(records)))
    for kind, n in counts.most_common():
        print("  %4d  %s" % (n, kind))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
