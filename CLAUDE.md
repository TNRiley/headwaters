# Headwaters — instructions for a Claude session

You are looking at a catalogue of open data sources that exists to be **used and extended by
you**, not only read by a person. Read this file before you touch anything else.

## What this is

Two catalogues that answer different questions.

**`datasets/<id>.json` — what data exists.** One file per published dataset: what it is, the
curator's own pitch, the files in it with their column names, who published it upstream, and
which aggregation surfaced it. 428 records, seeded from every TidyTuesday week since 2018.
This is the browsing layer — "is there anything good on X?"

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
python3 src/build_site.py
```

`fetch_tidytuesday.py` downloads **no data files** — everything comes from the year readme
table, the week readme, `meta.yaml` and one git-trees call. Keep it that way; the catalogue
describes datasets, it does not host or profile them.

`classify.py` is a rule table, not a pile of one-off judgements, so a week added next year
classifies itself. When it gets one wrong, prefer teaching the rule over adding an override —
and when the title genuinely misleads, add to `OVERRIDES` **with the reason as a comment**.
Re-running with `--force` recomputes everything including overrides; without it, existing
values are left alone.

Adding a second aggregation (Data Is Plural is the obvious next one) means a new
`src/fetch_<name>.py` writing the same record shape with its own `id` prefix and `found_in`
entry. A dataset that appears in two aggregations should be **one record with two `found_in`
entries**, not two records — that is the whole point of catalogueing by dataset rather than
by week.

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
src/validate.py     schema + id + cross-reference checks (stdlib only, no pip)
src/probe.py        runs every probe, writes health.json, reports what changed state
src/harvest.py      pulls leads from upstream initiatives into leads.json
src/build_site.py   splices sources + health into index.html
src/template.html   the page; edit here, never edit index.html
.github/workflows/probe.yml  weekly probe run; commits health, opens an issue on a break
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
