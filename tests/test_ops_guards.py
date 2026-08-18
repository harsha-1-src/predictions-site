"""Tests for the two unattended-daily hardening features in daily.py:
the disk-space guard and the healthcheck (dead-man switch) ping.

No real disk thresholds, no real HTTP, no real git: disk_usage and
urllib.request.urlopen are monkeypatched, git is a scripted fake, and all
paths (payloads, docs, logs, .env) point into tmp_path.
"""
import io
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import daily  # noqa: E402
import publish  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

GIB = 2**30


class FakeGit:
    """Records every git invocation and answers from a scripted table."""

    def __init__(self, status=""):
        self.calls = []
        self.status = status

    def __call__(self, *args, capture=False):
        self.calls.append(args)
        out = self.status if args[:2] == ("status", "--porcelain") else ""
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")


class FakeTransport:
    """Stands in for urllib.request.urlopen; counts every GET."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.fail:
            raise urllib.error.URLError("connection refused")
        return io.BytesIO(b"OK")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway tree with fixtures, a clean fake git, a roomy fake
    disk, and no ambient healthcheck/threshold configuration."""
    payloads = tmp_path / "payloads"
    payloads.mkdir()
    shutil.copyfile(FIXTURES / "nfl_priced.json", payloads / "nfl.json")
    shutil.copyfile(FIXTURES / "nba_unpriced.json", payloads / "nba.json")

    monkeypatch.setattr(publish, "PAYLOAD_DIR", payloads)
    monkeypatch.setattr(publish, "OUT_DIR", tmp_path / "docs")
    monkeypatch.setattr(publish, "MODELS", {})
    monkeypatch.setattr(publish, "git", FakeGit())
    monkeypatch.setattr(daily, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(daily, "LOG_PATH", tmp_path / "logs" / "automation.log")
    monkeypatch.setattr(daily, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("HEALTHCHECK_URL", raising=False)
    monkeypatch.delenv("MIN_FREE_GB", raising=False)
    set_free_disk(monkeypatch, 50.0)
    return tmp_path


def set_free_disk(monkeypatch, free_gb):
    monkeypatch.setattr(
        daily.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(
            total=100 * GIB, used=100 * GIB - int(free_gb * GIB),
            free=int(free_gb * GIB)),
    )


def logged(sandbox):
    return (sandbox / "logs" / "automation.log").read_text(encoding="utf-8")


# --------------------------------------------------------------- disk guard

def test_below_threshold_aborts_before_any_work(sandbox, monkeypatch, capsys):
    set_free_disk(monkeypatch, 1.2)
    ran = []
    monkeypatch.setattr(daily, "run_model_daily", lambda s, r: ran.append(s))
    monkeypatch.setattr(publish, "MODELS", {"nfl": Path("x"), "nba": Path("x")})
    monkeypatch.setattr(publish, "copy_payloads",
                        lambda: pytest.fail("copy_payloads ran under the guard"))
    monkeypatch.setattr(publish, "build_site",
                        lambda: pytest.fail("build_site ran under the guard"))
    monkeypatch.setattr(publish, "commit_and_push",
                        lambda: pytest.fail("commit_and_push ran under the guard"))

    assert daily.main([]) != 0
    assert ran == [], "no model repo may run when the disk guard trips"
    err = capsys.readouterr().err
    assert "DISK-GUARD ABORT" in err
    assert err.count("\n") >= 5, "the banner must be an unmissable multi-line"
    assert "DISK-GUARD ABORT" in logged(sandbox)
    assert "free_gb=1.2" in logged(sandbox)


def test_exit_code_surfaces_through_publish_daily(sandbox, monkeypatch):
    set_free_disk(monkeypatch, 0.5)
    assert publish.main(["--daily"]) != 0


def test_at_the_threshold_proceeds(sandbox, monkeypatch):
    set_free_disk(monkeypatch, 2.0)  # exactly 2 GiB: at, not below
    assert daily.main(["--skip-models"]) == 0
    assert "disk_free_gb=2.0" in logged(sandbox)
    assert "DISK-GUARD" not in logged(sandbox)


def test_min_free_gb_env_override_raises_the_bar(sandbox, monkeypatch):
    set_free_disk(monkeypatch, 5.0)
    monkeypatch.setenv("MIN_FREE_GB", "10")
    assert daily.main(["--skip-models"]) != 0
    assert "DISK-GUARD ABORT" in logged(sandbox)
    assert "min_free_gb=10" in logged(sandbox)


def test_min_free_gb_override_lowers_the_bar(sandbox, monkeypatch):
    set_free_disk(monkeypatch, 1.5)  # below the 2 GiB default
    monkeypatch.setenv("MIN_FREE_GB", "1")
    assert daily.main(["--skip-models"]) == 0
    assert "disk_free_gb=1.5" in logged(sandbox)


def test_min_free_gb_from_dotenv_and_env_wins(sandbox, monkeypatch):
    set_free_disk(monkeypatch, 5.0)
    (sandbox / ".env").write_text("MIN_FREE_GB=10\n", encoding="utf-8")
    assert daily.main(["--skip-models"]) != 0, ".env threshold must be honoured"

    monkeypatch.setenv("MIN_FREE_GB", "1")
    assert daily.main(["--skip-models"]) == 0, "environment must beat .env"


def test_garbage_threshold_falls_back_to_the_default(sandbox, monkeypatch, capsys):
    set_free_disk(monkeypatch, 5.0)
    monkeypatch.setenv("MIN_FREE_GB", "plenty")
    assert daily.main(["--skip-models"]) == 0
    assert "not a number" in capsys.readouterr().err
    assert "disk_free_gb=5.0" in logged(sandbox)


def test_free_gb_figure_appears_in_the_summary_line(sandbox, monkeypatch, capsys):
    set_free_disk(monkeypatch, 12.3)
    assert daily.main(["--skip-models"]) == 0
    line = logged(sandbox).splitlines()[-1]
    assert "disk_free_gb=12.3" in line
    assert "disk_free_gb=12.3" in capsys.readouterr().out


# -------------------------------------------------------------- healthcheck

def test_successful_run_pings_exactly_once(sandbox, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc.example/ping/abc")

    assert daily.main(["--skip-models"]) == 0
    assert transport.calls == [("https://hc.example/ping/abc",
                                daily.HEALTHCHECK_TIMEOUT)]
    assert daily.HEALTHCHECK_TIMEOUT == 10
    assert "healthcheck=ok" in logged(sandbox)


def test_failed_ping_is_a_warning_not_a_run_failure(sandbox, monkeypatch, capsys):
    transport = FakeTransport(fail=True)
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc.example/ping/abc")

    assert daily.main(["--skip-models"]) == 0, "a dead switch must not fail the run"
    assert len(transport.calls) == 1
    assert "healthcheck=failed" in logged(sandbox)
    assert "warning: healthcheck ping failed" in capsys.readouterr().err


def test_unset_url_never_touches_the_network(sandbox, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", transport)

    assert daily.main(["--skip-models"]) == 0
    assert transport.calls == [], "no URL configured means no GET at all"
    assert "healthcheck=unset" in logged(sandbox)


def test_failed_daily_never_pings_even_with_a_url(sandbox, monkeypatch):
    """The point of a dead-man switch: silence must mean trouble."""
    transport = FakeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc.example/ping/abc")
    monkeypatch.setattr(publish, "MODELS", {"nfl": Path("no-such-repo")})

    assert daily.main([]) == 0  # a model failure degrades, it does not crash
    assert "nfl=FAIL" in logged(sandbox)
    assert transport.calls == [], "a failed run must stay silent"
    assert "healthcheck=skipped" in logged(sandbox)


def test_dry_run_never_pings(sandbox, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc.example/ping/abc")

    assert daily.main(["--dry-run", "--skip-models"]) == 0
    assert transport.calls == [], "a rehearsal must not reassure the switch"
    assert "healthcheck=skipped" in logged(sandbox)


def test_url_from_dotenv_is_picked_up(sandbox, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    (sandbox / ".env").write_text(
        'HEALTHCHECK_URL="https://hc.example/from-dotenv"\n', encoding="utf-8")

    assert daily.main(["--skip-models"]) == 0
    assert [u for u, _ in transport.calls] == ["https://hc.example/from-dotenv"]
    assert "healthcheck=ok" in logged(sandbox)


def test_environment_wins_over_dotenv(sandbox, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    (sandbox / ".env").write_text(
        "HEALTHCHECK_URL=https://hc.example/from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc.example/from-env")

    assert daily.main(["--skip-models"]) == 0
    assert [u for u, _ in transport.calls] == ["https://hc.example/from-env"]


# ------------------------------------------------------------- .env parsing

def test_env_file_parser_skips_malformed_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "no equals sign here\n"
        "=value-without-a-key\n"
        "HEALTHCHECK_URL='https://hc.example/q'\n"
        "  MIN_FREE_GB = 3 \n"
        "TRAILING=keeps=inner=equals\n",
        encoding="utf-8",
    )
    parsed = daily.parse_env_file(env)
    assert parsed == {
        "HEALTHCHECK_URL": "https://hc.example/q",
        "MIN_FREE_GB": "3",
        "TRAILING": "keeps=inner=equals",
    }


def test_missing_env_file_is_an_empty_dict(tmp_path):
    assert daily.parse_env_file(tmp_path / "no-such.env") == {}


# ------------------------------------------------------------- housekeeping

def test_env_is_gitignored_and_example_is_committed():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignore.splitlines()
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "HEALTHCHECK_URL=" in example
