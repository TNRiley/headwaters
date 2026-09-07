#!/usr/bin/env python3
"""Answer "do we already know about this?" -- the one question every other script asks.

Three places already normalise a host and none of them agreed: classify.py derives a
provider key, build_site.py joins datasets to sources, harvest.py auto-marks a lead
whose host is catalogued. This module is the single implementation, so a change to the
rule changes all of them at once.

It exists mainly for what comes next. Ingesting a second aggregation means deciding,
for every incoming record, whether it is new or a second sighting of one already held
-- a dataset in two aggregations must be one record with two `found_in` entries, never
two records. That is this function, run several thousand times, so it is worth having
it tested at 40-source scale first.

    from match import Index
    idx = Index.load(ROOT)
    idx.lookup("https://api.open-meteo.com/v1/forecast")   -> Hit(kind='source', id='open-meteo', ...)

Stdlib only, like everything here.
"""
import json
import re
import unicodedata
from collections import namedtuple
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

# Subdomains that name a service, not a publisher: api.nhle.com and nhle.com are one
# organisation, and a record filed under either should answer for both.
SERVICE_PREFIX = re.compile(r"^(www|api|api2|data|raw|files|download|static|cdn|docs|dev)\.")

# Hosts that identify a platform rather than a publisher. A GitHub URL tells you where
# something is parked, not who made it, so these never become a provider key.
PLATFORM_HOSTS = {
    "github.com", "raw.githubusercontent.com", "githubusercontent.com", "gist.github.com",
    "kaggle.com", "figshare.com", "zenodo.org", "dropbox.com", "drive.google.com",
    "docs.google.com", "sites.google.com", "s3.amazonaws.com", "amazonaws.com",
    "huggingface.co", "gitlab.com", "bitbucket.org", "osf.io", "archive.org",
}

# Multi-part public suffixes we actually meet. Not a full PSL -- the full list is 15,000
# lines and this catalogue is mostly .com/.org/.gov -- but without these, co.uk collapses
# every British publisher into one key.
MULTI_SUFFIX = {
    "co.uk", "ac.uk", "gov.uk", "org.uk", "com.au", "gov.au", "edu.au", "co.nz",
    "co.jp", "com.br", "gov.br", "co.in", "gov.in", "com.mx", "co.za", "com.sg",
}

Hit = namedtuple("Hit", "kind id name why")


def host_of(url_or_host):
    """The bare host, lowercased, with any scheme, port, userinfo or path removed."""
    s = (url_or_host or "").strip().lower()
    if not s:
        return ""
    if "//" not in s and not s.startswith("http"):
        s = "//" + s                     # bare host: give urlsplit something to bite on
    host = urlsplit(s).netloc or urlsplit(s).path
    host = host.split("@")[-1].split(":")[0].strip("/")
    return host


def normalise(url_or_host):
    """Host reduced to the thing worth comparing: service prefixes stripped.

    Kept deliberately shallow -- one prefix, not a loop -- because api.data.gov and
    data.gov really are different services, and collapsing everything to the
    registrable domain would merge them.

    A prefix is only stripped when something that still looks like a domain is left.
    `data.gov.uk` is not a service called `data` on `gov.uk`; `gov.uk` is a public
    suffix, and stripping down to it merges every UK government publisher into one key.
    """
    host = host_of(url_or_host)
    stripped = SERVICE_PREFIX.sub("", host, count=1)
    if stripped != host:
        parts = stripped.split(".")
        if len(parts) < 2 or stripped in MULTI_SUFFIX:
            return host
    return stripped


def registrable(url_or_host):
    """The organisation-level domain: nhle.com from api.stats.nhle.com."""
    host = normalise(url_or_host)
    parts = host.split(".")
    if len(parts) < 3:
        return host
    if ".".join(parts[-2:]) in MULTI_SUFFIX:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def slug(text):
    """A comparable form of a title: lowercase, unaccented, alphanumerics only.

    Titles are the fallback key when there is no usable host, which is most of the
    time for a dataset ("Weather Forecast Capstone Project" is a provider name, not a
    domain). Punctuation and spacing vary wildly between aggregations; the letters do not.
    """
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text)


# Words that carry no distinguishing weight in a dataset title. Dropped before building
# the loose title key so "The Bob Ross Paintings Dataset" and "Bob Ross Paintings" match.
STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "by", "from", "with",
    "data", "dataset", "datasets", "database", "archive", "statistics", "stats",
}


def title_key(text):
    """Loose title key: distinguishing words only, alphabetised, so word order stops mattering."""
    words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", (text or "").lower()))
    keep = sorted({w for w in words if w not in STOPWORDS and len(w) > 1})
    return " ".join(keep)


