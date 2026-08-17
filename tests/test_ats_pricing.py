"""Rendering tests for priced spreads and per-game odds coverage.

The NBA payload used to carry no spread and no price at all. It now carries
both, from live odds APIs, and coverage is per game — so a slate can be partly
priced. Everything here checks that the site is driven by what is in the
payload rather than by which league it came from.
"""
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

# Saturday 2026-10-24, 11:00 Pacific — the same clock the other suites pin.
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)

RECORD_ONLY = "units require an odds source — showing record only"


def make_site(tmp_path, nfl, nba, now=NOW):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    shutil.copyfile(FIXTURES / nfl, payload_dir / "nfl.json")
    shutil.copyfile(FIXTURES / nba, payload_dir / "nba.json")
    out = tmp_path / "docs"
    build(payload_dir, out, now)
    return out


@pytest.fixture(scope="module")
def mixed_site(tmp_path_factory):
    """Both leagues priced; both have exactly one ungraded-for-units game.

    The NBA fixture is the interesting one: one game with a spread and a
    moneyline (at -105 and -140), one with a spread and no moneyline (+100),
    one with neither, plus a push.
    """
    return make_site(
        tmp_path_factory.mktemp("mixed"), "nfl_priced.json", "nba_priced.json"
    )


@pytest.fixture(scope="module")
def unpriced_nba_site(tmp_path_factory):
    """The old world: NBA with no odds at all, for the record-only path."""
    return make_site(
        tmp_path_factory.mktemp("unpriced"), "nfl_priced.json", "nba_unpriced.json"
    )


def read(out_dir, name):
    return (out_dir / name).read_text(encoding="utf-8")


def text(out_dir, name):
    return html.unescape(read(out_dir, name))


def prose(out_dir, name):
    """The page as readable text: tags stripped, entities resolved, whitespace
    collapsed. Lets prose assertions ignore where the source wraps and which
    words happen to be wrapped in <strong>."""
    stripped = re.sub(r"<[^>]+>", "", read(out_dir, name))
    return re.sub(r"\s+", " ", html.unescape(stripped))


def dashboard(out_dir):
    match = re.search(
        r'<section class="dashboard".*?</section>', read(out_dir, "index.html"), re.S
    )
    assert match, "dashboard section missing"
    return match.group(0)


def row(out_dir, label):
    match = re.search(
        rf'<th scope="row">{label}</th>(.*?)</tr>', dashboard(out_dir), re.S
    )
    assert match, f"dashboard row {label!r} missing"
    return match.group(1)


def section(out_dir, sport):
    """One league's track-record section."""
    parts = read(out_dir, "track-record.html").split(f'id="{sport}-record"')
    assert len(parts) == 2, f"{sport} section missing"
    return parts[1].split("</section>")[0]


def thead(section_html):
    match = re.search(r'<table class="history">.*?<thead>(.*?)</thead>', section_html, re.S)
    assert match, "history table head missing"
    return re.findall(r'<th scope="col">([^<]*)</th>', match.group(1))


# ------------------------------------------------- NBA units on the dashboard

def test_nba_shows_real_units_now_that_its_games_are_priced(mixed_site):
    dash = dashboard(mixed_site)
    # Today: LAL/DEN only — ATS win at -105 (+0.9524) plus ML win at -140
    # (+0.7143) = +1.67u on 2-0-0.
    nba_today = row(mixed_site, "Today").split("</td>")[1]
    assert "+1.67u" in nba_today and ">2-0-0<" in nba_today
    # This week adds the +100 spread loss (no moneyline on that game): +0.67u.
    assert "+0.67u" in row(mixed_site, "This week")
    # This month adds the Oct 5 push plus its -190 moneyline win: +1.19u, 3-1-1.
    month = row(mixed_site, "This month")
    assert "+1.19u" in month and ">3-1-1<" in month
    assert 'class="pl-rec pl-rec-only"' not in dash, "no league is record-only here"


def test_a_non_minus_110_spread_price_is_visible_in_the_rendered_units(mixed_site):
    """-105 pays +0.952, not the -110 convention's +0.909. If the site had
    silently assumed -110 the LAL/DEN row would read +1.62u, not +1.67u."""
    nba = section(mixed_site, "nba")
    assert "+1.67u" in nba
    assert "+1.62u" not in nba


