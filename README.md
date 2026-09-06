# Headwaters

**Open data sources, described well enough to start using one from a shell — and probed, so
the catalogue can tell you whether it still answers.**

→ **[tnriley.github.io/headwaters](https://tnriley.github.io/headwaters/)**

Most data catalogues are lists of links. Links rot: roughly two thirds of URLs sampled over
the last decade are dead, and government endpoints move without notice. So every source here
carries **probes** — small, real requests with stated expectations — and `src/probe.py` runs
them and records what happened.

Six things found broken while building the first forty records, none of them documented where
you would look:

- `catalog.data.gov`'s CKAN API — the endpoint every US open-data tutorial starts with — 404s
  on every documented path, while the `api.gsa.gov` proxy authenticates your key and then
  redirects you to the dead origin.
- NOAA NCEI's `pub/data/ghcnd/*` station list, in every GHCN tutorial: 404.
- SWPC's `products/solar-wind/plasma-1-day.json`, in a lot of live dashboard code: 404.
- `JeffSackmann/tennis_atp` and `tennis_wta`, the basis of most public tennis analytics: 404.
  (`tennis_MatchChartingProject` is alive; `Tennismylife/TML-Database` carries ATP results
  1968–present in the same schema.)
- The Census API without a key does not return 401. It redirects to an HTML page that answers
  **200**, so the failure reaches you as a JSON parse error in your own code.
- The GitHub contents API silently caps a directory listing at 1,000 entries and ignores
  paging — which hid 199 datasets from this repository's own first harvest of the AWS registry.

## What a record looks like

One JSON file per source, validated against [`schema/source.schema.json`](schema/source.schema.json):
identity and licence, access conditions (auth, formats, bulk, rate limit, etiquette),
copy-pasteable **recipes**, the **gotchas** that cost an hour, and the **probes**.

```json
{
  "id": "openalex",
  "access": { "auth": "email-in-user-agent", "rate_limit": "100,000/day, 10/second",
              "pagination": "cursor=* then next_cursor; page= stops working past 10,000" },
  "probes": [ { "id": "cursor-select",
                "url": "https://api.openalex.org/works?...&cursor=*",
                "expect": { "body_contains": ["next_cursor"] } } ],
  "gotchas": [ { "trap": "In counts_by_year the count key is cited_by_count, not count.",
                 "fix": "c['year'], c['cited_by_count']." } ]
}
```

## Use it

```bash
grep -il "citation\|retraction" sources/*.json   # what do we already have
python3 src/validate.py                          # schema, ids, cross-references
python3 src/probe.py                             # re-check every endpoint, write health.json
python3 src/probe.py openalex                    # just one
python3 src/harvest.py --list new | head         # candidates waiting to be researched
python3 src/build_site.py                        # regenerate index.html
```

Standard library only, no dependencies, Python 3.9 or newer — it has to run anywhere.

## How it grows

`src/harvest.py` pulls candidates from the projects that already do the finding — the
[Data Is Plural](https://www.data-is-plural.com/) archive,
[TidyTuesday](https://github.com/rfordatascience/tidytuesday)'s weeks, and the
[AWS Registry of Open Data](https://registry.opendata.aws/) — into `leads.json`. A lead
becomes a source only when someone researches it and writes a record with working probes.

[LANDSCAPE.md](LANDSCAPE.md) surveys those initiatives and explains what none of them do.
[CLAUDE.md](CLAUDE.md) is the operating manual for an AI session extending the catalogue.

## Licence

Code MIT. Each catalogued source keeps its own licence, recorded in its record. The catalogue
records themselves are CC0 — facts about public endpoints, free to take.
