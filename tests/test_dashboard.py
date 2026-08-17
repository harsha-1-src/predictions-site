"""Tests for the home-page P/L dashboard, the cumulative units chart, the
docs/data/*.json contract, and v1-payload tolerance."""
import html
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from build import build  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = ("index.html", "track-record.html", "methodology.html")

DISCLAIMER = (
    "These are the outputs of a hobby statistical model, published for fun "
    "and transparency. Not betting advice."
)

# Saturday 2026-10-24, 11:00 Pacific. The priced NFL fixture has a graded game
# that day, two that Mon-Sun week, three that month.
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def make_site(tmp_path, nfl=None, nba=None, now=NOW):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    if nfl:
        shutil.copyfile(FIXTURES / nfl, payload_dir / "nfl.json")
    if nba:
        shutil.copyfile(FIXTURES / nba, payload_dir / "nba.json")
    out = tmp_path / "docs"
    build(payload_dir, out, now)
    return out


@pytest.fixture(scope="module")
def priced_site(tmp_path_factory):
    """NFL with graded ATS + ML across two months; NBA with no prices."""
    return make_site(
        tmp_path_factory.mktemp("priced"), "nfl_priced.json", "nba_unpriced.json"
    )


@pytest.fixture(scope="module")
def blank_site(tmp_path_factory):
    """Both leagues pre-season: picks logged, nothing graded."""
    return make_site(tmp_path_factory.mktemp("blank"), "empty.json", "empty.json")


@pytest.fixture(scope="module")
def v1_site(tmp_path_factory):
    """The original schema: no settle, no revisions, no ml_price anywhere."""
    return make_site(tmp_path_factory.mktemp("v1"), "nfl.json", "nba.json")


def read(out_dir, name):
    return (out_dir / name).read_text(encoding="utf-8")


def text(out_dir, name):
    """Page with HTML entities resolved, for asserting on prose."""
    return html.unescape(read(out_dir, name))


def dashboard(out_dir):
    match = re.search(
        r'<section class="dashboard".*?</section>', read(out_dir, "index.html"), re.S
    )
    assert match, "dashboard section missing from index.html"
    return match.group(0)


# ------------------------------------------------------------ shell and rows

def test_dashboard_is_above_the_slates(priced_site):
    index = read(priced_site, "index.html")
    assert index.index('class="dashboard"') < index.index('id="nfl-picks"')


@pytest.mark.parametrize("row", ["Today", "This week", "This month"])
def test_dashboard_has_the_three_period_rows(priced_site, row):
    assert f'<th scope="row">{row}</th>' in dashboard(priced_site)


def test_dashboard_has_a_column_per_league_plus_combined(priced_site):
    head = dashboard(priced_site)
    for label in ("NFL", "NBA", "Combined"):
        assert f'<th scope="col">{label}</th>' in head


# ----------------------------------------------------------- priced numbers

def test_dashboard_shows_units_and_record_for_a_priced_league(priced_site):
    dash = dashboard(priced_site)
    # Today: HOU/TEN only — ATS win at -110 (+0.9091) and ML win at -300
    # (+0.3333) = +1.24u on a 2-0-0 record.
    assert "+1.24u" in dash
    assert ">2-0-0<" in dash
    # This week adds the SEA/ARI ATS + ML double loss: -0.76u on 2-2-0.
    assert "-0.76u" in dash
    assert ">2-2-0<" in dash
    # This month adds CIN/BAL: +0.54u on 4-2-0.
    assert "+0.54u" in dash
    assert ">4-2-0<" in dash


def test_dashboard_colour_codes_wins_and_losses(priced_site):
    dash = dashboard(priced_site)
    assert 'class="pl-units pl-pos">+1.24u' in dash
    assert 'class="pl-units pl-neg">-0.76u' in dash
    # The sign is always printed, so colour is never the only cue.
    assert re.search(r'pl-units[^>]*>[+-]\d', dash)


def test_pushes_are_reported_separately_and_never_as_wins(priced_site):
    # The all-time ATS block on the track record: 3 wins, 2 losses, 1 push.
    track = read(priced_site, "track-record.html")
    assert "3-2-1, ROI 12.1%" in track


def test_combined_column_sums_the_leagues(priced_site):
    # NBA contributes no priced bets, so Combined equals NFL here.
    row = re.search(
        r'<th scope="row">Today</th>(.*?)</tr>', dashboard(priced_site), re.S
    ).group(1)
    assert row.count("+1.24u") == 2  # NFL cell and Combined cell


# ------------------------------------------------------- unpriced fallback

def test_unpriced_league_shows_record_only_with_a_visible_note(priced_site):
    dash = html.unescape(dashboard(priced_site))
    assert "NBA: units require an odds source — showing record only." in dash
    # ...and the NBA cells carry a straight-up record instead of fake units.
    assert 'class="pl-rec pl-rec-only">1-0<' in dash   # today
    assert 'class="pl-rec pl-rec-only">2-1<' in dash   # week and month


