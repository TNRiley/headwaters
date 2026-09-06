# Headwaters — instructions for a Claude session

You are looking at a catalogue of open data sources that exists to be **used and extended by
you**, not only read by a person. Read this file before you touch anything else.

## What this is

`sources/<id>.json` — one file per data source. Each answers the questions you actually have
when you want to use something: what is in it, what licence, what auth, what the rate limit
is, **what breaks**, and one or two working requests you can copy.

The distinguishing feature is `probes`: small real requests with stated expectations.
`src/probe.py` runs them and writes `health.json`, so the catalogue reports what answered
today rather than what worked once. Link lists rot; this one is meant to notice.

## Use it

Before writing any data-fetching code, look here first:

```bash
grep -il "tide\|water level" sources/*.json          # is it already catalogued?
python3 -c "import json;r=json.load(open('sources/noaa-coops.json'));print(r['description']);print([g['trap'] for g in r['gotchas']])"
python3 src/probe.py noaa-coops                      # does it still answer, right now?
```

Read the `gotchas` before writing the loop, not after it fails. They are there because
somebody already lost the hour.

## Extend it

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
sources/*.json      the catalogue          — hand/agent authored, canonical
schema/             the record schema      — extend deliberately; validate.py enforces it
src/validate.py     schema + id + cross-reference checks (stdlib only, no pip)
src/probe.py        runs every probe, writes health.json
src/harvest.py      pulls leads from upstream initiatives into leads.json
src/build_site.py   splices sources + health into index.html
src/template.html   the page; edit here, never edit index.html
health.json         generated — last probe run
leads.json          generated — the queue
LANDSCAPE.md        why this exists and what already existed (written first, on purpose)
```

Everything is Python 3.9-compatible standard library. No dependencies, on purpose: this has
to run on a machine where `pip install` is not an option.

## House rules

- **Never invent a probe result.** If you cannot run it, say the record is unprobed.
- **Never soften a `known_broken` note into a hedge.** "404 on 2026-09-06, and here is what
  else I tried" is the useful sentence.
- Date every claim about behaviour you observed. Endpoints change; the record should say when
  it was last true.
- Prefer adding a `gotcha` to a source you already have over adding a shallow new record.
