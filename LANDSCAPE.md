# Who else has tried this, and what they leave undone

Written 2026-09-06, before the first source record, to find out what already exists.
Headwaters is deliberately narrow because of what this survey found.

---

## 1. Weekly practice communities

The best-known open-data initiatives are not catalogues at all. They are *rituals*: a
dataset lands on a schedule and a crowd analyses it together.

| Project | Since | Cadence | What it actually publishes |
|---|---|---|---|
| [TidyTuesday](https://github.com/rfordatascience/tidytuesday) | 2018 | weekly, Mondays | a cleaned dataset + a readme per week, in git |
| [Makeover Monday](https://makeovermonday.co.uk/) | 2016 | weekly | one chart and its data, to be redrawn |
| [Workout Wednesday](https://www.workout-wednesday.com/) | 2016 | weekly | a visualisation to reproduce exactly |
| [#30DayChartChallenge](https://github.com/30DayChartChallenge) | 2021 | annual, April | daily prompts, no data supplied |

TidyTuesday is the one with a durable data artefact. Roughly 400 weeks of curated CSVs
sit in one repository with per-week readmes naming the original source, and since 2025 the
curation itself is crowdsourced through pull requests. It is a superb teaching corpus.

**What it is not:** an index of where data *lives*. A TidyTuesday week is a snapshot,
cleaned and often simplified, frozen on the day it was published. Nothing in the repository
tells you whether the upstream API still answers, and nothing is meant to.

## 2. Curated lead lists

| Project | Size | Form |
|---|---|---|
| [Data Is Plural](https://www.data-is-plural.com/) | 1,900+ entries since Oct 2015 | weekly newsletter + a structured Google Sheet |
| [Awesome Public Datasets](https://github.com/awesomedata/awesome-public-datasets) | ~700 links | one markdown list |
| [awesome-gee-community-catalog](https://gee-community-catalog.org/) | ~1,000 | geospatial, Earth Engine-shaped |

Data Is Plural is the standout: one person, one paragraph per dataset, ten years of it, and
crucially an archive published as a spreadsheet with `edition, position, headline, text,
links` — machine-readable, which is why this repository harvests it.

**What they are not:** verified. A markdown list of URLs decays quietly. The original
`awesome-public-datasets` was archived read-only in 2020 and a successor picked it up;
its issue tracker is substantially reports of broken links. Data Is Plural entries from 2016
are historical documents, and its own author has never claimed otherwise.

## 3. Platform and cloud registries

- **[Registry of Open Data on AWS](https://registry.opendata.aws/)** — ~1,200 datasets, each a
  YAML file in [one GitHub repo](https://github.com/awslabs/open-data-registry), giving bucket
  ARN, region, format, licence and worked examples. Structurally the closest thing to what
  this project does, and the model for one-file-per-source. Contributed by data owners and
  not re-verified.
- **[Hugging Face Datasets](https://huggingface.co/datasets)** — hundreds of thousands of
  datasets with a uniform rows/splits/stats API. Licences are whatever the uploader typed.
- **Kaggle, data.world, Google Dataset Search** — discovery layers over other people's
  hosting; Dataset Search is an index of `schema.org/Dataset` markup, so it finds what
  publishers chose to describe.

## 4. Institutional portals

`data.gov` indexes roughly half a million US federal datasets, and the EU, UK and most US
states and large cities run CKAN or Socrata portals with real APIs.

Worth recording plainly, because it is the sharpest finding of the day:
**on 2026-09-06 every documented `catalog.data.gov` CKAN API path returned 404** —
`/api/3/action/package_search`, `/api/action/…`, `/api/1/metastore/…`, `/api/4/…` — and the
`api.gsa.gov` v3 proxy authenticates a key and then 301s straight back to the dead origin.
The web catalogue still loads. Every tutorial, wrapper library and language model answer
about US open data still begins with that endpoint.

## 5. Research-data registries and metadata standards

- **[re3data](https://www.re3data.org/)** (a DataCite service) — 3,000+ research data
  repositories described against a rich schema, CC0, with an API. The place to answer
  *where would data about X live*.
- **Zenodo, Dataverse, Figshare** — the repositories themselves, each minting DOIs.
- **Metadata vocabularies** — `schema.org/Dataset` for discovery; **DCAT** for government
  catalogue interchange; **Frictionless Data Package** for the internal shape of a table;
  **[Croissant](https://mlcommons.org/working-groups/data/croissant/)** (MLCommons, 2024)
  layering ML-specific structure on top of schema.org, now supported by CKAN and Hugging Face.

These are the serious end of the field, and they describe *datasets*: what a thing contains,
who made it, how to cite it. None of them describe **whether the endpoint answered this
morning, what it returns when it does not, and which two lines of the response will ruin
your afternoon**. That is a different kind of fact, and it has no standard because it is
perishable — which is precisely why it has to be tested rather than declared.

## 6. Enterprise catalogue software

DataHub, OpenMetadata, Amundsen, Magda, CKAN itself. Excellent tools, aimed at an
organisation's *internal* warehouse: lineage, ownership, governance, freshness SLAs. They
assume you already have the data and credentials. Different problem.

---

## The gap

Everything above is one of three things: a **ritual** (weekly practice), a **lead list**
(long, wide, unverified), or a **metadata standard** (what a dataset contains). Nobody keeps
the fourth thing:

> a small, deep, continuously re-tested record of **how to actually get the data** —
> the exact URL, the parameters that matter, the auth, the rate limit that will ban you,
> and the trap that costs an hour.

Link rot makes this the binding constraint rather than an annoyance. A longitudinal study of
27.3 million URLs found about 65% of 1996–2021 samples dead by 2023; Ahrefs put 66.5% of
links to two million domains at nine years. Government data has its own decay — 23% of US
state COVID dashboards had moved or vanished within 26 months.

Six failures found on the first day of building this, none of them documented anywhere the
searcher would look:

| What breaks | Where the wrong answer still lives |
|---|---|
| `catalog.data.gov` CKAN API — every path 404 | every tutorial on US open data |
| NCEI `pub/data/ghcnd/*` station list — 404 | every GHCN tutorial older than ~2024 |
| SWPC `products/solar-wind/plasma-1-day.json` — 404 | a lot of live dashboard code |
| `JeffSackmann/tennis_atp` and `tennis_wta` — 404 | thousands of tennis notebooks and papers |
| Census API without a key — 302 to an HTML page that answers **200** | surfaces as a JSON parse error in your code |
| GitHub contents API — silently caps a directory at 1,000 entries | hid 199 of the AWS registry's own datasets from this repo's first harvest |

The last two are the interesting ones. Neither is an outage. Both are endpoints that answer
*successfully* while giving you something other than what you asked for, and both are
invisible to any check that only asks "did the request return 200".

## What Headwaters takes from each

| From | Taken |
|---|---|
| AWS registry | one file per source, in git, reviewable as a diff |
| re3data / DCAT | a real schema with licence, temporal coverage and access conditions as first-class fields |
| Data Is Plural | prose that explains why a source is interesting, not just what it contains — and its archive, harvested as leads |
| TidyTuesday | community curation as an explicit pull-request workflow, and its 400 weeks as leads |
| Croissant | the principle that machine-readable beats human-readable when a machine is the main reader |

And the one thing none of them do: **`probes`** — small, real, expectation-bearing requests
stored beside each record, run by `src/probe.py`, so the catalogue reports what answered
today rather than what worked once.

---

### Sources

- [TidyTuesday](https://github.com/rfordatascience/tidytuesday) · [about](https://rfordatascience.github.io/tidytuesday/about.html)
- [Data Is Plural](https://www.data-is-plural.com/) · [archive](https://data.world/jsvine/data-is-plural-archive)
- [Awesome Public Datasets](https://github.com/awesomedata/awesome-public-datasets)
- [Registry of Open Data on AWS](https://registry.opendata.aws/) · [repo](https://github.com/awslabs/open-data-registry)
- [re3data](https://www.re3data.org/) · [Scientific Data paper](https://www.nature.com/articles/s41597-023-02462-y)
- [Croissant, MLCommons](https://mlcommons.org/working-groups/data/croissant/) · [paper](https://arxiv.org/pdf/2403.19546) · [CKAN support](https://ckan.org/blog/bridging-ckan-and-machine-learning-introducing-support-for-the-croissant-standard)
- [Data.gov API docs, GSA](https://open.gsa.gov/api/datadotgov/) · [resources.data.gov](https://resources.data.gov/catalog-api/)
- [Makeover Monday](https://makeovermonday.co.uk/) · [Workout Wednesday](https://www.workout-wednesday.com/) · [#30DayChartChallenge](https://github.com/30DayChartChallenge)
- [Ahrefs link rot study](https://ahrefs.com/blog/link-rot-study/) · [Link rot, Wikipedia](https://en.wikipedia.org/wiki/Link_rot)
