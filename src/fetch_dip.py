#!/usr/bin/env python3
"""Build dataset records from the Data Is Plural archive.

TidyTuesday gave the catalogue 428 datasets shaped by one community's weekly exercise:
tidy, teachable, mostly American, mostly the sort of thing you can plot in an afternoon.
Data Is Plural is the opposite selection -- ten years of one person finding the odd,
specific and hard-to-believe-it-exists, five a week since October 2015. It is the single
best answer to "is there anything good on X?" that exists in machine-readable form.

    python3 src/fetch_dip.py            # incremental; the CSV is cached under .cache/
    python3 src/fetch_dip.py --refresh  # re-download the archive
    python3 src/fetch_dip.py --limit 20 # a taste, for checking the shape

On the prose. The archive is published for reuse but the newsletter text is its author's,
and the record we hold says plainly: link and quote with attribution, do not republish the
prose wholesale. So the full text is fetched as *working input* and never stored: what
lands in `hook` is a short quotation cut at a sentence boundary, and every record carries
the archive URL it came from. That is quoting with attribution, which is the permitted
thing, and it is also the honest thing -- the hook field means the curator's own pitch,
and here the curator is Jeremy Singer-Vine.

On merging. A dataset in two aggregations must be ONE record with two `found_in` entries,
never two records -- that is the whole reason this catalogue is keyed by dataset rather
than by week. See `Matcher` for how conservatively that is decided, and why.
"""
import argparse
import csv
import io
import json
import re
import ssl
import sys
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import normalise, registrable, title_key, PLATFORM_HOSTS   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "datasets"
CACHE = ROOT / ".cache" / "dip"
ARCHIVE = "https://www.data-is-plural.com/archive/%s/"
CSV_URL = ("https://docs.google.com/spreadsheets/d/"
           "1wZhPLMCHKJvwOkP4juclhjFgqIY8fQFMemwKL2c64vk/export?format=csv&gid=0")
UA = ("headwaters-fetch/1.0 (+https://github.com/TNRiley/headwaters; "
      "tnril@users.noreply.github.com)")

# The most we quote from any one entry, and never mid-sentence. Long enough to say what
# the dataset is, short enough to stay a quotation rather than a reproduction.
QUOTE_MAX = 320
# Where a long opening sentence is allowed to run to rather than be cut with an ellipsis.
QUOTE_HARD_MAX = 460

# Links that illustrate a point rather than lead to data. DiP routinely links a map of
# Confusion Creek, Alaska, or the tweet that tipped the author off; neither is a source.
NOT_A_SOURCE = re.compile(
    r"^(twitter\.com|x\.com|mobile\.twitter\.com|maps\.google\.|www\.google\.com/maps"
    r"|bsky\.app|mastodon\.|facebook\.com|linkedin\.com|youtube\.com|youtu\.be)")

# Hosts whose links are the write-up, not the data.
NEWSY = re.compile(
    r"(nytimes|washingtonpost|theguardian|bbc\.|reuters|bloomberg|wsj|ft\.com|npr\.org"
    r"|fivethirtyeight|propublica|theatlantic|newyorker|wired|vox\.com|buzzfeed"
    r"|hechingerreport|theverge|axios|politico|economist|apnews|cnn\.com|nbcnews"
    r"|latimes|bostonglobe|chicagotribune|texastribune|marshallproject|citylab)")


def ssl_context():
    ctx = ssl.create_default_context()
    for path in ("/etc/ssl/cert.pem", "/etc/pki/tls/certs/ca-bundle.crt",
                 "/etc/ssl/certs/ca-certificates.crt"):
        if Path(path).exists():
            try:
                ctx.load_verify_locations(path)
            except Exception:
                pass
    return ctx


CTX = ssl_context()


def fetch_csv(refresh=False):
    """The archive, cached. One request; the sheet 307-redirects before serving it."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "archive.csv"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": UA})
    text = urllib.request.urlopen(req, timeout=90, context=CTX).read().decode("utf-8")
    path.write_text(text, encoding="utf-8")
    return text


def quote(text, limit=QUOTE_MAX, hard_max=QUOTE_HARD_MAX):
    """A short quotation ending on a sentence, never mid-word.

    Cutting at a fixed character count is what produced 38 hooks ending "available online
    at" in the TidyTuesday layer. So: prefer the last sentence end within the limit; if the
    opening sentence simply runs long -- DiP quotes abstracts, and one ran 300 characters
    before its first full stop -- overshoot to the next sentence end rather than trailing
    an ellipsis. Only a sentence longer than hard_max gets cut, and then on a word.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text)]
    within = [e for e in ends if e <= limit]
    if within and within[-1] > limit // 3:
        return text[:within[-1]].strip()
    beyond = [e for e in ends if limit < e <= hard_max]
    if beyond:
        return text[:beyond[0]].strip()
    cut = text[:limit]
    return cut[:cut.rfind(" ")].rstrip(",;: ") + "…"


