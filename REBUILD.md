# Rebuilding Headwaters from scratch

For an LLM with a shell and no other context. This is a recipe, not a summary.

## 1. What is being built

A catalogue of open data sources in which every record carries **probes** — small, real HTTP
requests with stated expectations — so the catalogue can report which endpoints answered
today rather than which ones worked once. The output is a static page listing the sources,
faceted and searchable, with a health dot per probe and a drill-down record for each source.

The effect it exists to show: **catalogues rot, and the rot is invisible until you test it.**
Building the first forty records turned up six live examples, including two endpoints that
answer HTTP 200 while returning something other than what was asked for.

## 2. Data sources

There is no upstream dataset. The content *is* the research: forty sources, each investigated
and probed. Three feeds supply candidates, and all three are catalogued as sources themselves:

| Feed | URL | Notes |
|---|---|---|
| Data Is Plural archive | `https://docs.google.com/spreadsheets/d/1wZhPLMCHKJvwOkP4juclhjFgqIY8fQFMemwKL2c64vk/export?format=csv&gid=0` | 307-redirects; follow it. Columns `edition, position, headline, text, links, hattips`. Store headline + links + a short excerpt only — the prose is the author's. |
| TidyTuesday | `https://api.github.com/repos/rfordatascience/tidytuesday/contents/data/<year>` | one directory per week |
| AWS Registry of Open Data | `https://api.github.com/repos/awslabs/open-data-registry/git/trees/main?recursive=1` | **not** the contents API — see below |

## 3. Decisions, and why

- **One JSON file per source**, not one big file. Reviewable as a diff, editable by an agent
  without rewriting anything else, and it is how the AWS registry does it.
- **Probes carry expectations, not just URLs.** `expect.body_contains` is what catches an
  endpoint that answers 200 with the wrong thing. Status-only checks miss the two worst
  failures in the catalogue.
- **`range_bytes` on every probe.** A ranged GET plus an early `read()` proves a 66 MB CSV is
  alive for 4 KB. Two probes deliberately break this rule: Google Play's markers sit ~1 MB
  into a 1.36 MB page, so those read 1.2 MB and say so in a `note`.
- **`min_interval_s` per probe**, because GDELT means its five seconds and Nominatim means its
  one.
- **Dead sources keep their records** with `status: "closed"`/`"degraded"` and a
  `known_broken` probe. The failure is the finding.
- **Standard library only, Python 3.9.** It has to run where `pip install` is not an option.
- Harvested leads store an excerpt, not the full newsletter prose — the licence note in
  `sources/data-is-plural.json` is the reason.

## 4. The page

`src/template.html` with `__PAYLOAD__` replaced by `{sources, health, leads_new}`;
`src/build_site.py` does the splice, then calls the catalogue's `wrap_for_pages.py` and
`add_catalog_link.py`. Dark, dense, two-pane: faceted rail on the left (topic, access, bulk,
licence, answering-now, record status), cards in the middle, a right-hand sheet for the full
record. A second mode lists every recorded trap across all sources. `/` focuses search,
`esc` closes the sheet. Health is a dot per probe: green answering, red not, grey known-dead.

## 5. Verification table

Rebuild is correct if these hold. Every value was observed on 2026-09-06.

| Check | Expected |
|---|---|
| `python3 src/validate.py` | `40 sources checked, 0 with problems` |
| `python3 src/probe.py` | ~78 probes; 5 known-dead; failures only from throttling or a busy host |
| GHCN station CSV first line | starts `STATION,DATE,...` and contains `TMAX` |
| `ncei.noaa.gov/pub/data/ghcnd/ghcnd-stations.txt` | **404** — this is the point of that probe |
| `catalog.data.gov/api/3/action/package_search?q=climate` | **404**, body `{"detail":{},"message":"Not Found"}` |
| `api.gsa.gov/technology/datagov/v3/...` with no key | **403** `API_KEY_MISSING`; with a key, 301 to the dead origin |
| Census `acs5?get=NAME,B01001_001E&for=state:24` with no key | 302 → `missing_key.html`, which answers **200** with HTML |
| `api.github.com/repos/JeffSackmann/tennis_atp` | **404** (also `tennis_wta`); `tennis_MatchChartingProject` is 200 |
| AWS registry via contents API vs git trees | 1,000 vs 1,199 dataset files — the gap is the bug |
| Retraction Watch CSV | ~66 MB, header includes `OriginalPaperDOI` and `RetractionDate` |
| `harvest.py` totals | ~3,620 leads: ~1,917 Data Is Plural, ~1,199 AWS, ~431 TidyTuesday |

If the AWS contents-vs-trees counts come out equal, GitHub changed the behaviour and the
`github-api` gotcha needs rewriting rather than deleting.

## 6. What the page must say about itself

- The health dots are a **snapshot**, timestamped in the footer, not a live check — the page
  is static and the Artifact/Pages CSP would block a runtime fetch anyway.
- A red dot frequently means throttling, not breakage. Overpass 504s under load, GDELT
  penalises bursts for minutes across all modes, and `api.labs.crossref.org` 502s while it
  generates the retraction CSV. Each of those probes carries a `note` saying so.
- Forty sources is a deliberately small number. This is not trying to be a comprehensive
  index; the comprehensive lists already exist and are largely unverified.
