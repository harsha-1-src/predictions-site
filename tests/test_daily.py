import json
"""Tests for the daily orchestration and publish.py's dry run.

Nothing here touches the real git repository or runs a real model: the git
helper and the model subprocess are both stubbed, and the payload/output
directories are redirected into tmp_path.
"""
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import daily  # noqa: E402
import publish  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class FakeGit:
    """Records every git invocation and answers from a scripted table."""

    def __init__(self, status="", has_origin=True):
        self.calls = []
        self.status = status
        self.has_origin = has_origin

    def __call__(self, *args, capture=False):
        self.calls.append(args)
        out, code = "", 0
        if args[:2] == ("status", "--porcelain"):
            out = self.status
        elif args[:1] == ("remote",):
            code = 0 if self.has_origin else 1
        return subprocess.CompletedProcess(args, code, stdout=out, stderr="")

    def ran(self, verb):
        return any(call[0] == verb for call in self.calls)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect publish/daily at a throwaway tree seeded with fixtures."""
    payloads = tmp_path / "payloads"
    payloads.mkdir()
    shutil.copyfile(FIXTURES / "nfl_priced.json", payloads / "nfl.json")
    shutil.copyfile(FIXTURES / "nba_unpriced.json", payloads / "nba.json")

    monkeypatch.setattr(publish, "PAYLOAD_DIR", payloads)
    monkeypatch.setattr(publish, "OUT_DIR", tmp_path / "docs")
    monkeypatch.setattr(publish, "MODELS", {})
    monkeypatch.setattr(daily, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(daily, "LOG_PATH", tmp_path / "logs" / "automation.log")
    return tmp_path


# ------------------------------------------------------------- model runner

def test_missing_repo_warns_and_continues(capsys):
    assert daily.run_model_daily("nfl", Path("no-such-repo")) is False
    assert "warning" in capsys.readouterr().out


def test_repo_without_a_venv_warns_and_continues(tmp_path, capsys):
    assert daily.run_model_daily("nfl", tmp_path) is False
    assert "no .venv python" in capsys.readouterr().out


def test_nonzero_exit_is_a_failure_not_a_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(publish, "repo_python", lambda repo: tmp_path / "python.exe")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 3),
    )
    assert daily.run_model_daily("nba", tmp_path) is False
    assert "exited with code 3" in capsys.readouterr().out


def test_timeout_is_a_failure_not_a_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(publish, "repo_python", lambda repo: tmp_path / "python.exe")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("main.py", daily.DAILY_TIMEOUT)

    monkeypatch.setattr(subprocess, "run", boom)
    assert daily.run_model_daily("nfl", tmp_path) is False
    assert "timed out" in capsys.readouterr().out


def test_success_reports_true(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "repo_python", lambda repo: tmp_path / "python.exe")
    recorded = {}

    def fake_run(cmd, cwd=None, timeout=None, **kwargs):
        recorded.update(cmd=cmd, cwd=cwd, timeout=timeout)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert daily.run_model_daily("nfl", tmp_path) is True
    assert recorded["cmd"][1:] == ["main.py", "daily"]
    assert recorded["cwd"] == str(tmp_path)
    assert recorded["timeout"] == daily.DAILY_TIMEOUT == 1800


# ------------------------------------------------------------------ dry run

def test_dry_run_builds_but_never_commits_or_pushes(sandbox, monkeypatch, capsys):
    git = FakeGit(status=" M docs/index.html\n?? docs/data/nfl.json\n")
    monkeypatch.setattr(publish, "git", git)

    assert daily.main(["--dry-run", "--skip-models"]) == 0

    assert (sandbox / "docs" / "index.html").exists(), "dry run must still build"
    assert not git.ran("add") and not git.ran("commit") and not git.ran("push")
    out = capsys.readouterr().out
    assert "would commit 2 path(s)" in out
    assert "docs/data/nfl.json" in out
    assert "dry run: no commit, no push" in out


def test_dry_run_on_a_clean_tree_says_so(sandbox, monkeypatch, capsys):
    monkeypatch.setattr(publish, "git", FakeGit(status=""))
    daily.main(["--dry-run", "--skip-models"])
    assert "nothing would be committed" in capsys.readouterr().out


def test_publish_dry_run_flag_reaches_the_same_place(sandbox, monkeypatch, capsys):
    git = FakeGit(status=" M docs/index.html\n")
    monkeypatch.setattr(publish, "git", git)
    assert publish.main(["--skip-export", "--dry-run"]) == 0
    assert not git.ran("commit")
    assert "dry run: no commit, no push" in capsys.readouterr().out


def test_publish_daily_flag_delegates_to_daily(sandbox, monkeypatch):
    seen = []

    def fake_main(argv=None):
        seen.append(argv)
        return 0

    monkeypatch.setattr(daily, "main", fake_main)
    assert publish.main(["--daily"]) == 0
    assert publish.main(["--daily", "--dry-run"]) == 0
    assert seen == [[], ["--dry-run"]]


def test_publish_skip_export_still_commits_and_pushes(sandbox, monkeypatch):
    """The behaviour the model repos depend on must not regress."""
    git = FakeGit(status=" M docs/index.html\n")
    monkeypatch.setattr(publish, "git", git)
    exported = []
    monkeypatch.setattr(publish, "run_export", lambda s, r: exported.append(s))

    assert publish.main(["--skip-export"]) == 0

    assert exported == [], "--skip-export must not run the exporters"
    assert git.ran("add") and git.ran("commit") and git.ran("push")


def test_commit_is_skipped_when_nothing_changed(sandbox, monkeypatch, capsys):
    git = FakeGit(status="")
    monkeypatch.setattr(publish, "git", git)
    assert publish.commit_and_push() == (False, False)
    assert not git.ran("commit")
    assert "nothing changed" in capsys.readouterr().out


def test_push_is_skipped_without_an_origin(sandbox, monkeypatch):
    git = FakeGit(status=" M docs/index.html\n", has_origin=False)
    monkeypatch.setattr(publish, "git", git)
    assert publish.commit_and_push() == (True, False)
    assert git.ran("commit") and not git.ran("push")


# ------------------------------------------------------------------ live run

def test_live_run_copies_builds_commits_pushes_and_logs(sandbox, monkeypatch):
    git = FakeGit(status=" M docs/index.html\n")
    monkeypatch.setattr(publish, "git", git)
    monkeypatch.setattr(publish, "MODELS", {"nfl": Path("no-such"), "nba": Path("no-such")})

    assert daily.main([]) == 0

    assert (sandbox / "docs" / "data" / "nfl.json").exists()
    assert git.ran("add") and git.ran("commit") and git.ran("push")

    logged = (sandbox / "logs" / "automation.log").read_text(encoding="utf-8")
    assert "nfl=FAIL" in logged and "nba=FAIL" in logged
    assert "site=changed" in logged and "pushed=y" in logged


def test_log_appends_rather_than_overwrites(sandbox, monkeypatch):
    monkeypatch.setattr(publish, "git", FakeGit(status=""))
    daily.main(["--skip-models"])
    daily.main(["--skip-models"])
    lines = (sandbox / "logs" / "automation.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all("site=unchanged" in line and "pushed=n" in line for line in lines)


# ------------------------------------------------------------ summary format

def test_summary_line_shape():
    line = daily.summary_line({"nfl": True, "nba": False}, changed=True, pushed=True,
                              dry_run=False)
    stamp, rest = line.split(" ", 1)
    assert stamp.endswith("Z") and "T" in stamp
    assert rest == "daily nba=FAIL nfl=OK site=changed pushed=y"


def test_summary_line_marks_dry_runs():
    line = daily.summary_line({}, changed=True, pushed=False, dry_run=True)
    assert "models=skipped" in line
    assert line.endswith("site=changed pushed=n mode=dry-run")


# --------------------------------------------------------- log is gitignored

def test_logs_directory_is_ignored_except_for_its_keepfile():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "logs/*" in ignore
    assert "!logs/.gitkeep" in ignore
    assert (REPO / "logs" / ".gitkeep").exists()


# ------------------------------------------------- no-op publishing (churn)
def test_rebuild_without_content_change_leaves_docs_untouched(tmp_path, monkeypatch):
    """A daily re-run must not push a commit whose only diff is the
    run's own timestamps — otherwise the site churns a commit a day."""
    import build
    import publish

    payloads = tmp_path / "payloads"
    payloads.mkdir()
    src = Path(__file__).parent / "fixtures"
    (payloads / "nfl.json").write_text((src / "nfl_priced.json").read_text(
        encoding="utf-8"), encoding="utf-8")
    docs = tmp_path / "docs"
    monkeypatch.setattr(publish, "PAYLOAD_DIR", payloads)
    monkeypatch.setattr(publish, "OUT_DIR", docs)

    assert publish.build_site() is True, "first build populates docs/"
    before = {p.relative_to(docs): p.stat().st_mtime_ns
              for p in docs.rglob("*") if p.is_file()}
    assert before, "docs/ should contain files"

    # Same payload, later clock: generated_at moves, nothing else does.
    assert publish.build_site() is False
    after = {p.relative_to(docs): p.stat().st_mtime_ns
             for p in docs.rglob("*") if p.is_file()}
    assert after == before, "no file may be rewritten by a no-op rebuild"

    # A real content change is still adopted.
    payload = json.loads((payloads / "nfl.json").read_text(encoding="utf-8"))
    payload["upcoming"][0]["pick_prob"] = 0.999
    (payloads / "nfl.json").write_text(json.dumps(payload), encoding="utf-8")
    assert publish.build_site() is True
    assert "0.999" in (docs / "data" / "nfl.json").read_text(encoding="utf-8") or \
        "99.9" in (docs / "index.html").read_text(encoding="utf-8")
    assert build  # imported for the build path under test


