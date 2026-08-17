"""Tests for build.py. Stdlib-only code under test; pytest as the runner."""
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import build as build_mod  # noqa: E402
from build import build  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = ("index.html", "track-record.html", "methodology.html")

DISCLAIMER = (
    "These are the outputs of a hobby statistical model, published for fun "
    "and transparency. Not betting advice."
)


@pytest.fixture(scope="module")
def full_site(tmp_path_factory):
    """Build from the full-featured NFL + NBA fixtures."""
    base = tmp_path_factory.mktemp("full")
    payload_dir = base / "payloads"
    payload_dir.mkdir()
    shutil.copyfile(FIXTURES / "nfl.json", payload_dir / "nfl.json")
    shutil.copyfile(FIXTURES / "nba.json", payload_dir / "nba.json")
    out = base / "docs"
    build(payload_dir, out)
    return out


@pytest.fixture(scope="module")
def empty_site(tmp_path_factory):
    """Build from an empty-state NFL payload; NBA payload missing entirely."""
    base = tmp_path_factory.mktemp("empty")
    payload_dir = base / "payloads"
    payload_dir.mkdir()
    shutil.copyfile(FIXTURES / "empty.json", payload_dir / "nfl.json")
    out = base / "docs"
    build(payload_dir, out)
    return out


def read(out_dir, name):
    return (out_dir / name).read_text(encoding="utf-8")


# (a) outputs exist

def test_build_produces_expected_files(full_site):
    for name in PAGES + ("style.css", ".nojekyll"):
        assert (full_site / name).exists(), f"missing {name}"


def test_empty_build_produces_expected_files(empty_site):
    for name in PAGES + ("style.css", ".nojekyll"):
        assert (empty_site / name).exists(), f"missing {name}"


# (b) index content

def test_index_contains_matchup_and_tier_badge(full_site):
    index = read(full_site, "index.html")
    assert "DAL @ NYG" in index
    assert "KC @ BUF" in index
    assert "BOS @ NYK" in index
    assert 'class="badge badge-strong"' in index
    assert ">Strong<" in index
    # NFL line comparison and logged-at stamp
    assert "Model line DAL -3.5" in index
    assert "market DAL -2.5" in index
    assert "picked 2026-09-10" in index


def test_index_empty_state(empty_site):
    index = read(empty_site, "index.html")
    assert "No upcoming picks logged yet" in index
    assert "check back at the start of the season" in index


# (c) track record content

def test_track_record_has_running_chart_svg(full_site):
    track = read(full_site, "track-record.html")
    assert "<svg" in track
    assert 'class="chart-line"' in track
    assert "running straight-up accuracy" in track.lower()
    # graded-games table with tick/cross and ATS for NFL
    assert "PHI @ WAS" in track
    assert "&#10003;" in track or "✓" in track
    assert "&#10007;" in track or "✗" in track
    assert "Push" in track


def test_track_record_empty_state(empty_site):
    track = read(empty_site, "track-record.html")
    assert "Awaiting first results" in track
    assert "3 picks are logged" in track
    assert "<svg" not in track  # chart skipped entirely in empty state


# (d) disclaimer footer everywhere

@pytest.mark.parametrize("page", PAGES)
def test_disclaimer_on_every_page(full_site, empty_site, page):
    assert DISCLAIMER in read(full_site, page)
    assert DISCLAIMER in read(empty_site, page)


# (e) no leaked Python literals

@pytest.mark.parametrize("page", PAGES)
def test_no_leaked_none_or_nan(full_site, empty_site, page):
    for site in (full_site, empty_site):
        text = read(site, page)
        assert "None" not in text, f"'None' leaked into {page}"
        assert "NaN" not in text, f"'NaN' leaked into {page}"


# (f) all hrefs are relative