def test_combined_column_adds_both_priced_leagues(mixed_site):
    today = row(mixed_site, "Today")
    assert "+1.24u" in today   # NFL
    assert "+1.67u" in today   # NBA
    assert "+2.91u" in today   # combined
    assert ">4-0-0<" in today


# ---------------------------------------------------- the partial-odds note

def test_partial_coverage_note_names_the_ungraded_games(mixed_site):
    dash = html.unescape(dashboard(mixed_site))
    assert (
        "NBA: 1 of 4 graded games had no odds logged and are ungraded for units."
        in dash
    )
    # ...and the same rule applies to NFL, which also has one unpriced game.
    assert (
        "NFL: 1 of 7 graded games had no odds logged and are ungraded for units."
        in dash
    )


def test_partial_coverage_never_downgrades_a_league_to_record_only(mixed_site):
    assert RECORD_ONLY not in text(mixed_site, "index.html")
    assert RECORD_ONLY not in text(mixed_site, "track-record.html")


def test_the_partial_note_also_appears_on_the_track_record(mixed_site):
    nba = html.unescape(section(mixed_site, "nba"))
    assert "1 of 4 graded games had no odds logged" in nba


def test_a_genuinely_unpriced_league_still_gets_the_record_only_note(unpriced_nba_site):
    dash = html.unescape(dashboard(unpriced_nba_site))
    assert f"NBA: {RECORD_ONLY}." in dash
    assert "NBA: 0 of" not in dash, "record-only, not a zero-coverage count"
    assert 'class="pl-rec pl-rec-only">1-0<' in dash


def test_a_fully_priced_league_gets_no_note_at_all(tmp_path):
    """Coverage notes are earned by missing odds, not printed by default."""
    import json

    payload = json.loads((FIXTURES / "nba_priced.json").read_text(encoding="utf-8"))
    payload["history"] = [g for g in payload["history"] if g["ats_result"]]
    payload["record"]["graded"] = len(payload["history"])
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "nba.json").write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "docs"
    build(payload_dir, out, NOW)
    dash = html.unescape(
        re.search(
            r'<section class="dashboard".*?</section>',
            (out / "index.html").read_text(encoding="utf-8"),
            re.S,
        ).group(0)
    )
    assert "ungraded for units" not in dash
    assert RECORD_ONLY not in dash


# ------------------------------------------- NBA gets the NFL breakdown too

def test_nba_history_table_has_the_same_columns_as_nfl(mixed_site):
    nfl_cols = thead(section(mixed_site, "nfl"))
    nba_cols = thead(section(mixed_site, "nba"))
    assert nba_cols == nfl_cols
    assert nba_cols == ["Date", "Matchup", "Pick", "Result", "Score", "ATS", "Units"]


def test_nba_summary_gets_the_ats_and_ml_breakdown(mixed_site):
    nba = html.unescape(section(mixed_site, "nba"))
    # The fixture's record.ats is null on purpose: the breakdown must come from
    # the settle blocks, so the site is ahead of the model repo, not behind it.
    assert "Against the spread</dt><dd>1–1–1 (50.0%)" in nba
    assert "Units · against the spread" in nba
    assert "Units · moneyline" in nba
    assert "1-1-1, ROI -1.6%" in nba
    assert "2-0-0, ROI 62.0%" in nba


def test_nba_now_draws_a_cumulative_units_chart_with_both_markets(mixed_site):
    nba = section(mixed_site, "nba")
    assert "cumulative units over" in nba
    assert 'class="chart-line-2"' in nba          # two market series
    assert 'class="chart-legend"' in nba


def test_an_unpriced_league_has_neither_a_units_column_nor_a_chart(unpriced_nba_site):
    nba = section(unpriced_nba_site, "nba")
    assert "Units" not in thead(nba)
    assert "cumulative units" not in nba.lower()


# ------------------------------------------ ungraded-for-units, made visible

def ungraded_row(section_html, matchup):
    match = re.search(rf"<tr>(?:(?!</tr>).)*{matchup}.*?</tr>", section_html, re.S)
    assert match, f"{matchup} row missing"
    return match.group(0)


