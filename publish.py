#!/usr/bin/env python3
"""Export payloads from the sibling model repos, rebuild the site, commit,
and (when a remote exists) push. Python 3 stdlib only.

Usage:
    python publish.py                 # export + build + commit + push
    python publish.py --skip-export   # reuse existing payloads
    python publish.py --dry-run       # build and report; never commit or push
    python publish.py --daily         # the full daily cycle (see daily.py)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAYLOAD_DIR = ROOT / "payloads"
OUT_DIR = ROOT / "docs"

MODELS = {
    "nfl": ROOT.parent / "nfl-model",
    "nba": ROOT.parent / "nba-model",
}

EXPORT_TIMEOUT = 600

#: How many changed paths a dry run lists before it starts summarising.
DRY_RUN_LIST_CAP = 40


class PublishError(Exception):
    """Raised for expected failures; printed without a traceback."""


def repo_python(repo: Path) -> Path | None:
    for candidate in (
        repo / ".venv" / "Scripts" / "python.exe",  # Windows
        repo / ".venv" / "bin" / "python",  # POSIX
    ):
        if candidate.exists():
            return candidate
    return None


def run_export(sport: str, repo: Path) -> None:
    if not repo.is_dir():
        print(f"warning: {sport}: repo not found at {repo} - skipping export")
        return
    python = repo_python(repo)
    if python is None:
        print(f"warning: {sport}: no .venv python found in {repo} - skipping export")
        return
    print(f"{sport}: exporting site payload from {repo} ...")
    try:
        result = subprocess.run(
            [str(python), "main.py", "site-payload"],
            cwd=str(repo),
            timeout=EXPORT_TIMEOUT,
        )
        if result.returncode != 0:
            print(
                f"warning: {sport}: export exited with code {result.returncode}"
                " - continuing with any existing payload"
            )
    except subprocess.TimeoutExpired:
        print(
            f"warning: {sport}: export timed out after {EXPORT_TIMEOUT}s"
            " - continuing with any existing payload"
        )
    except OSError as err:
        print(f"warning: {sport}: could not run export ({err})")


def copy_payloads() -> int:
    PAYLOAD_DIR.mkdir(exist_ok=True)
    copied = 0
    for sport, repo in MODELS.items():
        src = repo / "reports" / "site_payload.json"
        if src.exists():
            shutil.copyfile(src, PAYLOAD_DIR / f"{sport}.json")
            print(f"{sport}: copied {src}")
            copied += 1
        else:
            print(f"warning: {sport}: no payload at {src}")
    return copied


def git(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=capture,
        text=True,
    )


def pending_changes() -> list[str]:
    """Porcelain status lines, untracked files included."""
    status = git("status", "--porcelain", capture=True)
    if status.returncode != 0:
        raise PublishError("git status failed")
    return [line for line in status.stdout.splitlines() if line.strip()]


def report_pending() -> list[str]:
    changes = pending_changes()
    if not changes:
        print("dry run: nothing would be committed")
    else:
        print(f"dry run: would commit {len(changes)} path(s):")
        for line in changes[:DRY_RUN_LIST_CAP]:
            print(f"  {line}")
        if len(changes) > DRY_RUN_LIST_CAP:
            print(f"  ... and {len(changes) - DRY_RUN_LIST_CAP} more")
    print("dry run: no commit, no push")
    return changes


def commit_and_push(dry_run: bool = False) -> tuple[bool, bool]:
    """Stage everything, commit, and push. Returns ``(committed, pushed)``.

    With ``dry_run`` nothing is staged, committed or pushed; the pending
    changes are printed so an operator can rehearse the live cycle.
    """
    if dry_run:
        report_pending()
        return False, False

    if git("add", "-A").returncode != 0:
        raise PublishError("git add failed")

    if not pending_changes():
        print("nothing changed - skipped commit")
        return False, False

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if git("commit", "-m", f"publish: {stamp}").returncode != 0:
        raise PublishError("git commit failed")
    print(f"committed: publish: {stamp}")

    remote = git("remote", "get-url", "origin", capture=True)
    if remote.returncode != 0:
        print("no remote configured - skipped push")
        return True, False
    if git("push", "origin", "main").returncode != 0:
        raise PublishError("git push failed")
    print("pushed to origin main")
    return True, True


def build_site():
    """Rebuild docs/ from payloads/. Imported lazily so this module stays
    usable (for its git helpers) without pulling the builder in."""
    sys.path.insert(0, str(ROOT))
    import build  # stdlib-only sibling module

    out = build.build(PAYLOAD_DIR, OUT_DIR)
    print(f"built site into {out}")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="do not run the model repos' exports; use existing payloads",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and report what would be committed; never commit or push",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="run the full daily cycle instead (see daily.py)",
    )
    args = parser.parse_args(argv)

    if args.daily:
        sys.path.insert(0, str(ROOT))
        import daily  # stdlib-only sibling module

        return daily.main(["--dry-run"] if args.dry_run else [])

    if not args.skip_export:
        for sport, repo in MODELS.items():
            run_export(sport, repo)

    copy_payloads()
    build_site()
    commit_and_push(args.dry_run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PublishError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