@pytest.mark.parametrize("page", PAGES)
def test_hrefs_are_relative(full_site, empty_site, page):
    for site in (full_site, empty_site):
        text = read(site, page)
        for href in re.findall(r'href="([^"]*)"', text):
            assert not href.startswith("/"), (
                f"absolute href {href!r} in {page}"
            )


# missing payload -> empty sections, build still succeeds

def test_missing_payload_renders_empty_state(empty_site):
    index = read(empty_site, "index.html")
    # NBA payload was absent entirely; its section still renders
    assert 'id="nba-picks"' in index
    track = read(empty_site, "track-record.html")
    assert "No results published yet" in track


# (g) the publisher stamp: who published, and when

STAMP_RE = re.compile(
    r"Last updated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC from (\S+)"
)


@pytest.mark.parametrize("page", PAGES)
def test_publisher_stamp_on_every_page(full_site, empty_site, page):
    """A page with no data at all still says who published it and when —
    that is precisely the case an operator needs to spot."""
    for site in (full_site, empty_site):
        match = STAMP_RE.search(read(site, page))
        assert match, f"no publisher stamp in {page}"
        assert match.group(1) not in ("", "None")


def test_publisher_stamp_uses_build_time_not_payload_generated_at(tmp_path):
    """The payloads are from 2026; the stamp must show the build clock."""
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    shutil.copyfile(FIXTURES / "nfl.json", payload_dir / "nfl.json")
    out = tmp_path / "docs"
    build(
        payload_dir,
        out,
        built_at=datetime(2031, 3, 4, 5, 6, tzinfo=timezone.utc),
        publisher="vps3508171",
    )
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Last updated 2031-03-04 05:06 UTC from vps3508171" in index
    # ...and the payload's own generated_at is not what the footer shows.
    generated = json.loads(
        (FIXTURES / "nfl.json").read_text(encoding="utf-8")
    )["generated_at"]
    assert f"Last updated {generated[:10]}" not in index


def test_build_time_is_rendered_in_utc(tmp_path):
    """A non-UTC build clock is converted, never printed as local time."""
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    out = tmp_path / "docs"
    minus_seven = timezone(timedelta(hours=-7))
    build(
        payload_dir,
        out,
        built_at=datetime(2026, 8, 17, 13, 25, tzinfo=minus_seven),
        publisher="box",
    )
    assert "Last updated 2026-08-17 20:25 UTC from box" in (
        out / "index.html").read_text(encoding="utf-8")


def test_publisher_defaults_to_the_short_hostname(monkeypatch):
    monkeypatch.delenv(build_mod.PUBLISHER_ENV, raising=False)
    monkeypatch.setattr(
        build_mod.socket, "gethostname", lambda: "vps3508171.hosting.example.net"
    )
    assert build_mod.resolve_publisher() == "vps3508171"


def test_publisher_env_var_overrides_the_hostname(monkeypatch):
    monkeypatch.setattr(build_mod.socket, "gethostname", lambda: "ignored")
    monkeypatch.setenv(build_mod.PUBLISHER_ENV, "  vps-prod  ")
    assert build_mod.resolve_publisher() == "vps-prod"


def test_blank_env_override_falls_back_to_the_hostname(monkeypatch):
    monkeypatch.setattr(build_mod.socket, "gethostname", lambda: "realbox.local")
    monkeypatch.setenv(build_mod.PUBLISHER_ENV, "   ")
    assert build_mod.resolve_publisher() == "realbox"


def test_unnameable_host_still_produces_a_stamp(monkeypatch):
    monkeypatch.delenv(build_mod.PUBLISHER_ENV, raising=False)
    monkeypatch.setattr(build_mod.socket, "gethostname", lambda: "")
    assert build_mod.resolve_publisher() == build_mod.UNKNOWN_PUBLISHER


def test_publisher_is_html_escaped(tmp_path):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    out = tmp_path / "docs"
    build(payload_dir, out, publisher='a"<b>')
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "<b>" not in index.split("<footer")[1]
    assert "&lt;b&gt;" in index
