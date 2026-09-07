#!/usr/bin/env python3
"""Ask every catalogued source whether it still answers, and write health.json.

A link list rots. This is the whole reason Headwaters exists: each source carries
`probes` -- small real requests with stated expectations -- and this script runs
them, so the catalogue can say "verified an hour ago" instead of "worked once".

Cheap by construction: probes send a Range header and stop reading after
`range_bytes` (default 4 KB), so proving a 66 MB CSV is alive costs 4 KB.
Polite by construction: one request at a time, with a per-host delay.

    python3 src/probe.py                 # everything
    python3 src/probe.py ghcn-daily      # one source
    python3 src/probe.py --timeout 45    # slow networks
    python3 src/probe.py --fail-on-change # exit 2 if anything flipped; for CI
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
HEALTH = ROOT / "health.json"

# Identify honestly. Several of these APIs ask for a contact address and give
# better service (or any service) when you provide one.
UA = ("headwaters-probe/1.0 (+https://github.com/TNRiley/headwaters; "
      "tnril@users.noreply.github.com)")
DEFAULT_READ = 4096

# Some Python builds (notably the python.org macOS framework installs) ship with no
# CA bundle at the path OpenSSL is compiled to look in, so every HTTPS request fails
# with CERTIFICATE_VERIFY_FAILED while curl on the same machine is fine. Falling back
# to a bundle that exists keeps verification on rather than turning it off.
CA_FALLBACKS = ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem",
                "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/certs/ca-certificates.crt"]


def ssl_context():
    ctx = ssl.create_default_context()
    for path in CA_FALLBACKS:                     # additive; never replaces the defaults
        if os.path.exists(path):
            try:
                ctx.load_verify_locations(path)
            except Exception:
                pass
    if ctx.cert_store_stats().get("x509_ca"):
        return ctx
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
        return ctx
    except Exception:
        pass
    for path in CA_FALLBACKS:
        if os.path.exists(path):
            try:
                ctx.load_verify_locations(path)
                return ctx
            except Exception:
                continue
    print("warning: no CA bundle found; HTTPS verification will fail", file=sys.stderr)
    return ctx


CTX = ssl_context()
HOST_DELAY = 1.5   # seconds between two requests to the same host
ANY_DELAY = 0.3    # seconds between any two requests


def run_probe(p, timeout):
    url = p["url"]
    method = p.get("method", "GET")
    read_max = p.get("range_bytes", DEFAULT_READ)
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if method == "GET":
        # Advisory. Servers that ignore it just send more; we stop reading anyway.
        headers["Range"] = "bytes=0-%d" % (read_max - 1)
    headers.update(p.get("headers", {}))
    data = p["body"].encode("utf-8") if p.get("body") else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    out = {"url": url, "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            body = resp.read(read_max) if method != "HEAD" else b""
            out["status"] = resp.status
            out["content_type"] = resp.headers.get("Content-Type", "")
            length = resp.headers.get("Content-Range") or resp.headers.get("Content-Length")
            if length:
                out["length_header"] = length
    except urllib.error.HTTPError as e:
        body = e.read(read_max) if e.fp else b""
        out["status"] = e.code
        out["content_type"] = e.headers.get("Content-Type", "") if e.headers else ""
    except Exception as e:                       # DNS, TLS, timeout, refused
        out["status"] = None
        out["error"] = "%s: %s" % (type(e).__name__, e)
        body = b""
    out["ms"] = int((time.time() - started) * 1000)
    out["bytes_read"] = len(body)

    text = body.decode("utf-8", "replace")
    expect = p.get("expect", {})
    reasons = []
    ok_status = expect.get("status", [200, 206])
    if out.get("status") not in ok_status:
        reasons.append("status %s, wanted %s" % (out.get("status"), ok_status))
    ct = expect.get("content_type")
    if ct and ct.lower() not in out.get("content_type", "").lower():
        reasons.append("content-type %r lacks %r" % (out.get("content_type"), ct))
    for needle in expect.get("body_contains", []):
        if needle not in text:
            reasons.append("body missing %r" % needle)
    out["ok"] = not reasons
    if reasons:
        out["why"] = reasons
        out["preview"] = " ".join(text[:280].split())
    return out


# Being rate-limited is not the endpoint breaking; it is the endpoint working and us
# asking too often. Conflating the two is how a weekly watcher earns a mute: arXiv
# answers 429 (and sometimes just never answers) to a burst, and files an issue that
# resolves itself by the next run.
THROTTLE_STATUS = {429, 503}


def state_of(r):
    """The outcomes worth distinguishing when comparing two runs."""
    if r.get("ok"):
        return "ok"
    if r.get("known_broken"):
        return "dead"
    if r.get("status") in THROTTLE_STATUS or "timeout" in (r.get("error") or "").lower():
        return "throttled"
    return "failing"


def diff(previous, current):
    """What flipped between two runs, ignoring everything that stayed the same.

    Only state changes are reported, never timings or byte counts -- a probe that
    answered 40 ms slower is not a finding, and a watcher that cries every run gets
    muted. A probe seen for the first time is reported once, as `new`.
    """
    out = []
    for sid, probes in sorted(current.items()):
        for pid, r in sorted(probes.items()):
            was = (previous.get(sid) or {}).get(pid)
            now = state_of(r)
            if was is None:
                if now != "ok":
                    out.append({"source": sid, "probe": pid, "change": "new",
                                "from": None, "to": now,
                                "detail": "first run: %s -- %s" % (now, "; ".join(r.get("why", [])))})
                continue
            before = state_of(was)
            if before == now:
                continue
            detail = "; ".join(r.get("why", [])) or "status %s" % r.get("status")
            change = "recovered" if now == "ok" else \
                     "throttled" if now == "throttled" else "broke"
            out.append({"source": sid, "probe": pid, "change": change,
                        "from": before, "to": now, "detail": detail})
    for sid, probes in sorted(previous.items()):
        for pid in sorted(probes):
            if pid not in (current.get(sid) or {}) and sid in current:
                out.append({"source": sid, "probe": pid, "change": "removed",
                            "from": state_of(probes[pid]), "to": None,
                            "detail": "probe no longer defined in the record"})
    return out


def tally(results):
    """Count outcomes across a results map, however it was assembled."""
    counts = {"ok": 0, "fail": 0, "expected_fail": 0}
    for probes in results.values():
        for r in probes.values():
            key = "ok" if r.get("ok") else ("expected_fail" if r.get("known_broken") else "fail")
            counts[key] += 1
    return counts


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="source ids; default all")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--fail-on-change", action="store_true",
                    help="exit 2 if any probe changed state; for CI")
    args = ap.parse_args(argv)

    files = sorted(SOURCES.glob("*.json"))
    if args.ids:
        wanted = set(args.ids)
        files = [f for f in files if f.stem in wanted]
        missing = wanted - {f.stem for f in files}
        for m in sorted(missing):
            print("no such source: %s" % m, file=sys.stderr)

    # Read the previous run before overwriting it. What changed is the interesting part:
    # 37 of 40 answering is not news, one of them stopping is.
    previous = json.loads(HEALTH.read_text(encoding="utf-8")).get("results", {}) \
        if HEALTH.exists() else {}

    results, last_host, counts = {}, {}, {"ok": 0, "fail": 0, "expected_fail": 0}
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        sid = rec["id"]
        results[sid] = {}
        for p in rec.get("probes", []):
            host = urlsplit(p["url"]).netloc
            now = time.time()
            since = now - last_host.get(host, 0)
            wait = max(ANY_DELAY, HOST_DELAY - since, p.get("min_interval_s", 0) - since)
            if last_host:
                time.sleep(wait)
            r = run_probe(p, args.timeout)
            last_host[host] = time.time()

            r["known_broken"] = p.get("known_broken")
            if r["ok"]:
                mark, key = "ok  ", "ok"
            elif p.get("known_broken"):
                mark, key = "dead", "expected_fail"
            else:
                mark, key = "FAIL", "fail"
            counts[key] += 1
            results[sid][p["id"]] = r
            if not args.quiet:
                print("%s %-26s %-22s %s %5sms %s"
                      % (mark, sid, p["id"], str(r.get("status") or "---").rjust(3),
                         r["ms"], "; ".join(r.get("why", []))[:90]))

    changes = diff(previous, results)
    payload = {
        "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "probe_version": 1,
        "summary": counts,
        "changes": changes,
        "results": results,
    }
    if args.ids and HEALTH.exists():      # partial run: merge, do not clobber
        old = json.loads(HEALTH.read_text(encoding="utf-8"))
        merged = old.get("results", {})
        merged.update(results)
        payload["results"] = merged
        # Recount across everything held, not just what this run touched. Reporting
        # zeroes here is worse than reporting nothing: the site reads this summary,
        # so a one-source run used to publish "0 ok, 0 failing" for the whole catalogue.
        payload["summary"] = dict(tally(merged), partial=True)
    with HEALTH.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print("\n%d ok, %d failing, %d known-dead  ->  health.json"
          % (counts["ok"], counts["fail"], counts["expected_fail"]))
    for ch in changes:
        print("%-6s %s/%s  %s" % (ch["change"].upper(), ch["source"], ch["probe"], ch["detail"]))
    if args.fail_on_change and changes:
        return 2                          # for CI: a flip is worth a red build
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
