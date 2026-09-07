# Headwaters — instructions for a Claude session

You are looking at a catalogue of open data sources that exists to be **used and extended by
you**, not only read by a person. Read this file before you touch anything else.

## What this is

Two catalogues that answer different questions.

**`datasets/<id>.json` — what data exists.** One file per published dataset: what it is, the
curator's own pitch, the files in it with their column names, who published it upstream, and
which aggregation surfaced it. 2,371 records from two aggregations — every TidyTuesday week
since 2018, and ten years of Data Is Plural — with 30 datasets that both of them surfaced
held as **one record with two `found_in` entries**, never two records. This is the browsing
layer — "is there anything good on X?"

**`sources/<id>.json` — how to get data.** One file per queryable endpoint. Each answers the questions you actually have
when you want to use something: what is in it, what licence, what auth, what the rate limit
is, **what breaks**, and one or two working requests you can copy.

The distinguishing feature is `probes`: small real requests with stated expectations.
`src/probe.py` runs them and writes `health.json`, so the catalogue reports what answered
today rather than what worked once. Link lists rot; this one is meant to notice.

## Use it

Everything goes through `./hw`. It works from any directory, so a session in another
project can reach the catalogue by path.

```bash
./hw find tide                    # both layers, ranked; column names are the best key
./hw joins tt-2024-01-09          # what could this be combined with, and on what key
./hw show noaa-coops              # the whole record: licence, auth, limits, gotchas, recipes, probes
./hw gotchas census               # the traps
./hw recipe openalex              # copy-paste starting points
./hw add https://x.org/api        # do we already know this? ask BEFORE researching from scratch
./hw probe noaa-coops             # does it still answer, right now?
./hw health                       # what is failing, and what changed since the run before
./hw stats
```

Every command takes `--json`. The underlying records are plain files, so `grep -il penguin
datasets/*.json` still works and is sometimes faster to think in.

Read the `gotchas` before writing the loop, not after it fails. They are there because
somebody already lost the hour.

## Reach it from another session

`src/mcp_server.py` serves the same queries as MCP tools over stdio, so a session in any
project can consult the catalogue without knowing where it lives:

```bash
claude mcp add headwaters -- /usr/bin/python3 /abs/path/to/headwaters/src/mcp_server.py
```

That exposes `headwaters_find`, `headwaters_show`, `headwaters_gotchas`,
`headwaters_recipe`, `headwaters_known`, `headwaters_used_by` and `headwaters_health`.
It is hand-rolled JSON-RPC — no SDK, no pip, like everything else here. **Every byte on
stdout is protocol**: anything reused from `hw.py` inside a tool handler must be a pure
function, because one stray `print()` kills the server with an unhelpful parse error.

## Write back

The catalogue is only worth its keep if using it feeds it. After building anything that
touched data:

```bash
./hw used-by openalex still-cited     # this project consumed that source
./hw add https://newthing.org/api --write   # scaffolds sources/newthing.json to fill in
```

Then add a `gotcha` for anything that cost you time. **A new gotcha on an existing record
beats a shallow new record.** `nightly/DISPATCH.md` in the workspace makes this a step of
every nightly build.

## Extend the dataset layer

New TidyTuesday weeks appear every Monday. Picking them up is two commands and no judgement:

```bash
python3 src/fetch_tidytuesday.py     # incremental; readmes are cached under .cache/
python3 src/classify.py              # fills only empty fields, so it never undoes a correction
python3 src/quality.py --sweep       # strip the publisher's boilerplate out of the new hooks
python3 src/build_site.py
```

## The prose gate

The browsing layer lives on its hooks, and a quarter of the first 428 records opened with
TidyTuesday's standing request to add alt text to your charts — three paragraphs about
accessible visualisation, filed as the description of a dataset about technology adoption.

`src/quality.py` catches that class of thing without a list of known phrases, because the
next aggregation will have its own. **The signal is repetition: a paragraph appearing
verbatim in several records is not a description of any of them.** That is a corpus-level
judgement, so it is learned once into `boilerplate.json` and then applied per record —
which is also why `validate.py` and every fetcher can consult it for free.

```bash
python3 src/quality.py               # what is wrong with the corpus's prose
python3 src/quality.py --sweep       # learn and strip, repeatedly, until nothing changes
```

Three things to know before you touch it:

- **`--sweep` iterates for a reason.** Fragments are compared as groups of whole sentences,
  so removing the first half of a block re-groups what is left and exposes fingerprints
  nobody had seen. Stripping the alt-text block's opening paragraphs revealed eight more
  fragments underneath it, in the same 107 records.
