# Headwaters

**A catalogue of datasets worth working with, and of the sources they come from.**

Two layers, deliberately different:

- **`datasets/`** — 2,371 specific published datasets: what they are, what is in them, who
  published them, and where the original data lives. Classified by subject and publisher so
  you can browse for something to work with rather than search for something you already
  know exists. Drawn from two aggregations that select for very different things — every week
  of [TidyTuesday](https://github.com/rfordatascience/tidytuesday) since April 2018 (tidy,
  teachable, column names known) and ten years of
  [Data Is Plural](https://www.data-is-plural.com/) (odd, specific, hard to believe it
  exists). A dataset both of them surfaced is one record with two sightings, and the
  **Found via** facet filters on that.
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
./hw find tide                 # search both layers; column names are the best key
./hw joins tt-2024-01-09       # what could this be combined with, and on what key
./hw show noaa-coops           # licence, auth, rate limit, gotchas, recipes, probe results
./hw gotchas census            # the traps, before you write the loop
./hw recipe openalex           # requests that run as written
./hw add https://x.org/api     # already catalogued? ask before researching from scratch
./hw health                    # what is failing, and what changed since the run before
./hw stats
```

Add `--json` to any of them. The records are plain files, so `grep -il penguin datasets/*.json`
works too.

Maintenance:

```bash
python3 src/validate.py                           # schema, ids, cross-references
python3 src/probe.py                              # re-check every endpoint, write health.json
python3 src/match.py                              # normalisation self-test
python3 src/fetch_tidytuesday.py                  # pick up new weeks (incremental, cached)
python3 src/classify.py                           # assign subjects, publishers, geography
python3 src/quality.py --sweep                    # strip publisher boilerplate from hooks
python3 src/joins.py                              # rebuild the join graph
python3 src/harvest.py --list new | head          # candidates waiting to be researched
python3 src/build_site.py                         # regenerate index.html
```

Standard library only, no dependencies, Python 3.9 or newer — it has to run anywhere.

### From another project

`src/mcp_server.py` serves the same queries as MCP tools over stdio, so a session working
somewhere else can consult the catalogue without knowing where it lives:

```bash
claude mcp add headwaters -- /usr/bin/python3 /abs/path/to/headwaters/src/mcp_server.py
```

`headwaters_find`, `headwaters_show`, `headwaters_gotchas`, `headwaters_recipe`,
`headwaters_known`, `headwaters_used_by`, `headwaters_health`. Hand-rolled JSON-RPC, no SDK.

### It checks itself

`.github/workflows/probe.yml` runs every probe weekly, commits the results, and opens an
issue **only when a source changes state** — never for a recovery, and never for a rate
limit, which `probe.py` classifies separately from a failure. A watcher that cries every
week is a watcher nobody reads.

### What could this be joined with

A catalogue tells you what exists. `src/joins.py` derives the question after that — which
datasets share an entity key, so you could put two of them together. It ignores time keys
(`year` is in 129 records; a graph built on it says everything joins to everything), knows
that a *place* key like county or coordinate joins across subjects while a *species* key
only joins within one, and labels every edge with the evidence behind it: both records
declaring the column, or the key merely being read out of a description.

968 of 2,371 records have at least one candidate. A shared key means a join is
mechanically possible — not that the values overlap.

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