def test_unpriced_league_note_also_appears_on_the_track_record(priced_site):
    assert (
        "NBA: units require an odds source — showing record only."
        in text(priced_site, "track-record.html")
    )


# -------------------------------------------------------------- empty state

def test_dashboard_empty_state_renders_the_shell_with_em_dashes(blank_site):
    dash = dashboard(blank_site)
    assert '<th scope="row">Today</th>' in dash
    assert '<th scope="col">Combined</th>' in dash
    body = re.search(r"<tbody>(.*?)</tbody>", dash, re.S).group(1)
    assert body.count("&#8212;") == 9  # 3 rows x (NFL, NBA, Combined)
    assert "u<" not in dash and "pl-units" not in dash


def test_dashboard_empty_state_explains_itself(blank_site):
    assert (
        "No graded picks yet — P/L starts when the first games are played."
        in html.unescape(dashboard(blank_site))
    )


def test_no_odds_note_is_not_shown_before_anything_is_graded(blank_site):
    assert "units require an odds source" not in read(blank_site, "index.html")


# ----------------------------------------------------- cumulative units chart

def test_cumulative_units_chart_is_present_with_data(priced_site):
    track = read(priced_site, "track-record.html")
    assert "cumulative units over" in track            # the aria-label
    assert "Cumulative units at one flat unit a pick" in track  # the caption
    assert 'class="chart-ref"' in track                # break-even reference
    assert 'viewBox="0 0 640 260"' in track


def test_cumulative_chart_draws_both_series_with_a_legend(priced_site):
    track = read(priced_site, "track-record.html")
    assert 'class="chart-line-2"' in track
    assert 'class="chart-legend"' in track
    assert ">Against the spread</li>" in track
    assert ">Moneyline</li>" in track


def test_cumulative_chart_is_absent_when_nothing_is_graded(blank_site):
    track = read(blank_site, "track-record.html")
    assert "cumulative units" not in track.lower()
    assert "<svg" not in track


def test_cumulative_chart_is_absent_for_an_unpriced_league(priced_site):
    nba = read(priced_site, "track-record.html").split('id="nba-record"')[1]
    assert "cumulative units" not in nba.lower()
    assert 'class="chart-line-2"' not in nba


# ------------------------------------------------------ v1-payload tolerance

def test_v1_payload_builds_without_error(v1_site):
    for name in PAGES + ("style.css", ".nojekyll"):
        assert (v1_site / name).exists(), f"missing {name}"


def test_v1_payload_dashboard_falls_back_to_records(v1_site):
    dash = html.unescape(dashboard(v1_site))
    # Nothing is priced under v1, so both leagues get the record-only note.
    assert "NFL: units require an odds source — showing record only." in dash
    assert "NBA: units require an odds source — showing record only." in dash
    assert "pl-units" not in dash


def test_v1_payload_renders_no_units_chart_and_no_revisions(v1_site):
    track = read(v1_site, "track-record.html")
    assert "cumulative units" not in track.lower()
    assert "rev-details" not in track


# ----------------------------------------------------- docs/data/*.json

def test_build_publishes_the_raw_payloads_as_json(priced_site):
    import json

    for sport, expected in (("nfl", "nfl_priced.json"), ("nba", "nba_unpriced.json")):
        published = priced_site / "data" / f"{sport}.json"
        assert published.exists(), f"docs/data/{sport}.json not written"
        assert json.loads(published.read_text(encoding="utf-8")) == json.loads(
            (FIXTURES / expected).read_text(encoding="utf-8")
        )


def test_missing_payload_leaves_no_stale_data_file(tmp_path):
    out = make_site(tmp_path, nfl="nfl_priced.json", nba=None)
    assert (out / "data" / "nfl.json").exists()
    assert not (out / "data" / "nba.json").exists()


# --------------------------------------------- invariants on the new pages

@pytest.mark.parametrize("page", PAGES)
def test_new_pages_keep_the_disclaimer(priced_site, blank_site, v1_site, page):
    for site in (priced_site, blank_site, v1_site):
        assert DISCLAIMER in read(site, page)


@pytest.mark.parametrize("page", PAGES)
def test_new_pages_leak_no_none_or_nan(priced_site, blank_site, v1_site, page):
    for site in (priced_site, blank_site, v1_site):
        body = read(site, page)
        assert "None" not in body, f"'None' leaked into {page}"
        assert "NaN" not in body, f"'NaN' leaked into {page}"


@pytest.mark.parametrize("page", PAGES)
def test_new_pages_keep_hrefs_relative(priced_site, blank_site, v1_site, page):
    for site in (priced_site, blank_site, v1_site):
        for href in re.findall(r'href="([^"]*)"', read(site, page)):
            assert not href.startswith("/"), f"absolute href {href!r} in {page}"
