#!/usr/bin/env python3
"""The site's daily cycle: run both models, republish, log what happened.

Python 3 stdlib only. This is the entry point a scheduler (cron, Task
Scheduler, a human) calls once a day:

    1. run each sibling model repo's own `daily` command, in its own venv;
    2. copy each repo's reports/site_payload.json into payloads/;
    3. rebuild docs/ (which also republishes docs/data/<sport>.json);
    4. commit and push to origin, when there is anything to commit;
    5. append a one-line summary to logs/automation.log.

A model repo that is missing, has no venv, fails, or hangs produces a
warning and the cycle carries on with that sport's previous payload. One
broken model must not take the whole site down, and a stale-but-honest page
beats no page.

Usage:
    python daily.py                # the live cycle
    python daily.py --dry-run      # build and report; no commit, no push
    python daily.py --skip-models  # reuse existing payloads (debugging)

`python publish.py --daily` is an alias for the first form; `publish.py`
without it keeps its original export-only behaviour, which is what the
model repos call.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import publish  # noqa: E402  (stdlib-only sibling module)

ROOT = publish.ROOT
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "automation.log"

#: Model dailies retrain and re-scrape; give them room but not forever.
DAILY_TIMEOUT = 1800

#: Optional site-local config (gitignored). See .env.example.
ENV_PATH = ROOT / ".env"

#: Refuse to start a run with less than this much free disk, in GiB.
#: Override with MIN_FREE_GB (environment variable or .env).
MIN_FREE_GB_DEFAULT = 2.0

#: One short GET; a healthcheck ping must never stall the daily.
HEALTHCHECK_TIMEOUT = 10


# ----------------------------------------------------------- .env / settings
# Mirrors nba-model's nba_model/odds_api.py parser rather than importing it:
# the site repo must stand alone on stdlib, with no cross-repo imports.

def parse_env_file(path: Path | str | None = None) -> dict[str, str]:
    """Minimal KEY=VALUE .env parser (stdlib only). Missing/unreadable
    files are an empty dict; blanks, #comments and lines without '=' are
    skipped and surrounding quotes are stripped from the value."""
    try:
        text = Path(path or ENV_PATH).read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _setting(name: str) -> str:
    """One config value: the process environment wins over `.env`."""
    return (os.environ.get(name) or parse_env_file().get(name) or "").strip()


# ------------------------------------------------------------- disk guard

DISK_BANNER = """\
!!====================================================================!!
!!  DISK-GUARD ABORT - the daily cycle DID NOT RUN                    !!
!!                                                                    !!
!!  free disk space : {free:>8.2f} GiB                                    !!
!!  required minimum: {need:>8.2f} GiB                                    !!
!!                                                                    !!
!!  Nothing happened: no model dailies, no build, no commit, no push. !!
!!  A full disk mid-run can corrupt the git index or silently write   !!
!!  truncated payloads; refusing to start is the safe failure.        !!
!!                                                                    !!
!!  Free some space, then rerun:  python daily.py                     !!
!!  (Threshold override: MIN_FREE_GB, via environment or .env.)       !!
!!====================================================================!!"""


def free_disk_gb() -> float:
    """Free space, in GiB, on the volume this repo lives on."""
    return shutil.disk_usage(str(ROOT)).free / 2**30


def min_free_gb() -> float:
    """The abort threshold: MIN_FREE_GB (env, then .env), default 2 GiB."""
    raw = _setting("MIN_FREE_GB")
    if not raw:
        return MIN_FREE_GB_DEFAULT
    try:
        return float(raw)
    except ValueError:
        print(
            f"warning: MIN_FREE_GB={raw!r} is not a number - "
            f"using the default {MIN_FREE_GB_DEFAULT:g} GiB",
            file=sys.stderr,
        )
        return MIN_FREE_GB_DEFAULT


# ------------------------------------------------------------- healthcheck

def ping_healthcheck(url: str) -> bool:
    """One GET to the dead-man-switch URL. True on any response; a failed
    ping is a warning, never a run failure."""
    try:
        with urllib.request.urlopen(url, timeout=HEALTHCHECK_TIMEOUT) as resp:
            resp.read(64)
        return True
    except Exception as err:  # URLError, HTTPError, timeout, bad URL, ...
        print(f"warning: healthcheck ping failed ({err})", file=sys.stderr)
        return False


def run_model_daily(sport: str, repo: Path) -> bool:
    """Run ``<repo>/main.py daily`` in the repo's own venv. True on success."""
    if not Path(repo).is_dir():
        print(f"warning: {sport}: repo not found at {repo} - skipping")
        return False
    python = publish.repo_python(Path(repo))
    if python is None:
        print(f"warning: {sport}: no .venv python in {repo} - skipping")
        return False
    print(f"{sport}: running daily in {repo} ...")
    try:
        result = subprocess.run(
            [str(python), "main.py", "daily"],
            cwd=str(repo),
            timeout=DAILY_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"warning: {sport}: daily timed out after {DAILY_TIMEOUT}s")
        return False
    except OSError as err:
        print(f"warning: {sport}: could not run daily ({err})")
        return False
    if result.returncode != 0:
        print(f"warning: {sport}: daily exited with code {result.returncode}")
        return False
    print(f"{sport}: daily OK")
    return True


