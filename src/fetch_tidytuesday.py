#!/usr/bin/env python3
"""Build a dataset record for every TidyTuesday week, without downloading any data.

Everything needed is metadata the project already publishes:

  * one git-trees call            -> every file in every week, with sizes
  * data/<year>/readme.md  (x9)   -> the spine: title, date, source name+url, article
  * data/<year>/<date>/readme.md  -> the hook prose, the canonical file list, column names
  * data/<year>/<date>/meta.yaml  -> structured title/source/article for weeks since 2024-07

Writes datasets/tt-<date>.json. Subjects are left empty here and filled by the
classification pass (src/classify.py), so re-running this never clobbers them.

    python3 src/fetch_tidytuesday.py            # incremental; skips cached readmes
    python3 src/fetch_tidytuesday.py --refresh  # re-fetch everything
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from probe import CTX, UA                                    # CA-bundle fallback lives there

OUT = ROOT / "datasets"
CACHE = ROOT / ".cache" / "tidytuesday"
REPO = "rfordatascience/tidytuesday"
RAW = "https://raw.githubusercontent.com/%s/main/" % REPO
TREE = "https://api.github.com/repos/%s/git/trees/main?recursive=1" % REPO
DELAY = 0.25

# Year-opening weeks with no dataset at all - "bring your own data from last year".
# They are TidyTuesday events, not datasets, and would be empty records here.
SKIP_WEEKS = {"2020-12-29", "2022-01-04", "2023-01-03"}

DATA_EXT = {"csv", "tsv", "xlsx", "xls", "json", "rds", "zip", "gz", "txt", "parquet"}
SKIP_FILE = re.compile(r"^~\$|^readme|^meta\.yaml$|^intro\.md$|^post_vars\.json$|\.(png|jpg|jpeg|gif|r|rmd|py|md)$", re.I)
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")


def demarkdown(s):
    """The hook is shown to a person, so it should not carry markdown scaffolding."""
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)      # images
    s = LINK.sub(r"\1", s)                             # links -> their text
    s = re.sub(r"[*_]{1,3}(?=\S)", "", s)
    s = re.sub(r"(?<=\S)[*_]{1,3}", "", s)
    s = s.replace("`", "")
    s = re.sub(r"https?://\S+", "", s)                 # bare URLs read as noise
    return re.sub(r"\s+", " ", s).strip()


def fetch(path, refresh=False):
    """Fetch a repo path as text, cached on disk. Returns None on 404."""
    cached = CACHE / path.replace("/", "__")
    if cached.exists() and not refresh:
        return cached.read_text(encoding="utf-8")
    url = RAW + path
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        body = urllib.request.urlopen(req, timeout=60, context=CTX).read().decode("utf-8", "replace")
    except Exception as e:
        if "404" in str(e):
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text("", encoding="utf-8")
            return None
        raise
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(body, encoding="utf-8")
    time.sleep(DELAY)
    return body or None


def tree_by_week(refresh=False):
    cached = CACHE / "_tree.json"
    if cached.exists() and not refresh:
        tree = json.loads(cached.read_text(encoding="utf-8"))
    else:
        req = urllib.request.Request(TREE, headers={"User-Agent": UA})
        tree = json.loads(urllib.request.urlopen(req, timeout=60, context=CTX).read())
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(tree), encoding="utf-8")
    weeks = {}
    for node in tree["tree"]:
        parts = node["path"].split("/")
        if len(parts) == 4 and parts[0] == "data" and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[2]):
            weeks.setdefault(parts[2], []).append({"file": parts[3], "bytes": node.get("size")})
    return weeks


def parse_year_table(md):
    """The per-year readme table is the only uniform record of every week."""
    rows = {}
    for line in md.splitlines():
        if not line.startswith("|") or line.startswith("|--") or "|:--" in line or "|---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not re.match(r"^\d+$", cells[0]):
            continue
        week = int(cells[0])
        data_links = LINK.findall(cells[2])
        if not data_links:
            continue
        title, folder = data_links[0]
        # the link target is the week folder, but its form varies by year:
        # "2018-04-02", "2024-01-09/readme.md", "./2021-01-05". Take the date, not a path segment.
        m = re.search(r"(\d{4}-\d{2}-\d{2})", folder)
        if not m:
            continue
        slug = m.group(1)
        srcs = [{"name": n.strip(), "url": u} for n, u in LINK.findall(cells[3])]
        arts = [{"name": n.strip(), "url": u} for n, u in LINK.findall(cells[4])] if len(cells) > 4 else []
        rows[slug] = {"week": week, "title": title.strip(), "sources": srcs, "articles": arts}
    return rows


def parse_meta_yaml(text):
    """Tiny reader for the handful of keys TidyTuesday's meta.yaml actually uses.

    Deliberately not a YAML parser: no dependency is allowed here, and the file
    shape is fixed (title, article.title/url, data_source.title/url)."""
    out, section = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "-")):
            key = line.split(":", 1)[0].strip()
            section = key if line.rstrip().endswith(":") else None
            if key == "title" and ":" in line:
                out["title"] = line.split(":", 1)[1].strip().strip('"')
        elif section in ("article", "data_source") and ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"')
            if v:
                out.setdefault(section, {})[k.strip()] = v
    return out


def parse_week_readme(md):
    """Hook prose, the canonical file list, and column names per file."""
    out = {"title": "", "hook": "", "questions": [], "files": [], "columns": {}, "links": []}
    if not md:
        return out
    body = md.split("## The Data")[0]
    lines = body.splitlines()
    for line in lines:
        if line.startswith("# "):
            out["title"] = demarkdown(line[2:])
            break
    para, paras, questions = [], [], []
    for line in lines[1:]:
        s = line.strip()
        if s.startswith("|"):                 # a markdown table, not prose
            continue
        if s.startswith("- ") or s.startswith("* "):
            questions.append(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s[2:]).strip())
            continue
        if not s:
            if para:
                paras.append(" ".join(para)); para = []
            continue
        if s.startswith("#"):
            continue
        para.append(s.lstrip("> ").strip())
    if para:
        paras.append(" ".join(para))
    out["links"] = [{"name": n.strip(), "url": u} for n, u in LINK.findall(body) if u.startswith("http")]
    plain = [demarkdown(p) for p in paras]
    plain = [p for p in plain if len(p) > 30 and not p.lower().startswith("thank you")]
    hook = " ".join(plain)
    if len(hook) > 900:
        cut = hook[:900]
        stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        hook = (cut[:stop + 1] if stop > 500 else cut[:cut.rfind(" ")] + "\u2026")
    out["hook"] = hook
    out["questions"] = [demarkdown(q) for q in questions if len(q) > 12][:5]

    # canonical files: the ones the readme itself tells you to read
    out["files"] = list(dict.fromkeys(re.findall(r"/data/\d{4}/\d{4}-\d{2}-\d{2}/([\w.\-]+)", md)))

    # column names only - the class and description columns are deliberately dropped
    current = None
    for line in md.splitlines():
        m = re.match(r"^#+\s*`?([\w.\-]+\.(?:csv|tsv|xlsx|xls|json|rds))`?\s*$", line.strip())
        if m:
            current = m.group(1); out["columns"].setdefault(current, [])
            continue
        if current and line.startswith("|"):
            first = line.strip().strip("|").split("|")[0].strip().strip("`")
            if first and not set(first) <= set(":- ") and first.lower() not in ("variable", "column", "field", "name"):
                out["columns"][current].append(first)
    out["columns"] = {k: v for k, v in out["columns"].items() if v}
    return out


def build(refresh=False):
    OUT.mkdir(exist_ok=True)
    weeks = tree_by_week(refresh)
    years = sorted({w[:4] for w in weeks})
    spine = {}
    for y in years:
        md = fetch("data/%s/readme.md" % y, refresh)
        if md:
            spine.update(parse_year_table(md))

    written = 0
    for slug in sorted(weeks):
        if slug in SKIP_WEEKS:
            continue
        files = weeks[slug]
        names = {f["file"] for f in files}
        sp = spine.get(slug, {})
        rd = parse_week_readme(fetch("data/%s/%s/readme.md" % (slug[:4], slug), refresh)) if "readme.md" in names else parse_week_readme("")
        meta = parse_meta_yaml(fetch("data/%s/%s/meta.yaml" % (slug[:4], slug), refresh) or "") if "meta.yaml" in names else {}

        title = meta.get("title") or sp.get("title") or rd.get("title") or slug
        sources = []
        if meta.get("data_source", {}).get("url"):
            sources.append({"name": meta["data_source"].get("title", ""), "url": meta["data_source"]["url"]})
        for s in sp.get("sources", []):
            if s["url"] not in {x["url"] for x in sources}:
                sources.append(s)
        articles = []
        if meta.get("article", {}).get("url"):
            articles.append({"name": meta["article"].get("title", ""), "url": meta["article"]["url"]})
        for a in sp.get("articles", []):
            if a["url"] not in {x["url"] for x in articles}:
                articles.append(a)

        # tables: prefer the files the readme names, else every data-shaped file in the folder
        listed = [f for f in rd["files"] if f in names and not SKIP_FILE.search(f)]
        if not listed:
            listed = sorted(f["file"] for f in files
                            if not SKIP_FILE.search(f["file"])
                            and f["file"].rsplit(".", 1)[-1].lower() in DATA_EXT)
        size = {f["file"]: f["bytes"] for f in files}
        tables = []
        for f in listed[:12]:
            tables.append({"file": f, "bytes": size.get(f),
                           "url": RAW + "data/%s/%s/%s" % (slug[:4], slug, f),
                           "columns": rd["columns"].get(f, [])})

        rec = {
            "id": "tt-%s" % slug,
            "title": title,
            "hook": rd["hook"],
            "questions": rd["questions"],
            "subjects": [], "provider_type": "", "geography": "",   # filled by classify.py
            "sources": sources,
            "articles": articles,
            "tables": tables,
            "extra_files": max(0, len([f for f in files if not SKIP_FILE.search(f["file"])]) - len(tables)),
            "found_in": [{
                "aggregation": "tidytuesday", "date": slug, "year": int(slug[:4]),
                "week": sp.get("week"),
                "url": "https://github.com/%s/tree/main/data/%s/%s" % (REPO, slug[:4], slug),
            }],
            "added": date.today().isoformat(),
        }
        path = OUT / ("%s.json" % rec["id"])
        if path.exists():                      # never clobber a classification pass
            old = json.loads(path.read_text(encoding="utf-8"))
            for k in ("subjects", "provider_type", "geography", "notes", "added"):
                if old.get(k):
                    rec[k] = old[k]
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
        written += 1

    print("%d weeks written to datasets/" % written)
    missing = [s for s in sorted(weeks)
               if s not in SKIP_WEEKS and not (OUT / ("tt-%s.json" % s)).exists()]
    if missing:
        print("missing:", missing)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    build(ap.parse_args().refresh)
