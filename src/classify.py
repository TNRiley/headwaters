#!/usr/bin/env python3
"""Assign subjects, provider type and geography to every dataset record.

Rules, not one-off judgements, so a week added next year classifies itself and so
the reasoning stays inspectable and arguable. Anything the rules cannot place is
printed at the end for a human to either fix in OVERRIDES or teach a new rule.

    python3 src/classify.py            # fill empty fields
    python3 src/classify.py --force    # recompute everything
    python3 src/classify.py --report   # show counts and the unclassified list
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"

# ---------------------------------------------------------------- subjects
# Weighted, not a flat text match. Every TidyTuesday readme mentions R, GitHub and
# the word "tidytuesday", so scoring a single blob of text makes those three
# subjects swallow the whole corpus. Title and source name carry the signal;
# the hook is a weak tiebreak; boilerplate is stripped before any of it is read.
#
# title_only rules fire on the title alone - they describe what the week IS,
# not what it happens to mention.
SUBJECT_RULES = [
 ("sports & games", False, r"\b(nfl|nhl|nba|ncaa|mlb|football|soccer|rugby|cricket|tennis|golf|olympic|paralympic|athlete|marathon|powerlifting|volleyball|basketball|hockey|baseball|formula 1|grand prix|chess|board ?game|video ?game|esport|mario kart|dungeons ?(&|and) ?dragons|d&d|world cup|premier league|euroleague|march madness|ufc|wrestling|mountaineer|munro|tour de france|fide|lichess|steam|pokemon|marble race|bakeoff|ferris wheel|big pumpkin|powerlift|survivor)\b"),
 ("film & television", False, r"\b(imdb|movie|film|cinema|tv show|television|episode|netflix|hollywood|oscar|emmy|bechdel|sitcom|bake ?off|chopped|american idol|power rangers|pixar|doctor who|simpsons|stranger things|bob'?s burgers|the office|avatar|x-?men|scooby|star trek|star wars|hot ones|horror movie|monster movie|holiday movie|summer movie)\b"),
 ("music", False, r"\b(music|song|album|billboard|spotify|lyric|rap\b|hip.?hop|eurovision|rolling stone|beyonce|taylor swift|spice girls|country music|hot 100)\b"),
 ("books & language", False, r"\b(book|novel|literature|literary|gutenberg|shakespeare|sherlock|bestseller|poetry|language|linguistic|glottolog|crossword|encyclical|manuscript|library|prose|dialogue)\b"),
 ("art & culture", False, r"\b(art\b|artist|museum|painting|gallery|tate|sculpture|du ?bois|heritage|castle|monument|historical marker|craft|knit|ravelry|lego|fragrance|perfume|parfumo|makeup shade|world'?s fair|exposition|architecture)\b"),
 ("health & medicine", False, r"\b(health|medicine|medical|disease|cancer|patient|hospital|vaccin|measles|tuberculosis|malaria|mortality|traumatic|scurvy|pharma|medicare|medicaid|clinical|nurse|mental health|reproductive|epidemic|lead concentration|water insecurity|drug development|care by us state)\b"),
 ("environment & climate", False, r"\b(climate|weather|temperature|carbon|emission|co2|greenhouse|drought|wildfire|\bfires?\b|flood|hurricane|tornado|volcano|earthquake|seismic|pollution|plastic|waste|deforest|renewable|solar|wind (farm|turbine|utilit)|recycl|repair cafe|ocean|sea temperature|water quality|meteorolog|energy)\b"),
 ("animals & nature", False, r"\b(animal|bird|penguin|\bdogs?\b|\bcats?\b|pet\b|lemur|spider|numbat|caribou|whale|frog|fish|seafood|\bbees?\b|bee colony|shelter|wildlife|species|plant|\btrees?\b|palm|crop|garden|tortoise|salmon|crane|seabird|squirrel|breed|feeder ?watch|invasive|extinct|avonet|ecotourism|cetacean|numbat|horse)\b"),
 ("space & astronomy", False, r"\b(astronom|meteorite|astronaut|eclipse|galax|satellite|space launch|orbit|\bapod\b|telescope|launched into space|spectroscopic)\b"),
 ("transport & infrastructure", False, r"\b(transit|transport|traffic|flight|airline|airport|aviation|train|railway|bridge|highway|roundabout|elevator|bikeshare|bike (traffic|commute)|commut|shipping|shipwreck|wreck inventory|broadband|fuel station|car crash|passport)\b"),
 ("government & politics", False, r"\b(election|voter|polling place|congress|parliament|senate|president|democracy|dictator|freedom index|policing|police|incarcerat|prison|court|judges?|copyright|tariff|customs|border|grant|treaty|united nations|un votes|government|federal|fiscal sponsor|bureaucracy|gdpr)\b"),
 ("economy & work", False, r"\b(econom|gdp|income|wealth|salar|wage|\bpay\b|earning|employ|labor|labour|union member|stock|price|inflation|retail sales|trade|industrial production|business|compan|\bceo\b|mortgage|student loan|budget|spending|investment|big mac|productivity|tariff)\b"),
 ("education", False, r"\b(education|school|college|universit|student|tuition|degree|\bphd\b|graduat|teacher|enrollment|hbcu|pell grant|literacy|attainment|ielts|olympiad|campus|childcare)\b"),
 ("food & drink", False, r"\b(food|beer|wine|coffee|cocktail|ramen|pizza|chocolate|cacao|cheese|honey|dairy|\beggs?\b|vegetable|recipe|restaurant|nutrition|calorie|starbucks|james beard|taste test|brewer|agricultur|farmer|farming|farmland|crop yield|donut|allrecipes|edible)\b"),
 ("technology & software", False, r"\b(programming language|source code|stack overflow|api specs|apis\.guru|web page metrics|algorithm|machine learning|gpt|password|time ?zone|open source|product hunt|moore'?s law|technology adoption|landline|telephone subscription|spam e-?mail|chess engine|digital publication)\b"),
 ("society & demographics", False, r"\b(census|population|demograph|\bbirths?\b|baby names?|marriage|household|migration|refugee|immigra|gender|racial|ethnic|lgbtq|pride|religio|inequality|poverty|holiday|life expectancy|human day|parenting leave|twinned cities|populated places|salary survey|diversity)\b"),
 ("oddities & curiosities", False, r"\b(ufo|bigfoot|haunted|groundhog|squirrel census|near-?death|paranormal|snowman|digits of pi|leap day|urban legend|snopes|horror legend|exploding)\b"),
 ("the r & tidytuesday community", True, r"\b(tidytuesday|r4ds|rstats|posit::?conf|user! ?20|black ?in ?data|r-?ladies|datasaurus|cran|shiny|vignette|funspotr|ttmeta|du bois (visualization|challenge)|making maps with r|replicating plots|package structure|r package)\b"),
]

# ------------------------------------------------------- provider taxonomy
PROVIDER_RULES = [
 ("government",      r"(\.gov\b|\.gov\.|\.gc\.ca|\.govt\.|europa\.eu|\.gov\.uk|statcan|census\.gov|ons\.gov|eurostat|\bbls\b|\bbea\b|usda|\bfaa\b|\bcdc\b|\bepa\b|\bnsf\b|usgs|noaa|\bnasa\b|open\.canada|data\.gov|city ?of|cityof|municipal|opendata|open data (philly|toronto)|data\.sfgov|seattle\.gov|london\.gov|nhs|istituto nazionale|veterinary institute|holy see|vatican)"),
 ("intergovernmental", r"(unesco|united nations|\bun\b|world bank|\bwho\b|world health|oecd|imf|eurocontrol|comtrade|ipc\b|fao\b)"),
 ("academic",        r"(\.edu\b|dataverse|zenodo|osf\.io|figshare|doi\.org|sciencedirect|wiley|springer|nature\.com|arxiv|plos|nber|university|institute|et al|vizier|carpentr)"),
 ("journalism",      r"(fivethirtyeight|nytimes|new york times|bbc|economist|buzzfeed|guardian|washington post|wall ?street|wsj|axios|propublica|the pudding|reuters|carbon brief|public integrity|post45)"),
 ("platform",        r"(kaggle|data\.world|github\.com|raw\.githubusercontent|docs\.google|gitlab|huggingface|bit\.ly)"),
 ("reference works", r"(wikipedia|wikidata|wikimedia|imdb|iana|glottolog|isocodes|world factbook|encyclopedia)"),
 ("r package",       r"(\bcran\b|r package|`\w+`|\{[\w.]+\}|package$|pkg\b)"),
 ("company",         r"(\.com\b|inc\.|corporation|starbucks|netflix|spotify|steam|lichess|ravelry|playbill|billboard)"),
 ("nonprofit or society", r"(\.org\b|\.org\.|foundation|society|association|trust\b|charity|council)"),
]

# ------------------------------------------------------------- geography
GEO_RULES = [
 ("United States", r"\b(u\.?s\.?a?\b|united states|american|nfl|nba|ncaa|mlb|census bureau|federal|congress|state[s]?\b|california|texas|new york|chicago|seattle|philly|philadelphia|baltimore|dallas|san francisco|long beach|flint|hollywood|medicare|medicaid|fbi|cdc|usda|epa|nasa|faa)\b"),
 ("United Kingdom", r"\b(uk\b|united kingdom|british|britain|england|english|scotland|scottish|wales|welsh|london|premier league|munro|british library)\b"),
 ("Australia", r"\b(australia|australian|sydney|nsw|numbat|rspca)\b"),
 ("Canada", r"\b(canada|canadian|toronto|ontario|statcan|kenya census)\b"),
 ("Europe", r"\b(europe|european|\beu\b|eurostat|eurovision|erasmus|italian|italy|french|france|germany|german|spain|spanish|norwegian|norway|sweden|swedish|zurich|ireland|irish|vesuvius)\b"),
 ("Africa", r"\b(africa|african|kenya|nigeria|lesotho|basotho|afrisenti|afrilearn)\b"),
 ("Asia", r"\b(asia|china|chinese|india|indian|japan|japanese|qatar|himalaya|nepal|diwali)\b"),
 ("global", r"\b(global|world|worldwide|international|countries|nations|un\b|who\b|unesco|olympic|planet)\b"),
]

# Hand corrections. A rule table gets most of it; these are the ones where the
# words in the title genuinely mislead. Keep the reason with the fix.
OVERRIDES = {
 # Rules place ~90% of the corpus. These are the ones where the title's words
 # genuinely mislead, or where the subject is only obvious if you know the thing.
 "tt-2018-06-19": {"subjects": ["environment & climate", "society & demographics"]},
 "tt-2018-06-26": {"subjects": ["food & drink", "society & demographics"]},
 "tt-2018-07-17": {"subjects": ["health & medicine"]},
 "tt-2018-12-04": {"subjects": ["technology & software", "books & language"]},
 "tt-2019-04-23": {"subjects": ["film & television"]},
 "tt-2019-07-02": {"subjects": ["film & television", "economy & work"]},
 "tt-2019-08-20": {"subjects": ["government & politics", "environment & climate"]},
 "tt-2019-09-03": {"subjects": ["technology & software"]},              # "Moore's Law" is not a law dataset
 "tt-2019-10-15": {"subjects": ["transport & infrastructure", "environment & climate"]},
 "tt-2020-02-11": {"subjects": ["economy & work", "society & demographics"]},
 "tt-2020-10-13": {"subjects": ["the r & tidytuesday community"]},      # datasauRus, a teaching device
 "tt-2020-11-24": {"subjects": ["animals & nature", "sports & games"]},
 "tt-2021-03-02": {"subjects": ["film & television", "sports & games"]},
 "tt-2021-03-30": {"subjects": ["art & culture", "society & demographics"]},   # makeup shades / skin tone
 "tt-2021-04-13": {"subjects": ["government & politics", "society & demographics"]},
 "tt-2021-06-22": {"subjects": ["animals & nature", "society & demographics"]},
 "tt-2021-07-06": {"subjects": ["government & politics", "society & demographics"]},
 "tt-2021-09-28": {"subjects": ["economy & work", "education"]},
 "tt-2021-10-19": {"subjects": ["oddities & curiosities", "food & drink"]},
 "tt-2021-11-02": {"subjects": ["the r & tidytuesday community"]},      # Geocomputation with R
 "tt-2021-11-09": {"subjects": ["the r & tidytuesday community"]},
 "tt-2021-11-16": {"subjects": ["the r & tidytuesday community"]},
 "tt-2022-01-25": {"subjects": ["sports & games"]},
 "tt-2022-02-08": {"subjects": ["society & demographics", "government & politics"]},
 "tt-2022-02-15": {"subjects": ["the r & tidytuesday community", "art & culture"]},
 "tt-2022-03-01": {"subjects": ["transport & infrastructure", "environment & climate"]},
 "tt-2022-03-29": {"subjects": ["sports & games", "education"]},
 "tt-2022-04-05": {"subjects": ["technology & software", "books & language"]},
 "tt-2022-05-10": {"subjects": ["books & language"]},
 "tt-2022-05-31": {"subjects": ["economy & work", "society & demographics"]},
 "tt-2022-06-21": {"subjects": ["art & culture", "society & demographics"]},   # Juneteenth, Du Bois style
 "tt-2022-07-12": {"subjects": ["transport & infrastructure"]},
 "tt-2022-08-09": {"subjects": ["oddities & curiosities", "art & culture"]},
 "tt-2022-09-20": {"subjects": ["environment & climate", "transport & infrastructure"]},
 "tt-2022-09-27": {"subjects": ["art & culture", "economy & work"]},
 "tt-2022-11-08": {"subjects": ["music", "technology & software"]},
 "tt-2022-11-22": {"subjects": ["art & culture"]},
 "tt-2022-12-06": {"subjects": ["transport & infrastructure"]},
 "tt-2023-03-28": {"subjects": ["technology & software", "society & demographics"]},
 "tt-2023-04-18": {"subjects": ["food & drink", "animals & nature"]},
 "tt-2023-06-13": {"subjects": ["food & drink", "society & demographics"]},
 "tt-2023-07-18": {"subjects": ["technology & software"]},              # GPT detectors
 "tt-2024-03-19": {"subjects": ["film & television", "economy & work"]},        # X-Men Mutant Moneyball
 "tt-2024-11-12": {"subjects": ["technology & software", "society & demographics"]},
 "tt-2025-01-21": {"subjects": ["sports & games"]},
 "tt-2025-03-25": {"subjects": ["economy & work", "books & language"]},
 "tt-2025-04-29": {"subjects": ["the r & tidytuesday community"]},
 "tt-2025-07-08": {"subjects": ["art & culture", "society & demographics"]},
 "tt-2025-12-02": {"subjects": ["oddities & curiosities", "environment & climate"]},  # exploding snowman
 "tt-2026-02-17": {"subjects": ["food & drink", "economy & work"]},
 "tt-2026-03-10": {"subjects": ["books & language", "society & demographics"]},
 "tt-2026-03-24": {"subjects": ["oddities & curiosities"]},             # one million digits of pi
 "tt-2026-09-01": {"subjects": ["art & culture"]},
 "tt-2019-01-15": {"subjects": ["space & astronomy"]},                          # JSR launch vehicle database
 "tt-2020-06-02": {"subjects": ["sports & games", "oddities & curiosities"]},   # Jelle's Marble Runs
 "tt-2018-11-06": {"subjects": ["environment & climate"]},                      # wind *farms*, not farming
}


BOILER = re.compile(r"(tidytuesdayr?|tt_load|read_csv|readr::|install\.packages|github\.com/rfordatascience|"
                    r"raw\.githubusercontent|## the data|option \d)", re.I)


def fields(rec):
    """The text of a record, split by how much each part should count."""
    title = (rec.get("title") or "").lower()
    src = " ".join((s.get("name") or "") for s in rec.get("sources", [])).lower()
    tabl = " ".join([t["file"] for t in rec.get("tables", [])] +
                    [c for t in rec.get("tables", []) for c in t.get("columns", [])[:25]]).lower()
    ask = " ".join(rec.get("questions", [])).lower()
    hook = BOILER.sub(" ", (rec.get("hook") or "")).lower()
    return [(title, 5), (src, 3), (ask, 2), (tabl, 2), (hook, 1)]


# Hosts that say nothing about who published the data - the human-written name does
# compared after the prefix strip below, so list the registrable form
PLATFORM_HOSTS = {
    "github.com", "githubusercontent.com", "gist.github.com",
    "kaggle.com", "data.world", "docs.google.com", "drive.google.com",
    "cran.r-project.org", "zenodo.org", "osf.io", "figshare.com", "dataverse.harvard.edu",
    "bit.ly", "twitter.com", "x.com", "en.wikipedia.org", "wikipedia.org",
}
# Only strip suffixes that are packaging, never words that belong to org names -
# "data" is the last word of "Our World in Data".
NAME_NOISE = re.compile(r"\s*\b((r|the r)\s+)?(package|pkg)\b\s*$|\s*\bdatasets?\b\s*$", re.I)


def provider_key(rec):
    """Group by who published the data, not by where the file happens to sit.

    A GitHub or Kaggle URL identifies a host, not a publisher, so for those the
    human-written name is the grouping key. Everywhere else the registrable host
    is the stable key - it survives the same organisation being written five
    different ways across eight years of readmes."""
    if not rec.get("sources"):
        return None, ""
    s = rec["sources"][0]
    host = urlsplit(s.get("url", "")).netloc.lower()
    host = re.sub(r"^(www|api|data|raw|files|download)\.", "", host)
    name = (s.get("name") or "").strip().strip("`*_ ").strip()
    # readme source names run long: "Our World in Data: Annual number of objects
    # launched into space". The publisher is the part before the colon.
    pretty = re.split(r"\s*[:\u2014\u2013]\s|\s+-\s+", name)[0].strip()
    pretty = NAME_NOISE.sub("", pretty).strip() or name
    if host and host not in PLATFORM_HOSTS and "." in host:
        return host, pretty
    return (pretty.lower() or host), pretty


def classify(rec):
    parts = fields(rec)
    title = parts[0][0]
    scores = {}
    for subject, title_only, pat in SUBJECT_RULES:
        rx = re.compile(pat)
        if title_only:
            if rx.search(title):
                scores[subject] = 6
            continue
        total = 0
        for text, weight in parts:
            if rx.search(text):
                total += weight
        if total:
            scores[subject] = total
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    subjects = [s for s, v in ranked if v >= 4][:3]
    if not subjects and ranked:
        subjects = [ranked[0][0]]

    ptext = " ".join([(s.get("name") or "") + " " + s.get("url", "") for s in rec.get("sources", [])]).lower()
    ptype = ""
    for label, pat in PROVIDER_RULES:
        if re.search(pat, ptext):
            ptype = label
            break
    if not ptype and rec.get("sources"):
        ptype = "other"

    gscores = {}
    for label, pat in GEO_RULES:
        rx = re.compile(pat)
        total = sum(w for text, w in parts if rx.search(text))
        if total:
            gscores[label] = total
    # "global" only wins outright; a named region beats it on a tie
    geo = ""
    if gscores:
        geo = sorted(gscores.items(), key=lambda kv: (-kv[1], kv[0] == "global"))[0][0]
    return subjects, ptype, geo


def main():
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    import collections
    subs, ptypes, geos, unplaced = collections.Counter(), collections.Counter(), collections.Counter(), []
    pending, names = [], {}
    for f in sorted(DATASETS.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        s, p, g = classify(rec)
        ov = OVERRIDES.get(rec["id"], {})
        s = ov.get("subjects", s)
        p = ov.get("provider_type", p)
        g = ov.get("geography", g)
        if a.force or not rec.get("subjects"):
            rec["subjects"] = s
        if a.force or not rec.get("provider_type"):
            rec["provider_type"] = p
        if a.force or not rec.get("geography"):
            rec["geography"] = g
        key, pretty = provider_key(rec)
        rec["provider"] = {"name": pretty[:60], "host": key or ""} if key else None
        pending.append((f, rec))
        if key:
            names.setdefault(key, collections.Counter())[pretty] += 1
        for x in rec["subjects"]:
            subs[x] += 1
        ptypes[rec["provider_type"] or "(none)"] += 1
        geos[rec["geography"] or "(none)"] += 1
        if not rec["subjects"]:
            unplaced.append((rec["id"], rec["title"]))

    # second pass: every record sharing a key gets the same display name
    providers = collections.Counter()
    def best(counter, fallback):
        # the spelling most readmes used, preferring a real name over a bare domain
        def rank(item):
            n, c = item
            return (0 if re.match(r"^[\w.-]+\.[a-z]{2,}$", n or "") else 1, c, -len(n))
        return max(counter.items(), key=rank)[0] if counter else fallback

    for f, rec in pending:
        if rec.get("provider"):
            key = rec["provider"]["host"]
            rec["provider"]["name"] = best(names.get(key), rec["provider"]["name"])[:60]
            providers[rec["provider"]["name"]] += 1
        with f.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    print("distinct publishers:", len(providers))
    print("top publishers:", ", ".join("%s (%d)" % (k, v) for k, v in providers.most_common(10)))

    print("subjects:")
    for k, v in subs.most_common():
        print("  %4d  %s" % (v, k))
    print("provider types:", dict(ptypes))
    print("geography:", dict(geos))
    print("\nno subject (%d):" % len(unplaced))
    for i, t in unplaced:
        print("  %s  %s" % (i, t))


if __name__ == "__main__":
    main()
