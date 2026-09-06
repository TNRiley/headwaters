#!/usr/bin/env python3
"""Pull candidate datasets from the initiatives that already do the finding, into leads.json.

Headwaters is not trying to out-collect Data Is Plural or the AWS registry. Those
are lead lists: long, wide, and unverified. This repository is the opposite -
short, deep, and probed. Harvest brings their leads in so a future session has a
queue to work from, and so the same dataset is never researched twice.

A lead is not a source. Promoting one means reading it, writing a real record with
working probes, and running src/probe.py. Then mark the lead catalogued.

    python3 src/harvest.py                      # every feed
    python3 src/harvest.py --feed dip           # one
    python3 src/harvest.py --list new | head    # what is waiting
    python3 src/harvest.py --mark dip:2019.03.06-2 catalogued

On redistribution: Data Is Plural's prose belongs to its author, so only the
headline, the links and a short excerpt are stored, with the edition date so the
original entry can always be read in place.
"""
import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
LEADS = ROOT / "leads.json"
UA = ("headwaters-harvest/1.0 (+https://github.com/TNRiley/headwaters; "
      "tnril@users.noreply.github.com)")

DIP_CSV = ("https://docs.google.com/spreadsheets/d/"
           "1wZhPLMCHKJvwOkP4juclhjFgqIY8fQFMemwKL2c64vk/export?format=csv&gid=0")
TT_YEARS = range(2018, date.today().year + 1)
GH_CONTENTS = "https://api.github.com/repos/%s/contents/%s"

# Hosts too generic to imply "we already have this". A Data Is Plural entry that
# links to github.com tells you nothing about whether we hold that dataset.
GENERIC_HOSTS = {
    "github.com", "raw.githubusercontent.com", "api.github.com", "gist.github.com",
    "docs.google.com", "drive.google.com", "sites.google.com",
    "dropbox.com", "archive.org", "web.archive.org", "zenodo.org", "figshare.com",
    "huggingface.co", "kaggle.com", "data.world", "twitter.com", "x.com",
    # the feeds' own hosts: every lead from a feed points at its own index
    "registry.opendata.aws", "data-is-plural.com",
}


def get(url, tries=3):
    # share probe.py's CA-bundle fallback: some Python builds have no usable store
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from probe import CTX
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=60, context=CTX).read()
        except Exception as e:                    # transient 5xx are common here
            last = e
    raise last


def known_hosts():
    """Hosts we already have a real record for, so their leads are not new."""
    hosts, slugs = set(), set()
    for f in SOURCES.glob("*.json"):
        rec = json.loads(f.read_text(encoding="utf-8"))
        slugs.add(rec["id"])
        for url in [rec["homepage"]] + [p["url"] for p in rec.get("probes", [])]:
            host = urlsplit(url).netloc.lower().replace("www.", "")
            if host and host not in GENERIC_HOSTS:
                hosts.add(host)
    return hosts, slugs


def feed_dip():
    rows = list(csv.DictReader(io.StringIO(get(DIP_CSV).decode("utf-8", "replace"))))
    for row in rows:
        edition, pos = row.get("edition", ""), row.get("position", "")
        text = " ".join((row.get("text") or "").split())
        links = [u for u in re.split(r"[\s,;]+", row.get("links") or "") if u.startswith("http")]
        yield {
            "id": "dip:%s-%s" % (edition, pos),
            "feed": "data-is-plural",
            "title": (row.get("headline") or "").strip(),
            "excerpt": text[:220] + ("..." if len(text) > 220 else ""),
            "links": links[:5],
            "published": edition,
            "read_it_at": "https://www.data-is-plural.com/archive/%s/" % edition.replace(".", "-"),
        }


def feed_tidytuesday():
    for year in TT_YEARS:
        try:
            weeks = json.loads(get(GH_CONTENTS % ("rfordatascience/tidytuesday", "data/%d" % year)))
        except Exception:
            continue
        if not isinstance(weeks, list):
            continue
        for w in weeks:
            if w.get("type") != "dir":
                continue
            yield {
                "id": "tt:%s" % w["name"],
                "feed": "tidytuesday",
                "title": "TidyTuesday %s" % w["name"],
                "excerpt": "",
                "links": ["https://github.com/rfordatascience/tidytuesday/tree/main/%s" % w["path"]],
                "published": w["name"],
                "read_it_at": ("https://raw.githubusercontent.com/rfordatascience/tidytuesday/"
                               "main/%s/readme.md" % w["path"]),
            }


def feed_aws():
    # The contents API ignores per_page/page and truncates at 1,000 entries, so it
    # silently hides ~200 of the registry's datasets. The git trees API does not.
    tree = json.loads(get("https://api.github.com/repos/awslabs/open-data-registry/"
                          "git/trees/main?recursive=1"))
    for node in tree.get("tree", []):
        path = node.get("path", "")
        if not (path.startswith("datasets/") and path.endswith(".yaml")):
            continue
        slug = path[len("datasets/"):-len(".yaml")]
        yield {
            "id": "aws:%s" % slug,
            "feed": "aws-open-data-registry",
            "title": slug.replace("-", " "),
            "excerpt": "",
            "links": ["https://registry.opendata.aws/%s/" % slug],
            "published": "",
            "read_it_at": ("https://raw.githubusercontent.com/awslabs/open-data-registry/"
                           "main/%s" % path),
        }


FEEDS = {"dip": feed_dip, "tidytuesday": feed_tidytuesday, "aws": feed_aws}


def load_leads():
    if LEADS.exists():
        return json.loads(LEADS.read_text(encoding="utf-8"))
    return {"updated": "", "leads": {}}


def save_leads(db):
    db["updated"] = date.today().isoformat()
    with LEADS.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(db, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feed", choices=list(FEEDS) + ["all"], default="all")
    ap.add_argument("--list", dest="want", choices=["new", "catalogued", "rejected", "all"])
    ap.add_argument("--mark", nargs=2, metavar=("LEAD_ID", "STATE"))
    args = ap.parse_args(argv)
    db = load_leads()

    if args.mark:
        lead_id, state = args.mark
        if lead_id not in db["leads"]:
            print("no such lead: %s" % lead_id, file=sys.stderr)
            return 1
        db["leads"][lead_id]["state"] = state
        save_leads(db)
        print("%s -> %s" % (lead_id, state))
        return 0

    if args.want:
        for lead in sorted(db["leads"].values(), key=lambda x: x["id"]):
            if args.want == "all" or lead.get("state") == args.want:
                print("%-28s %-22s %s" % (lead["id"], lead["feed"], lead["title"][:70]))
        return 0

    hosts, slugs = known_hosts()
    added = 0
    for name in ([args.feed] if args.feed != "all" else list(FEEDS)):
        print("harvesting %s ..." % name)
        for lead in FEEDS[name]():
            if lead["id"] in db["leads"]:
                continue
            lead_hosts = {urlsplit(u).netloc.lower().replace("www.", "") for u in lead["links"]}
            lead["state"] = "catalogued" if (lead_hosts & hosts) else "new"
            lead["discovered"] = date.today().isoformat()
            db["leads"][lead["id"]] = lead
            added += 1

    save_leads(db)
    states = {}
    for lead in db["leads"].values():
        states[lead.get("state", "new")] = states.get(lead.get("state", "new"), 0) + 1
    print("%d new lead%s; %d total (%s)"
          % (added, "" if added == 1 else "s", len(db["leads"]),
             ", ".join("%s %d" % (k, v) for k, v in sorted(states.items()))))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:          # `| head`
        sys.exit(0)
