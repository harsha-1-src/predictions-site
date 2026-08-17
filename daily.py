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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import publish  # noqa: E402  (stdlib-only sibling module)

ROOT = publish.ROOT
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "automation.log"

#: Model dailies retrain and re-scrape; give them room but not forever.
DAILY_TIMEOUT = 1800


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


def summary_line(results: dict, changed: bool, pushed: bool, dry_run: bool) -> str:
    """One grep-friendly line: when, which repos worked, what happened."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    repos = " ".join(
        f"{sport}={'OK' if ok else 'FAIL'}" for sport, ok in sorted(results.items())
    ) or "models=skipped"
    state = "changed" if changed else "unchanged"
    mode = " mode=dry-run" if dry_run else ""
    return f"{stamp} daily {repos} site={state} pushed={'y' if pushed else 'n'}{mode}"


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

    line = summary_line(results, changed, pushed, args.dry_run)
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