def clean_title(headline):
    """DiP headlines are sentences, and sometimes somebody else's article headline."""
    t = re.sub(r"\s+", " ", (headline or "").strip())
    t = t.strip("“”\"'").strip()
    t = re.sub(r"[.\s]+$", "", t)                  # trailing full stop, not an ellipsis
    return t[:1].upper() + t[1:] if t else ""


def split_links(links):
    """Data links, article links, and the ones that are neither."""
    sources, articles = [], []
    for url in links:
        url = url.strip()
        if not url.startswith("http"):
            continue
        host = urlsplit(url).netloc.lower()
        if NOT_A_SOURCE.search(host) or NOT_A_SOURCE.search(host + urlsplit(url).path):
            continue
        entry = {"name": normalise(host), "url": url}
        (articles if NEWSY.search(host) else sources).append(entry)
    # DiP often links a landing page and its download page; both canonicalise the same,
    # and two rows pointing at one resource is noise in the record and in the matcher.
    seen, unique = set(), []
    for e in sources:
        key = canonical_url(e["url"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique, articles


# Query parameters that identify the visitor, never the resource.
TRACKING = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_[a-z]+|ref|source|_ga)$")


def canonical_url(url):
    """A URL reduced to what identifies the resource.

    The query string stays, and that is the whole point. Dropping it looks tidy and is
    catastrophic here: a PLOS article is `journals.plos.org/plosone/article?id=10.1371/...`,
    so without the query every paper PLOS has ever published canonicalises to the same
    string -- and the matcher merged a 2015 newsletter entry into TidyTuesday's 2021 bird
    bath dataset on the strength of it. Plenty of government portals identify datasets the
    same way. Only tracking parameters are dropped, and the rest are sorted so that two
    orderings of the same request agree.
    """
    parts = urlsplit((url or "").strip().lower())
    host = normalise(parts.netloc)
    path = re.sub(r"/(index|default)\.(html?|php|aspx?)$", "", parts.path.rstrip("/"))
    query = "&".join(sorted(
        q for q in parts.query.split("&")
        if q and not TRACKING.match(q.split("=")[0])))
    return urlunsplit(("", host, path, query, "")).lstrip("/")


# A path that names an organisation or a section, never a particular dataset.
GENERIC_PATH = re.compile(
    r"^(about|about-us|aboutus|index|home|main|default|welcome|data|datasets|dataset"
    r"|download|downloads|en|us|start|overview|info)$")


def primary_url(sources):
    """The one URL that identifies a dataset, or "" if none of them does.

    Only the FIRST link counts. DiP links the dataset and then whatever gives it context --
    the project's homepage, an about page, a related tool -- and treating every link as an
    identity claim merged five unrelated entries into one record because each happened to
    mention gdeltproject.org. Identity is the thing the entry is about, which is the link
    it leads with.

    A bare homepage is refused even in first position: `cummings.ee/` names a project, and
    two entries about different corpora from the same project are two datasets.
    """
    for s in sources[:1]:
        c = canonical_url(s.get("url", ""))
        if not c:
            continue
        rest = c.partition("/")[2]
        if "?" in c:                       # a query string names a resource
            return c
        segments = [x for x in rest.split("/") if x]
        if not segments:
            return ""                      # bare host
        if len(segments) == 1 and GENERIC_PATH.match(segments[0]):
            return ""
        return c
    return ""


class Matcher:
    """Dataset-level lookup, kept up to date as records are written.

    Two indexes rather than a scan: the archive has ~2,000 rows and the catalogue already
    holds hundreds of records, and re-scanning everything per row is minutes of quadratic
    work for an answer two dicts give immediately. Records created during the run are
    added as they are written, so a dataset DiP featured twice is found the second time.
    """

    def __init__(self, records):
        self.by_url, self.by_title = {}, {}
        for rec in records:
            self.add(rec)

    def add(self, rec):
        key = primary_url(rec.get("sources", []))
        if key:
            self.by_url.setdefault(key, rec)
        key = title_key(rec.get("title", ""))
        if key:
            self.by_title.setdefault(key, []).append(rec)

    def find(self, urls, title):
        key = primary_url([{"url": u} for u in urls])
        if key and key in self.by_url:
            return self.by_url[key], "same URL"
        mine = {registrable(u) for u in urls} - PLATFORM_HOSTS
        for rec in self.by_title.get(title_key(title), []):
            # A title alone is not enough -- "Air quality" is a title several publishers
            # would use -- so the publisher has to agree too.
            hosts = {registrable(s.get("url", "")) for s in rec.get("sources", [])}
            if (hosts & mine) - PLATFORM_HOSTS:
                return rec, "same title and publisher"
        return None, ""


def mark_leads(edition_positions):
    """Tell the lead queue which DiP entries are now dataset records.

    `catalogued` in leads.json means something specific -- somebody researched the endpoint
    and wrote a source record with working probes -- and that is NOT what happened here.
    These entries became browsable dataset records, which leaves the source-layer question
    entirely open. So they get their own state. Without it the queue reports 1,900 leads
    waiting that nobody needs to look at again for this purpose, and a queue that lies
    stops being read.
    """
    path = ROOT / "leads.json"
    if not path.exists():
        return 0
    db = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for edition, position in edition_positions:
        lid = "dip:%s-%s" % (edition, position)
        lead = db.get("leads", {}).get(lid)
        if lead and lead.get("state") == "new":
            lead["state"] = "ingested"
            n += 1
    if n:
        path.write_text(json.dumps(db, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                        encoding="utf-8")
    return n


def build(refresh=False, limit=None):
    rows = list(csv.DictReader(io.StringIO(fetch_csv(refresh))))
    OUT.mkdir(exist_ok=True)
    existing = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(OUT.glob("*.json"))]
    by_id = {r["id"]: r for r in existing}
    matcher = Matcher([r for r in existing])
    today = date.today().isoformat()

    written = merged = skipped = 0
    merge_reasons = {}
    ingested = []
    for row in rows[:limit] if limit else rows:
        edition = (row.get("edition") or "").strip()
        position = (row.get("position") or "").strip()
        if not edition or not position:
            skipped += 1
            continue
        slug = edition.replace(".", "-")
        rid = "dip-%s-%s" % (slug, position)
        title = clean_title(row.get("headline"))
        links = [l for l in (row.get("links") or "").splitlines() if l.strip()]
        sources, articles = split_links(links)
        if not title or not sources:
            skipped += 1                        # nothing to identify or nowhere to go
            continue

        found = {"aggregation": "data-is-plural", "date": slug,
                 "year": int(edition[:4]), "url": ARCHIVE % slug}

        # Already held? Record a sighting on that record; never add a second record for
        # the same dataset. Sightings are keyed by (aggregation, date), not by aggregation
        # alone -- DiP re-features a dataset years later, and that is a second sighting,
        # not a duplicate to drop on the floor.
        target, why = matcher.find([s["url"] for s in sources], title)
        if target is not None and target.get("id") != rid:
            seen = {(f.get("aggregation"), f.get("date")) for f in target.get("found_in", [])}
            if (found["aggregation"], found["date"]) not in seen:
                target["found_in"].append(found)
                (OUT / ("%s.json" % target["id"])).write_text(
                    json.dumps(target, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                merged += 1
                merge_reasons[why] = merge_reasons.get(why, 0) + 1
            ingested.append((edition, position))
            continue

        rec = {
            "id": rid,
            "title": title,
            "hook": quote(row.get("text")),
            "hook_source": "publisher",
            "questions": [],
            "subjects": [], "provider_type": "", "geography": "",
            "sources": sources,
            "articles": articles,
            "tables": [],                       # DiP describes datasets, not their files
            "extra_files": 0,
            "found_in": [found],
            "added": today,
        }
        path = OUT / ("%s.json" % rid)
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            for k in ("subjects", "provider", "provider_type", "geography", "notes", "added",
                      "hook_source", "questions_source"):
                if old.get(k):
                    rec[k] = old[k]
            if old.get("hook_source") == "manual" and old.get("hook"):
                rec["hook"] = old["hook"]
            if old.get("questions_source") in ("manual", "generated") and old.get("questions"):
                rec["questions"] = old["questions"]
            # A record already here may have picked up other sightings, including further
            # ones from this same aggregation -- DiP re-features a dataset years later.
            # Keyed by (aggregation, date) to match the merge rule: comparing aggregation
            # alone dropped the second DiP sighting on every rewrite, which the merge pass
            # then re-added, so the file churned on every run and nothing was ever stable.
            seen = {(f.get("aggregation"), f.get("date")) for f in rec["found_in"]}
            for f in old.get("found_in", []):
                if (f.get("aggregation"), f.get("date")) not in seen:
                    rec["found_in"].append(f)
            rec["found_in"].sort(key=lambda f: (f.get("date") or "", f.get("aggregation")))
        if not rec["questions"]:
            rec.pop("questions")
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        matcher.add(rec)                        # findable by the rest of this run
        by_id[rid] = rec
        ingested.append((edition, position))
        written += 1

    print("%d records written, %d merged into an existing record, %d rows skipped"
          % (written, merged, skipped))
    for why, n in sorted(merge_reasons.items(), key=lambda kv: -kv[1]):
        print("   merged on %s: %d" % (why, n))
    marked = mark_leads(ingested)
    if marked:
        print("%d lead(s) marked `ingested` -- in the dataset layer; the source layer "
              "may still want them" % marked)
    print("Now: python3 src/classify.py && python3 src/quality.py --sweep "
          "&& python3 src/build_site.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    build(a.refresh, a.limit)