- **Re-fetching and sweeping alternate.** A fetcher strips the boilerplate it knows about
  *before* the length cap — the alt-text block runs to ~800 characters, so on the weeks
  that carried it the cap was spent before the readme reached the data. Each re-fetch
  recovers prose, which can expose new boilerplate, so run both until each is a no-op.
- **Repetition is a good signal, not a perfect one.** Three weeks genuinely drew on IMDb
  and said so in the same words. Record such an exception in `boilerplate.json`'s
  `not_boilerplate` map **with its reason** — do not raise the threshold until it survives,
  because that lets real boilerplate through. Relearning preserves those judgements.

An empty hook is an honest outcome, not a defect to paper over: the earliest TidyTuesday
weeks have no week readme at all. Never invent a pitch for a dataset — `hook` means the
curator's words. If you write one yourself, set `hook_source: "manual"` and every tool
here will leave it alone.

### Filling `questions`

`questions` is what turns browsing into an idea, and it is nearly empty. The schema says
what a good one is: answerable from the columns the record already lists, phrased as a
question, and specific enough that it could not be asked of a different dataset. Set
`questions_source` to `curator` (the publisher's own bullets), `generated` or `manual` —
a curator's question is evidence about the dataset and a generated one is not.

**An ingest that has the publisher's prose in front of it should fill this in the same
pass.** Back-filling later means a second traversal of the whole corpus for no reason.

`fetch_tidytuesday.py` downloads **no data files** — everything comes from the year readme
table, the week readme, `meta.yaml` and one git-trees call. Keep it that way; the catalogue
describes datasets, it does not host or profile them.

`classify.py` is a rule table, not a pile of one-off judgements, so a week added next year
classifies itself. When it gets one wrong, prefer teaching the rule over adding an override —
and when the title genuinely misleads, add to `OVERRIDES` **with the reason as a comment**.
Re-running with `--force` recomputes everything including overrides; without it, existing
values are left alone.

Adding a third aggregation means a new `src/fetch_<name>.py` writing the same record shape
with its own `id` prefix and `found_in` entry — `src/fetch_dip.py` is the worked example.
A dataset that appears in two aggregations must be **one record with two `found_in` entries**,
not two records; that is the whole point of catalogueing by dataset rather than by week.

**Read `Matcher` in `src/fetch_dip.py` before writing that merge logic**, because both
tempting shortcuts are wrong and neither fails loudly. Matching on any link merged five
unrelated entries that each happened to mention `gdeltproject.org`. Dropping the query string
from a URL merged a 2015 newsletter entry into TidyTuesday's bird bath dataset, because every
PLOS article is `journals.plos.org/plosone/article?id=…` and without the query they are all
the same string. Identity is the entry's **first** link, query intact, and a bare homepage
identifies nothing. A false merge destroys two real records and leaves nothing behind to
notice it.

## Extend the source layer

**When you find or use a data source that is not in here, add it.** That is the whole point.
The bar is: someone with a shell and no other context could start using it from your record.

1. Copy the shape of an existing file — `sources/open-meteo.json` is a clean, ordinary one;
   `sources/apple-review-rss.json` shows how to document something fragile and half-closed.
2. Write at least one probe that would fail if the source changed in a way that matters.
   Prefer a cheap one: `range_bytes` stops the read early, so proving a 66 MB CSV is alive
   costs 4 KB. Set `min_interval_s` if the publisher demands spacing.
3. `python3 src/validate.py` then `python3 src/probe.py <id>` — **do not commit a record whose
   probes you have not run.** A green record that was never tested is worse than no record.
4. `python3 src/build_site.py` to regenerate `index.html`.

### Things that belong in a record and are usually left out

- **Failures.** A source that closed keeps its record, with `status: "closed"` or `"degraded"`
  and a `known_broken` probe saying what you tried and when. `sources/data-gov.json` and
  `sources/tennis-open-data.json` are the models. Knowing an endpoint is dead is worth as much
  as knowing one is alive, and nobody else writes it down.
- **The silent failures.** An endpoint that answers 200 with the wrong thing — the Census API
  redirecting a keyless call to an HTML page, the GitHub contents API capping a directory at
  1,000 entries — costs far more than an outage. Probe for the content, not just the status.
- **The exact string.** `counts_by_year` uses `cited_by_count`, not `count`. Write that down.

## The join graph

`src/joins.py` answers the question after "what exists": what could I put this *next to*?
It derives, for each dataset, which others appear to share an entity key.

```bash
python3 src/joins.py                      # rebuild joins.json
python3 src/joins.py --explain tt-2024-01-09
python3 src/joins.py --sample 12          # a spread, for eyeballing
```

Four things it learned the hard way, all of which a rewrite would rediscover:

- **A shared time column is not a discovery.** `year` is in 129 records. A graph built on
  time says everything joins to everything. An edge needs an *entity* key; time only
  confirms two datasets could line up.
- **`place` keys and `entity` keys behave oppositely.** A place — county, country,
  coordinate — is a universal code space, so a cross-subject join is the whole point and
  distance is rewarded. An entity — species, airport, station — is nominally shared and
  practically disjoint: bats and coffee both have a `species` column and their species
  never meet. Entity edges are kept only when the subjects agree. `person` and `company`
  were dropped outright; matching on a name is not matching on a key.
- **Popular records swamp everything.** Scoring alone made one dataset of chart-design
  mistakes the top suggestion for half the catalogue, because it has a country column and
  an unusual subject, so it scored maximum distance against all comers. There is a hub
  penalty *and* a per-partner quota, and both were necessary.
- **Keys arrive with qualifiers.** `birth_country`, `home_state`, `birth_city`. Anchored
  patterns matched none of them, so the NHL birth-dates record reported no keys while
  carrying three. Column names are matched whole *and* by underscore-delimited part.

**Say what the evidence is.** Only the records that came from TidyTuesday list column
names, so for most of the catalogue the key is read out of the description. Every edge
carries `basis`: `columns` (both declare it — a fact), `mixed`, or `inferred` (a guess).
Never present an inferred edge as though it were a column match. And a shared key means a
join is *mechanically possible*, never that the values overlap — the catalogue does not
download data, so it cannot know that.

## Grow the queue

`src/harvest.py` pulls candidates from the initiatives that already do the finding — Data Is
Plural's archive, TidyTuesday's weeks, the AWS open-data registry — into `leads.json`.
A lead is not a source; promoting one means researching it and writing a real record.

```bash
python3 src/harvest.py                       # refresh all feeds
python3 src/harvest.py --list new | head -40  # what is waiting
python3 src/harvest.py --mark dip:2019.03.06-2 catalogued
```

Leads whose host already appears in a source record are auto-marked `catalogued`.

## Layout

```
hw                  the CLI; run it from anywhere
datasets/*.json     what data exists       — generated, then corrected by hand
sources/*.json      how to get data        — hand/agent authored, canonical
schema/             both record schemas    — extend deliberately; validate.py enforces them
src/hw.py           search, show, gotchas, recipes, add, used-by, probe, health, stats
src/mcp_server.py   the same, as MCP tools over stdio, for sessions in other projects
src/match.py        "do we already know about this?" — the one host/title normaliser
src/fetch_tidytuesday.py  builds dataset records from TidyTuesday metadata (no downloads)
src/classify.py     subject / publisher / geography rules, plus the override table
src/quality.py      learns publisher boilerplate from repetition; strips it; reports prose
src/joins.py        derives which datasets share an entity key -> joins.json
src/fetch_dip.py    builds dataset records from the Data Is Plural archive
src/validate.py     schema + id + cross-reference checks (stdlib only, no pip)
src/probe.py        runs every probe, writes health.json, reports what changed state
src/harvest.py      pulls leads from upstream initiatives into leads.json
src/build_site.py   splices sources + health into index.html
src/template.html   the page; edit here, never edit index.html
.github/workflows/probe.yml  weekly probe run; commits health, opens an issue on a break
boilerplate.json    generated — learned boilerplate, plus the not_boilerplate judgements
joins.json          generated — the join graph
health.json         generated — last probe run
leads.json          generated — the queue
LANDSCAPE.md        why this exists and what already existed (written first, on purpose)
```

Everything is Python 3.9-compatible standard library. No dependencies, on purpose: this has
to run on a machine where `pip install` is not an option.

## House rules

- **Never invent a probe result.** If you cannot run it, say the record is unprobed.
- **Host and title normalisation lives in `src/match.py`.** Three private copies of that
  rule is how they drift apart. If a match is wrong, fix it there and add a case to
  `_selftest()` — `python3 src/match.py` runs them.
- **Never let `build_site.py` publish an unwrapped fragment.** It refuses on its own now
  (the page would render in quirks mode with UTF-8 read as Latin-1), but if you see that
  refusal, the fix is to supply the wrapper, never to bypass the check.
- **Being rate-limited is not being broken.** `probe.py` classifies 429, 503 and read
  timeouts as `throttled`, and the weekly run does not raise an issue for them. If you
  find a publisher that means its limit, set `min_interval_s` on the probe rather than
  letting the catalogue break the etiquette it documents.
- **Never soften a `known_broken` note into a hedge.** "404 on 2026-09-06, and here is what
  else I tried" is the useful sentence.
- Date every claim about behaviour you observed. Endpoints change; the record should say when
  it was last true.
- Prefer adding a `gotcha` to a source you already have over adding a shallow new record.