def summary_line(results: dict, changed: bool, pushed: bool, dry_run: bool,
                 free_gb: float | None = None,
                 healthcheck: str | None = None) -> str:
    """One grep-friendly line: when, which repos worked, what happened."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    repos = " ".join(
        f"{sport}={'OK' if ok else 'FAIL'}" for sport, ok in sorted(results.items())
    ) or "models=skipped"
    state = "changed" if changed else "unchanged"
    extra = ""
    if free_gb is not None:
        extra += f" disk_free_gb={free_gb:.1f}"
    if healthcheck is not None:
        extra += f" healthcheck={healthcheck}"
    mode = " mode=dry-run" if dry_run else ""
    return (f"{stamp} daily {repos} site={state}"
            f" pushed={'y' if pushed else 'n'}{extra}{mode}")


def append_log(line: str) -> None:
    """Append to logs/automation.log. The log is gitignored: it is a local
    operational record, not site content."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as err:  # never fail a good run over the logbook
        print(f"warning: could not write {LOG_PATH}: {err}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and report what would be committed; never commit or push",
    )
    parser.add_argument(
        "--skip-models",
        action="store_true",
        help="do not run the model repos' daily; publish the payloads they "
        "already have",
    )
    args = parser.parse_args(argv)

    # Disk guard: refuse to start on a nearly-full volume. This runs
    # before ANY work - no model dailies, no build, no commit, no push.
    threshold = min_free_gb()
    free_gb = free_disk_gb()
    if free_gb < threshold:
        print(DISK_BANNER.format(free=free_gb, need=threshold), file=sys.stderr)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        append_log(f"{stamp} DISK-GUARD ABORT free_gb={free_gb:.1f}"
                   f" min_free_gb={threshold:g}")
        return 1

    results: dict = {}
    if args.skip_models:
        print("--skip-models: reusing the payloads already in payloads/")
    else:
        for sport, repo in publish.MODELS.items():
            results[sport] = run_model_daily(sport, repo)

    publish.copy_payloads()
    publish.build_site()

    if args.dry_run:
        changed = bool(publish.report_pending())
        pushed = False
    else:
        changed, pushed = publish.commit_and_push()

    # Healthcheck (dead-man switch): ping ONLY after a fully successful
    # LIVE run - every repo that ran succeeded (or models were skipped
    # cleanly) and the publish step did not raise. Silence must mean
    # trouble, so a failed or rehearsed run never pings.
    success = all(results.values())
    url = _setting("HEALTHCHECK_URL")
    if not url:
        healthcheck = "unset"  # not configured; skip silently
    elif args.dry_run or not success:
        healthcheck = "skipped"
    else:
        healthcheck = "ok" if ping_healthcheck(url) else "failed"

    line = summary_line(results, changed, pushed, args.dry_run,
                        free_gb=free_gb, healthcheck=healthcheck)
    append_log(line)
    print(line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except publish.PublishError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