class Index:
    """Every identifier the catalogue holds, keyed the several ways a lookup arrives."""

    def __init__(self, sources, datasets, leads):
        self.sources = sources
        self.datasets = datasets
        self.leads = leads
        self.by_host = {}          # normalised host   -> Hit
        self.by_domain = {}        # registrable domain -> Hit
        self.by_title = {}         # loose title key    -> Hit
        self.by_id = {}            # record id          -> Hit
        self._build()

    @classmethod
    def load(cls, root=ROOT):
        def read(directory):
            d = Path(root) / directory
            return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))] \
                if d.is_dir() else []
        leads_path = Path(root) / "leads.json"
        leads = json.loads(leads_path.read_text(encoding="utf-8")).get("leads", {}) \
            if leads_path.exists() else {}
        return cls(read("sources"), read("datasets"), leads)

    def _put(self, table, key, hit):
        # First writer wins. Sources are indexed before datasets and datasets before
        # leads, so the most authoritative record answers for a shared host.
        if key and key not in table:
            table[key] = hit

    def _build(self):
        for s in self.sources:
            hit = Hit("source", s["id"], s.get("name", ""), "")
            self.by_id[s["id"]] = hit
            urls = [s.get("homepage", "")] + [p.get("url", "") for p in s.get("probes", [])]
            for u in urls:
                host = normalise(u)
                if not host:
                    continue
                self._put(self.by_host, host, hit)
                if host not in PLATFORM_HOSTS:
                    self._put(self.by_domain, registrable(u), hit)
            self._put(self.by_title, title_key(s.get("name", "")), hit)

        for d in self.datasets:
            hit = Hit("dataset", d["id"], d.get("title", ""), "")
            self.by_id[d["id"]] = hit
            self._put(self.by_title, title_key(d.get("title", "")), hit)
            host = normalise((d.get("provider") or {}).get("host") or "")
            if host and "." in host:
                self._put(self.by_host, host, hit)
                if host not in PLATFORM_HOSTS:
                    self._put(self.by_domain, registrable(host), hit)
            for src in d.get("sources", []):
                host = normalise(src.get("url", ""))
                if host and host not in PLATFORM_HOSTS:
                    self._put(self.by_host, host, hit)

        for lid, lead in self.leads.items():
            hit = Hit("lead", lid, lead.get("title", ""), lead.get("state", ""))
            self.by_id[lid] = hit
            self._put(self.by_title, title_key(lead.get("title", "")), hit)
            for u in lead.get("links", []):
                host = normalise(u)
                if host and host not in PLATFORM_HOSTS:
                    self._put(self.by_host, host, hit)

    def lookup(self, url_or_title, title=None):
        """Best single answer to "do we have this already?", or None.

        Tried in descending order of confidence: exact host, then organisation domain,
        then title. A domain match is a weaker claim than a host match and says so in
        `why`, because api.census.gov and www.census.gov being the same publisher does
        not make them the same endpoint.
        """
        host = normalise(url_or_title)
        if host and "." in host:
            hit = self.by_host.get(host)
            if hit:
                return hit._replace(why="host %s" % host)
            if host not in PLATFORM_HOSTS:
                dom = registrable(host)
                hit = self.by_domain.get(dom)
                if hit:
                    return hit._replace(why="same publisher (%s), different endpoint" % dom)
        for candidate in (title, None if host and "." in host else url_or_title):
            key = title_key(candidate)
            if key:
                hit = self.by_title.get(key)
                if hit:
                    return hit._replace(why="title %r" % candidate)
        return None

    def counts(self):
        return {"sources": len(self.sources), "datasets": len(self.datasets),
                "leads": len(self.leads),
                "leads_new": sum(1 for v in self.leads.values() if v.get("state") == "new")}


def _selftest():
    """Run the rules against the cases that actually broke something. `python3 src/match.py`"""
    cases = [
        (normalise("https://api.open-meteo.com/v1/forecast"), "open-meteo.com"),
        (normalise("www.census.gov"), "census.gov"),
        (normalise("https://api.data.gov/x"), "data.gov"),          # one prefix only
        (registrable("https://api.stats.nhle.com/x"), "nhle.com"),
        (registrable("https://data.gov.uk/thing"), "data.gov.uk"),  # multi-part suffix
        (host_of("https://user@example.org:8443/p"), "example.org"),
        (title_key("The Bob Ross Paintings Dataset"), title_key("Bob Ross paintings")),
        (slug("Café Ratings"), "caferatings"),
    ]
    bad = [(i, got, want) for i, (got, want) in enumerate(cases) if got != want]
    for i, got, want in bad:
        print("case %d: got %r, wanted %r" % (i, got, want))
    idx = Index.load()
    print(json.dumps(idx.counts()))
    for probe in ["https://api.open-meteo.com/v1/forecast", "https://www.census.gov/data",
                  "https://example.invalid/nothing"]:
        print("%-44s -> %s" % (probe, idx.lookup(probe)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