@pytest.mark.parametrize("sport,matchup", [("nba", "MIL @ CHI"), ("nfl", "MIA @ NE")])
def test_an_unpriced_game_is_marked_not_shown_as_a_loss(mixed_site, sport, matchup):
    tr = ungraded_row(section(mixed_site, sport), matchup)
    assert 'class="pl-cell units-na"' in tr
    assert 'title="no odds logged &#8212; ungraded for units"' in tr
    assert "ungraded for units, no odds logged" in tr   # screen-reader text
    assert "&#8212;" in tr                              # the visible em dash
    # Emphatically not a settled result of any kind.
    assert "-1.00u" not in tr and "0.00u" not in tr
    assert "pl-neg" not in tr and "pl-units" not in tr


def test_the_priced_rows_around_it_still_show_their_units(mixed_site):
    nba = section(mixed_site, "nba")
    assert "+1.67u" in ungraded_row(nba, "LAL @ DEN")
    assert "-1.00u" in ungraded_row(nba, "GSW @ PHX")   # +100 spread loss
    assert "+0.53u" in ungraded_row(nba, "BOS @ NYK")   # ATS push + -190 ML win


def test_the_ungraded_game_is_still_in_the_straight_up_record(mixed_site):
    """It was played and scored; it just has no price. Both facts are shown."""
    nba = html.unescape(section(mixed_site, "nba"))
    assert "Graded</dt><dd>4" in nba
    assert "Straight-up</dt><dd>3–1 (75.0%)" in nba


# --------------------------------------------------- the methodology promise

def test_methodology_states_the_nfl_line_only_convention(mixed_site):
    page = prose(mixed_site, "methodology.html")
    assert "NFL spreads come from nflverse historical closing lines" in page
    assert "nflverse does not publish the price that went with it" in page
    assert "settled at the standard -110 convention" in page
    assert "a stated assumption, not a recorded price" in page


def test_methodology_names_both_nba_odds_providers_and_the_exact_price_rule(mixed_site):
    page = prose(mixed_site, "methodology.html")
    assert "NBA moneylines and spreads come from live odds APIs read at prediction time" in page
    assert "ParlayAPI first, with The Odds API as the fallback" in page
    assert "free tiers" in page
    assert "settle at the exact price logged with the pick" in page
    assert "often -110 on a spread, but never assumed to be" in page


def test_methodology_promises_prices_are_never_back_filled(mixed_site):
    page = prose(mixed_site, "methodology.html")
    assert "recorded alongside the pick before the game" in page
    assert "never back-filled or invented afterwards" in page
    assert "Coverage is per game, not per league" in page
    assert "shown as ungraded for units" in page
    assert "rather than being assumed into a price it never had" in page


def test_methodology_keeps_the_honest_fifty_percent_framing(mixed_site):
    page = text(mixed_site, "methodology.html")
    assert "Neither model beats the betting market" in page
    assert "near 50% against the spread" in page
    assert "negative return on investment" in page
    assert "50.6% ATS, -3.4% ROI" in page   # the NBA backtest line, unchanged


# ---------------------------------------------------------------- invariants

@pytest.mark.parametrize("page", PAGES)
def test_pages_keep_the_disclaimer(mixed_site, unpriced_nba_site, page):
    for site in (mixed_site, unpriced_nba_site):
        assert DISCLAIMER in read(site, page)


@pytest.mark.parametrize("page", PAGES)
def test_pages_leak_no_none_or_nan(mixed_site, unpriced_nba_site, page):
    for site in (mixed_site, unpriced_nba_site):
        body = read(site, page)
        assert "None" not in body, f"'None' leaked into {page}"
        assert "NaN" not in body, f"'NaN' leaked into {page}"


@pytest.mark.parametrize("page", PAGES)
def test_pages_keep_hrefs_relative(mixed_site, unpriced_nba_site, page):
    for site in (mixed_site, unpriced_nba_site):
        for href in re.findall(r'href="([^"]*)"', read(site, page)):
            assert not href.startswith("/"), f"absolute href {href!r} in {page}"


def test_the_nba_slate_renders_its_new_market_lines_on_the_index(mixed_site):
    index = text(mixed_site, "index.html")
    assert "Model line BOS -4.5" in index
    assert "market BOS -2.5" in index
    assert "Moneyline -125" in index
    # The unpriced upcoming game still renders, just without any line at all.
    assert "SAC @ POR" in index