def test_publisher_change_is_material_but_the_clock_alone_is_not(tmp_path):
    """The footer stamp carries two things with opposite churn rules.

    A later build time is noise — masking it is the whole reason the daily
    re-run does not commit. A different publishing host is *news*: the site
    moved boxes, and that must reach git.
    """
    import build

    payloads = tmp_path / "payloads"
    payloads.mkdir()
    (payloads / "nfl.json").write_text(
        (FIXTURES / "nfl_priced.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    def staged(name, built_at, publisher):
        out = tmp_path / name
        build.build(payloads, out, built_at=built_at, publisher=publisher)
        return out

    t0 = datetime(2026, 8, 17, 20, 25, tzinfo=timezone.utc)
    baseline = staged("a", t0, "vps3508171")

    # Hours later on the same box: only the stamp moved.
    later = staged("b", t0 + timedelta(hours=9, minutes=41), "vps3508171")
    assert publish._materially_changed(later, baseline) is False

    # Same instant, different box: a real change, and it reaches the page.
    moved = staged("c", t0, "vps9900001")
    assert publish._materially_changed(moved, baseline) is True
    assert "from vps9900001" in (moved / "index.html").read_text(encoding="utf-8")

    # Both at once still publishes — the host change is not masked away.
    both = staged("d", t0 + timedelta(days=3), "vps9900001")
    assert publish._materially_changed(both, baseline) is True


def test_relabelling_the_box_publishes_through_the_real_build_path(
        tmp_path, monkeypatch):
    """End-to-end through publish.build_site(): SITE_PUBLISHER is read from
    the build environment, so relabelling the box adopts a new docs/."""
    payloads = tmp_path / "payloads"
    payloads.mkdir()
    (payloads / "nfl.json").write_text(
        (FIXTURES / "nfl_priced.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    monkeypatch.setattr(publish, "PAYLOAD_DIR", payloads)
    monkeypatch.setattr(publish, "OUT_DIR", docs)

    monkeypatch.setenv("SITE_PUBLISHER", "vps-old")
    assert publish.build_site() is True
    assert "from vps-old" in (docs / "index.html").read_text(encoding="utf-8")

    assert publish.build_site() is False, "same box, same content - no publish"

    monkeypatch.setenv("SITE_PUBLISHER", "vps-new")
    assert publish.build_site() is True, "a new publisher must reach docs/"
    assert "from vps-new" in (docs / "index.html").read_text(encoding="utf-8")
