#!/usr/bin/env python3
"""Work out which datasets could actually be joined together, and on what.

A catalogue tells you what exists. The question one step further on -- "what could I
make with this?" -- is usually answered by putting two datasets next to each other, and
that is exactly the thing a list of records cannot show you. This derives it.

    python3 src/joins.py                 # rebuild joins.json
    python3 src/joins.py --explain tt-2024-01-09
    python3 src/joins.py --sample 12     # a spread of what it found, for eyeballing

Three ideas do the work.

**A shared time column is not a discovery.** `year` appears in 129 records and `date` in
60; a graph built on those says everything joins to everything, which is the same as
saying nothing. A join needs an *entity* key -- a country, a state, a county, a species,
a coordinate -- and time is only useful afterwards, for checking the two overlap.

**The same key is spelled a dozen ways.** country / country_name / country_code / iso3 /
iso3c / nation / cty all name one join key, and matching column strings literally finds
none of it. Families are matched by pattern, so the spelling stops mattering.

**Joining two datasets about the same thing tells you nothing.** Two country-year
economic indicators join perfectly and produce a third economic indicator. The pairs
worth surfacing share a key and differ in subject, so the score rewards distance.

A caveat the output states honestly: only 360 of the catalogue's records carry column
names -- the ones that came from TidyTuesday, which lists them. For everything else the
key is inferred from the title and the curator's description, which is a weaker claim,
and every edge says which kind of evidence it rests on.
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"
OUT = ROOT / "joins.json"

# (family, kind, specificity, column pattern, prose pattern)
#
# `kind` is the distinction that makes this usable, and getting it wrong produced a graph
# of confident nonsense: "Bats in caves joins Coffee Ratings on species".
#
#   place  -- a universal code space. Every domain publishes data by county, by country,
#             by coordinate, so a cross-domain join is exactly the point and the values
#             really do line up.
#   entity -- nominally shared, practically disjoint. Both bats and coffee have a species
#             column and the two species sets never meet; both a fragrance dataset and a
#             ramen dataset have a brand. These join only inside one domain, so an edge is
#             kept only when the subjects agree.
#
# `person` and `company` were dropped outright: matching on a name is not matching on a
# key, there is no shared identifier space behind either, and between them they produced
# the worst edges in the first run ("More coronavirus data joins Women's World Cup").
#
# Specificity is how much the key narrows the world. Two datasets keyed by county are
# describing nearly the same rows as each other; two keyed by country share 200 rows and
# a join is still a real piece of work. Patterns are anchored deliberately -- an early
# draft matched `.*gauge.*` for stream gauges and collected a knitting dataset's
# `yarn_weight_knit_gauge`, and `.*imdb.*` for identifiers and collected `imdb_rating`.
ENTITY_KEYS = [
    ("county", "place", 5,
     r"^(fips|fips_?code|county|county_?name|county_?fips|county_?code|geoid|countyfp)$",
     r"\b(counties|county|county-level|by county|fips)\b"),
    ("postcode", "place", 5,
     r"^(zip|zips|zip_?code|zip_?codes|postcode|post_?code|postal_?code|zcta)$",
     r"\b(zip ?codes?|postcodes?|postal codes?|zcta)\b"),
    ("coordinate", "place", 4,
     r"^(lat|latitude|lon|lng|long|longitude|decimal_?latitude|decimal_?longitude)$",
     r"\b(latitude|longitude|coordinates|geocoded|point locations|geolocated)\b"),
    ("state or province", "place", 3,
     r"^(state|province|state_?name|province_?name|state_?abb|state_?abbr|state_?code|state_?po|us_?state|st)$",
     r"\b(states?|provinces?|state-level|by state|statewide|all 50 states)\b"),
    ("city", "place", 3,
     r"^(city|city_?name|municipality|town|place_?name|msa|metro|metro_?area|cbsa)$",
     r"\b(cities|city-level|municipalit|metro areas?|metropolitan)\b"),
    ("country", "place", 2,
     r"^(country|countries|country_?name|country_?code|iso|iso2|iso3|iso_?a2|iso_?a3|"
     r"iso2c|iso3c|nation|nation_?name|cty|cty_?name|economy)$",
     r"\b(countries|country-level|international|worldwide|global|nations|per country|"
     r"cross-national)\b"),
    ("species", "entity", 4,
     r"^(species|species_?name|scientific_?name|scientificname|taxon|taxon_?name|genus|"
     r"binomial|gbif_?id)$",
     r"\b(species|taxa|taxonomic|genus|biodiversity|specimens?)\b"),
    ("airport", "entity", 4,
     r"^(airport|airport_?code|origin|dest|destination|iata|icao|airport_?id)$",
     r"\b(airports?|iata|icao|flights?)\b"),
    ("monitoring station", "entity", 4,
     r"^(station|station_?id|station_?name|site_?id|site_?no|site_?number|gauge_?id|"
     r"sensor_?id|monitor_?id)$",
     r"\b(monitoring stations?|weather stations?|gauges?|sensors?|buoys?)\b"),
    ("publication", "entity", 4,
     r"^(doi|isbn|pmid|issn|paper_?id|article_?id|work_?id)$",
     r"\b(dois?|papers|publications|articles|journals|preprints|citations)\b"),
]

# Time keys never justify an edge on their own; they confirm two datasets could line up.
TIME_KEY = (r"^(year|yr|date|month|day|week|season|datetime|timestamp|time|period|"
            r"fiscal_?year|quarter)$",
            r"\b(annual|yearly|monthly|daily|hourly|weekly|time series|since \d{4}|"
            r"\d{4}[-–]\d{2,4})\b")

# Geographies that cannot be joined to each other. "global" joins anything; two named
# regions that differ do not, and an edge claiming otherwise is just wrong.
GLOBALISH = {"", "global"}

# How hard to push back on generically-joinable records. Tuned by eye: at 0 a
# handful of hubs are everyone's top suggestion, and much above 1 the graph
# prefers obscure records purely for being obscure.
HUB_PENALTY = 0.7

# How many times one record may be offered as somebody else's join candidate.
MAX_APPEARANCES = 12


def column_forms(col):
    """The whole column name, plus each of its underscore-delimited parts.

    Keys arrive with qualifiers attached -- `birth_country`, `home_state`, `birth_city` --
    and an anchored pattern matches none of them, which is why the NHL birth-dates record
    reported no keys at all while carrying three. Matching parts as well as the whole is
    enough, and stays tighter than a substring test: `imdb_rating` yields {imdb, rating}
    and still matches nothing.
    """
    col = col.lower().strip()
    parts = [p for p in re.split(r"[^a-z0-9]+", col) if p]
    return [col] + parts


def keys_from_columns(rec):
    cols = {c.lower().strip() for t in rec.get("tables", []) for c in t.get("columns", [])}
    if not cols:
        return set(), False
    forms = {f for c in cols for f in column_forms(c)}
    found = {fam for fam, _, _, pat, _ in ENTITY_KEYS
             if any(re.match(pat, f) for f in forms)}
    has_time = any(re.match(TIME_KEY[0], f) for f in forms)
    return found, has_time


def keys_from_prose(rec):
    """Weaker evidence, but it is the only evidence for 85% of the catalogue."""
    text = " ".join([rec.get("title", ""), rec.get("hook", ""),
                     " ".join(rec.get("questions", []) or [])]).lower()
    found = {fam for fam, _, _, _, pat in ENTITY_KEYS if re.search(pat, text)}
    return found, bool(re.search(TIME_KEY[1], text))


SPECIFICITY = {fam: spec for fam, _, spec, _, _ in ENTITY_KEYS}
KIND = {fam: kind for fam, kind, _, _, _ in ENTITY_KEYS}


def profile(rec):
    cols, col_time = keys_from_columns(rec)
    prose, prose_time = keys_from_prose(rec)
    return {
        "id": rec["id"],
        "known": cols,                       # from column names: the strong claim
        "inferred": prose - cols,            # from prose only
        "keys": cols | prose,
        "time": col_time or prose_time,
        "subjects": set(rec.get("subjects") or []),
        "geography": (rec.get("geography") or "").strip(),
        "title": rec.get("title", ""),
    }


def compatible(a, b):
    """Two named, different places cannot be joined. Global joins anything."""
    ga, gb = a["geography"].lower(), b["geography"].lower()
    if ga in GLOBALISH or gb in GLOBALISH:
        return True
    return ga == gb


def score_pair(a, b):
    shared = a["keys"] & b["keys"]
    if not shared or not compatible(a, b):
        return None
    # sorted() first: max() over a set breaks ties in whatever order the set iterates,
    # which varies with the hash seed and made the graph differ between identical runs
    best = max(sorted(shared), key=lambda f: SPECIFICITY[f])
    score = SPECIFICITY[best]

    subs_a, subs_b = a["subjects"], b["subjects"]
    overlap = (len(subs_a & subs_b) / len(subs_a | subs_b)) if (subs_a and subs_b) else 0.0

    if KIND[best] == "entity":
        # An entity key only joins inside one domain: bats and coffee both have a species
        # column and their species never meet. Require the subjects to agree, and give no
        # credit for distance -- distance is precisely what makes these edges wrong.
        if not overlap:
            return None
        score += overlap
    else:
        # A place key is a universal code space, so distance is the whole point: air
        # quality by county x eviction filings by county is a project, while two economic
        # indicators by country are a rounding error.
        score += 2 * (1 - overlap)

    # How good is the evidence for that key on both sides? A column named `fips` is a
    # fact; "county" appearing in a sentence is a guess, and the gap should be wide
    # enough that a guess never outranks a fact.
    if best in a["known"] and best in b["known"]:
        basis, score = "columns", score + 3
    elif best in a["known"] or best in b["known"]:
        basis, score = "mixed", score + 1.5
    else:
        basis = "inferred"
    if a["time"] and b["time"]:
        score += 1
    if len(shared) > 1:
        score += min(2, len(shared) - 1)
    return {"key": best, "shared": sorted(shared), "basis": basis, "score": round(score, 2)}


def build(top_k=6):
    records = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(DATASETS.glob("*.json"))]
    profiles = [profile(r) for r in records]
    by_key = defaultdict(list)
    for p in profiles:
        for fam in p["keys"]:
            by_key[fam].append(p)

    # Only records sharing a key family are ever compared -- there is no point scoring
    # 2.8 million pairs to discard almost all of them.
    edges = defaultdict(list)
    seen_pairs = set()
    # Families in a fixed order for the same reason: whichever family reaches a pair
    # first is the one that scores it, so set-iteration order would decide the answer.
    for fam in sorted(by_key):
        group = by_key[fam]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pair = (a["id"], b["id"])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                res = score_pair(a, b)
                if not res:
                    continue
                edges[a["id"]].append(dict(res, other=b["id"], title=b["title"]))
                edges[b["id"]].append(dict(res, other=a["id"], title=a["title"]))

    # A record that could join with 1,800 others is not a match, it is a hub. Without this
    # one dataset of chart-design mistakes -- which happens to carry a country column and
    # an unusual subject, so it scored maximum distance against everything -- was the top
    # suggestion for half the catalogue. Penalising a partner by how joinable it is in
    # general is the same idea as weighting a search term by how rare it is.
    degree = {rid: len(es) for rid, es in edges.items()}
    for rid in sorted(edges):
        es = edges[rid]
        for e in es:
            e["score"] = round(e["score"] - HUB_PENALTY * math.log2(1 + degree.get(e["other"], 1)), 2)
        es.sort(key=lambda e: (-e["score"], e["other"]))

    # The penalty alone still let the handful of genuinely universal records -- the Big Mac
    # Index really is joinable with anything that has a country column -- take four of every
    # twelve suggestions. So slots are filled in global score order with a quota per partner:
    # the strongest claim on a popular record wins it, and everyone after that gets shown
    # something they would not have seen otherwise. A record with no alternative still keeps
    # its best candidate, because a repetitive suggestion beats an empty panel.
    out = {rid: [] for rid in sorted(edges)}
    used = defaultdict(int)
    ranked = sorted(((e["score"], rid, e) for rid, es in edges.items() for e in es),
                    key=lambda t: (-t[0], t[1], t[2]["other"]))
    for _, rid, e in ranked:
        if len(out[rid]) >= top_k or used[e["other"]] >= MAX_APPEARANCES:
            continue
        out[rid].append(e)
        used[e["other"]] += 1
    for rid in sorted(edges):
        if not out[rid]:
            out[rid] = edges[rid][:1]

    payload = {
        "built_from": "%d records" % len(records),
        "note": ("An edge means the two records appear to share an entity key, so a join is "
                 "mechanically possible. basis=columns means both sides declare the key as a "
                 "column; inferred means it was read out of the description and is a guess."),
        "top_k": top_k,
        "joins": out,
    }
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    strong = sum(1 for es in out.values() for e in es if e["basis"] == "columns")
    print("%d records with at least one join candidate (of %d)" % (len(out), len(records)))
    print("%d edges, %d of them evidenced by column names on both sides"
          % (sum(len(v) for v in out.values()), strong))
    fams = defaultdict(int)
    for es in out.values():
        for e in es:
            fams[e["key"]] += 1
    print("by key: " + ", ".join("%s %d" % (k, v) for k, v in
                                 sorted(fams.items(), key=lambda kv: -kv[1])))
    return payload


def explain(rid):
    payload = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"joins": {}}
    rec = DATASETS / ("%s.json" % rid)
    if not rec.exists():
        print("no record %r" % rid, file=sys.stderr)
        return 1
    r = json.loads(rec.read_text(encoding="utf-8"))
    p = profile(r)
    print("%s  %s" % (rid, r.get("title", "")))
    print("  keys from columns: %s" % (", ".join(sorted(p["known"])) or "-"))
    print("  keys from prose:   %s" % (", ".join(sorted(p["inferred"])) or "-"))
    print("  geography: %s   time key: %s" % (p["geography"] or "unspecified", p["time"]))
    print("\n  could be joined with:")
    for e in payload["joins"].get(rid, []):
        print("    %-5.1f %-9s on %-19s %s" % (e["score"], e["basis"], e["key"], e["title"][:52]))
        print("           %s" % e["other"])
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--explain", metavar="ID")
    ap.add_argument("--sample", type=int, metavar="N")
    ap.add_argument("--top-k", type=int, default=6)
    a = ap.parse_args()
    if a.explain:
        sys.exit(explain(a.explain))
    payload = build(a.top_k)
    if a.sample:
        import random
        random.seed(5)
        print("\nA spread of what it found:\n")
        for rid in random.sample(list(payload["joins"]), min(a.sample, len(payload["joins"]))):
            e = payload["joins"][rid][0]
            rec = json.loads((DATASETS / ("%s.json" % rid)).read_text(encoding="utf-8"))
            print("  %s" % rec.get("title", rid)[:58])
            print("    + %-56s  %s on %s" % (e["title"][:56], e["basis"], e["key"]))
