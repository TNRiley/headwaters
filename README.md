# Headwaters

**A catalogue of datasets worth working with, and of the sources they come from.**

Two layers, deliberately different:

- **`datasets/`** — 428 specific published datasets: what they are, what is in them, who
  published them, and where the original data lives. Classified by subject and publisher so
  you can browse for something to work with rather than search for something you already
  know exists. Seeded from every week of [TidyTuesday](https://github.com/rfordatascience/tidytuesday)
  since April 2018.
- **`sources/`** — 40 endpoints you can query repeatedly, each described well enough to use
  from a shell, and **probed**, so the catalogue can say whether it still answers.

A dataset is a thing you might want to work with. A source is a thing you query. The join
between them is `provider` — when a dataset came from an endpoint we document, the record
links straight to its access recipe.

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

## What a dataset record looks like

Everything comes from metadata the publisher already wrote — no data files are downloaded:

```
tt-2024-01-09   Canadian NHL Player Birth Dates
  hook      Are Canadian NHL players still disproportionately born in January?
            Gladwell said yes in 2008; the data runs to 2022.
  subjects  sports & games, society & demographics        geography  Canada
  tables    canada_births_1991_2022.csv   5 KB   year, month, births
            nhl_player_births.csv       511 KB   player_id, first_name, birth_date, birth_city …
            nhl_rosters.csv             8.2 MB   team_code, season, position_code, headshot …
            nhl_teams.csv                 1 KB   team_code, full_name
  came from Statistics Canada · NHL team list endpoint · NHL API
  write-up  "Are Birth Dates Still Destiny for Canadian NHL Players?"
```

Column *names* are kept because they are the best search key — someone typing "elevation"
should find the dataset that has an elevation column even when the title never says so.
Column types and descriptions are deliberately not kept: this is a catalogue, not a data
dictionary.

## What a source record looks like

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
grep -il "penguin\|bird" datasets/*.json          # is there something fun on this?
grep -il "citation\|retraction" sources/*.json    # do we already document this endpoint?
python3 src/validate.py                           # schema, ids, cross-references
python3 src/probe.py                              # re-check every endpoint, write health.json
python3 src/fetch_tidytuesday.py                  # pick up new weeks (incremental, cached)
python3 src/classify.py                           # assign subjects, publishers, geography
python3 src/harvest.py --list new | head          # candidates waiting to be researched
python3 src/build_site.py                         # regenerate index.html
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
