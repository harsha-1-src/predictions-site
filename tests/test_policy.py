"""Tests for the prediction-horizon policy.

Three rules are under test here, and they are deliberately not the same rule:

* the **picks page** publishes only games inside the horizon window;
* **units and P/L** exclude picks made outside the policy entirely;
* the **straight-up record** keeps them, and the site says so.

The last two are an asymmetry on purpose (hiding graded picks from the
accuracy record would flatter it), so several tests below assert both halves
together — that excluding a game changed the units and did *not* change the
straight-up record.
"""
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import build as build_mod  # noqa: E402
import units  # noqa: E402
from build import build  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = ("index.html", "track-record.html", "methodology.html")

DISCLAIMER = (
    "These are the outputs of a hobby statistical model, published for fun "
    "and transparency. Not betting advice."
)

# Saturday 2026-10-24, 11:00 Pacific — the clock every suite here pins.
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)

ATS_WIN = 100.0 / 110.0


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
def policy_site(tmp_path_factory):
    """NFL with a live in-window slate, NBA deep in the off-season.

    NFL: two in-window picks, one legacy far-future pick, two graded games in
    policy and two graded out of it. NBA: nothing in window at all, one graded
    game in policy and one out of it.
    """
    return make_site(
        tmp_path_factory.mktemp("policy"),
        "nfl_policy.json",
        "nba_policy_offseason.json",
    )


@pytest.fixture(scope="module")
def legacy_site(tmp_path_factory):
    """Payloads written before the policy contract existed."""
    return make_site(tmp_path_factory.mktemp("legacy"), "nfl.json", "nba.json")


def read(out_dir, name):
    return (out_dir / name).read_text(encoding="utf-8")


def prose(out_dir, name):
    """The page as readable text: tags stripped, entities resolved."""
    stripped = re.sub(r"<[^>]+>", " ", read(out_dir, name))
    return re.sub(r"\s+", " ", html.unescape(stripped))


def picks_section(out_dir, sport):
    parts = read(out_dir, "index.html").split(f'id="{sport}-picks"')
    assert len(parts) == 2, f"{sport} picks section missing"
    return parts[1].split("</section>")[0]


def record_section(out_dir, sport):
    parts = read(out_dir, "track-record.html").split(f'id="{sport}-record"')
    assert len(parts) == 2, f"{sport} record section missing"
    return parts[1].split("</section>")[0]


def rewrite_policy(tmp_path, source, min_days, max_days):
    """Copy a fixture with a different horizon window bolted on."""
    payload = json.loads((FIXTURES / source).read_text(encoding="utf-8"))
    payload["policy"] = {"min_days": min_days, "max_days": max_days}
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "nfl.json").write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "docs"
    build(payload_dir, out, NOW)
    return out


# ------------------------------------------------- (1) picks-page filtering

def test_only_in_window_games_are_published(policy_site):
    nfl = picks_section(policy_site, "nfl")
    assert "DAL @ NYG" in nfl        # horizon 4.2 days
    assert "KC @ BUF" in nfl         # horizon 6.1 days
    assert "SEA @ ARI" not in nfl, "an out-of-window pick reached the picks page"


def test_the_hidden_pick_is_still_in_the_published_payload(policy_site):
    """Filtering is a display decision. The data contract stays complete."""
    data = json.loads(read(policy_site, "data/nfl.json"))
    ids = [g["game_id"] for g in data["upcoming"]]
    assert "2026_16_SEA_ARI" in ids
    assert len(ids) == 3


def test_the_policy_sentence_is_rendered_from_the_payload(policy_site):
    text = prose(policy_site, "index.html")
    assert "Picks are published for games starting 3–7 days out" in text
    assert "games closer than that keep being revised" in text
    assert "nothing further out is predicted" in text


def test_the_policy_sentence_follows_the_payload_and_is_not_hardcoded(tmp_path):
    """Ship a 2-6 day window and the prose says 2-6, everywhere."""
    out = rewrite_policy(tmp_path, "nfl_policy.json", 2, 6)
    index = prose(out, "index.html")
    assert "starting 2–6 days out" in index
    assert "3–7" not in index
    method = prose(out, "methodology.html")
    assert "2–6 days out" in method
    assert "3–7" not in method
    # ...and the track record's exclusion note moves with it.
    assert "current 2–6 day policy" in prose(out, "track-record.html")


def test_whole_number_bounds_never_render_as_floats(tmp_path):
    """The payload may type these as 3.0; a reader must not see '3.0 days'."""
    out = rewrite_policy(tmp_path, "nfl_policy.json", 3.0, 7.0)
    text = prose(out, "index.html")
    assert "starting 3–7 days out" in text
    assert "3.0" not in text and "7.0" not in text


# ------------------------------------------------------- (2) empty states

def test_off_season_empty_state_explains_the_window(policy_site):
    """Case (a): games exist, none of them are close enough yet."""
    nba = picks_section(policy_site, "nba")
    assert 'class="card empty-card"' in nba
    text = html.unescape(re.sub(r"<[^>]+>", " ", nba))
    assert "Nothing is inside the publishing window yet" in text
    assert "further out than 7 days" in text
    assert "3–7 days away" in text
    # calm, not an error, and no game leaked through
    assert "BOS @ NYK" not in nba
    assert "error" not in text.lower()


def test_no_upcoming_at_all_keeps_the_original_message(tmp_path):
    """Case (b): the payload has no upcoming entries to talk about."""
    out = make_site(tmp_path, "empty.json")
    nfl = picks_section(out, "nfl")
    assert "No upcoming picks logged yet" in nfl
    assert "check back at the start of the season" in nfl
    assert "publishing window" not in nfl


def test_the_two_empty_states_read_differently(tmp_path):
    """A reader must be able to tell "not yet published" from "none logged"."""
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    shutil.copyfile(FIXTURES / "empty.json", payload_dir / "nfl.json")
    shutil.copyfile(
        FIXTURES / "nba_policy_offseason.json", payload_dir / "nba.json"
    )
    out = tmp_path / "docs"
    build(payload_dir, out, NOW)

    nfl = picks_section(out, "nfl")
    nba = picks_section(out, "nba")
    assert "No upcoming picks logged yet" in nfl
    assert "No upcoming picks logged yet" not in nba
    assert "Nothing is inside the publishing window yet" in nba
    assert "Nothing is inside the publishing window yet" not in nfl


@pytest.mark.parametrize("page", PAGES)
def test_empty_states_never_leak_python_literals(policy_site, page):
    text = read(policy_site, page)
    assert "None" not in text
    assert "NaN" not in text
    assert "null" not in text


def test_out_of_window_empty_state_without_a_policy_block(tmp_path):
    """in_window flags but no policy: still a sentence, just no numbers."""
    payload = json.loads(
        (FIXTURES / "nba_policy_offseason.json").read_text(encoding="utf-8")
    )
    payload.pop("policy")
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "nba.json").write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "docs"
    build(payload_dir, out, NOW)
    nba = picks_section(out, "nba")
    card = html.unescape(re.sub(r"<[^>]+>", " ", nba))
    assert "Nothing is inside the publishing window yet" in card
    assert "they will appear as those games get closer" in card
    # No numbers were invented to fill the gap, and nothing leaked.
    assert "days" not in card
    assert "None" not in read(out, "index.html")
    assert 'class="policy-note"' not in read(out, "index.html")


# ------------------------------------------------------- (3) back-compat

def test_a_pre_contract_payload_still_shows_every_upcoming_game(legacy_site):
    """No in_window key anywhere means "unknown", not "hide everything"."""
    nfl = picks_section(legacy_site, "nfl")
    assert "DAL @ NYG" in nfl
    assert "KC @ BUF" in nfl
    assert "empty-card" not in nfl
    assert "BOS @ NYK" in picks_section(legacy_site, "nba")


def test_a_pre_contract_payload_renders_no_policy_prose(legacy_site):
    """Nothing to quote, so nothing is claimed — on any page."""
    assert 'class="policy-note"' not in read(legacy_site, "index.html")
    assert "Prediction horizon" not in read(legacy_site, "methodology.html")
    for page in PAGES:
        assert "day policy" not in read(legacy_site, page)


def test_visible_upcoming_treats_a_missing_key_as_visible():
    old = [{"game_id": "a"}, {"game_id": "b"}]
    assert build_mod.visible_upcoming(old) == old
    mixed = [{"game_id": "a", "in_window": True}, {"game_id": "b"}]
    assert [g["game_id"] for g in build_mod.visible_upcoming(mixed)] == ["a"]
    assert build_mod.visible_upcoming([]) == []
    assert build_mod.visible_upcoming(None) == []


# --------------------------------------------------- (4) units exclusions

def game(day="2026-10-11", **kwargs):
    settle = {
        "spread_line": None, "spread_price": None,
        "ml_price": None, "ml_result": None,
    }
    settle.update(kwargs.pop("settle", None) or {})
    entry = {"date": day, "ats_result": None, "su_correct": None, "settle": settle}
    entry.update(kwargs)
    return entry


def priced(day, ats_result, ml_result, out_of_policy=False, su=True):
    return game(
        day,
        ats_result=ats_result,
        su_correct=su,
        out_of_policy=out_of_policy,
        settle={"spread_line": -3.0, "spread_price": -110,
                "ml_price": -110, "ml_result": ml_result},
    )


def test_out_of_policy_flag_defaults_to_false():
    assert units.is_out_of_policy({}) is False
    assert units.is_out_of_policy(None) is False
    assert units.is_out_of_policy({"out_of_policy": False}) is False
    assert units.is_out_of_policy({"out_of_policy": True}) is True


def test_an_out_of_policy_game_is_not_a_bet_on_either_market():
    entry = priced("2026-10-11", "win", "win", out_of_policy=True)
    assert units.ats_pnl(entry) is None
    assert units.ml_pnl(entry) is None
    assert units.entry_units(entry) is None
    assert units.is_priced(entry) is False


def test_out_of_policy_is_an_exclusion_and_never_a_zero_or_a_loss():
    """The whole point: it must not settle at 0.00u, and must not be a loss."""
    only = [priced("2026-10-11", "win", "win", out_of_policy=True)]
    summary = units.summarize(only)
    assert summary == {"ats": None, "ml": None}
    assert units.combine(summary["ats"], summary["ml"]) is None
    assert units.cumulative_series(only) == {}


def test_excluding_out_of_policy_changes_the_units_but_not_the_record():
    """The mixed case, asserted from both sides at once."""
    slate = [
        priced("2026-10-11", "win", "win", su=True),                     # counts
        priced("2026-10-12", "loss", "loss", su=False),                  # counts
        priced("2026-10-13", "win", "win", out_of_policy=True, su=True),  # excluded
    ]
    summary = units.summarize(slate)
    assert summary["ats"]["n"] == 2 and summary["ml"]["n"] == 2
    total = units.combine(summary["ats"], summary["ml"])
    assert total["units"] == pytest.approx(2 * (ATS_WIN - 1.0), abs=1e-6)

    # ...and had the third game counted, the total would have been better.
    if_included = units.summarize([dict(g, out_of_policy=False) for g in slate])
    assert units.combine(
        if_included["ats"], if_included["ml"]
    )["units"] == pytest.approx(4 * ATS_WIN - 2.0, abs=1e-6)

    # The straight-up record is identical either way: 2-1, all three games.
    assert units.su_record(slate) == {"w": 2, "l": 1, "n": 3}
    assert units.su_record(
        [dict(g, out_of_policy=False) for g in slate]
    ) == units.su_record(slate)
    assert units.graded_count(slate) == 3


def test_out_of_policy_games_are_excluded_from_every_window():
    entries = [
        priced("2026-10-24", "win", "win", out_of_policy=True),
        priced("2026-10-24", "loss", "loss"),
    ]
    for window in ("today", "week", "month", "all"):
        block = units.summarize(entries, window, NOW)["ats"]
        assert block["n"] == 1, f"{window} counted an out-of-policy bet"
        assert block["units"] == -1.0
    # ...including the straight-up fallback, which keeps both.
    assert units.su_record(entries, "today", NOW)["n"] == 2


def test_out_of_policy_games_are_absent_from_the_cumulative_chart():
    entries = [
        priced("2026-10-11", "win", "win"),
        priced("2026-10-12", "win", "win", out_of_policy=True),
        priced("2026-10-13", "loss", "loss"),
    ]
    series = units.cumulative_series(entries)
    assert [d for d, _ in series["ats"]] == ["2026-10-11", "2026-10-13"]
    assert series["ats"][-1][1] == pytest.approx(ATS_WIN - 1.0, abs=1e-6)


def test_coverage_reports_odds_gaps_and_policy_gaps_separately():
    entries = [
        priced("2026-10-11", "win", "win"),                       # priced
        game("2026-10-12", su_correct=True),                      # no odds
        priced("2026-10-13", "win", "win", out_of_policy=True),   # out of policy
        game("2026-10-14"),                                       # not graded
    ]
    # The out-of-policy game is not an odds failure and is not counted as one.
    assert units.coverage(entries) == {"graded": 2, "priced": 1, "ungraded": 1}
    assert units.out_of_policy_count(entries) == 1
    assert units.out_of_policy_count(entries, "today", NOW) == 0
    assert units.out_of_policy_count([]) == 0


# ------------------------------------------------ (5) track-record labelling

def test_out_of_policy_rows_stay_visible_and_are_labelled(policy_site):
    nfl = record_section(policy_site, "nfl")
    assert "NYJ @ DEN" in nfl, "an out-of-policy game was hidden from the record"
    assert "SF @ LAR" in nfl
    assert nfl.count('class="row-out-of-policy"') == 2
    assert nfl.count("outside window") == 2
    assert "predicted before the 3-7 day policy; excluded from P/L" in nfl


def test_the_label_is_available_to_a_screen_reader(policy_site):
    nfl = record_section(policy_site, "nfl")
    row = [r for r in nfl.split("<tr") if "NYJ @ DEN" in r][0]
    assert 'class="visually-hidden">, predicted before the 3-7 day policy' in row
    assert 'title="predicted before the 3-7 day policy' in row


def test_an_out_of_policy_row_shows_no_units_and_says_why(policy_site):
    nfl = record_section(policy_site, "nfl")
    row = [r for r in nfl.split("<tr") if "NYJ @ DEN" in r][0]
    assert "units-na" in row
    assert "excluded from P/L" in row
    # never a fabricated settlement, in either direction
    assert "0.00u" not in row and "+0.91u" not in row
    # ...while its straight-up result is still shown as a win
    assert "result-win" in row


def test_the_exclusion_note_counts_the_games_and_names_the_scope(policy_site):
    nfl = prose(policy_site, "track-record.html")
    assert (
        "2 graded games were predicted outside the current 3–7 day policy "
        "and are excluded from P/L" in nfl
    )
    assert "still counted in the straight-up record" in nfl


def test_the_exclusion_note_is_singular_for_a_single_game(policy_site):
    nba = re.sub(r"<[^>]+>", " ", record_section(policy_site, "nba"))
    nba = re.sub(r"\s+", " ", html.unescape(nba))
    assert (
        "1 graded game was predicted outside the current 3–7 day policy "
        "and is excluded from P/L" in nba
    )


def test_no_exclusion_note_when_nothing_is_excluded(tmp_path):
    out = make_site(tmp_path, "nfl_priced.json", "nba_priced.json")
    assert "excluded from P/L" not in read(out, "track-record.html")
    assert "row-out-of-policy" not in read(out, "track-record.html")


def test_units_totals_on_the_page_exclude_the_flagged_games(policy_site):
    """The rendered NFL units are the in-policy figures, not the full slate."""
    nfl = record_section(policy_site, "nfl")
    assert "-0.09u" in nfl        # ATS: one win at -110, one loss
    assert "-0.44u" in nfl        # ML: -180 win, -135 loss
    assert "+0.82u" not in nfl    # what ATS would read if the flags were ignored
    # ...but the straight-up record still counts all four graded games.
    assert "Graded</dt><dd>4</dd>" in nfl.replace("\n", "")
    assert "2&#8211;2" in nfl


def test_the_dashboard_shows_no_units_for_a_day_of_only_excluded_games(policy_site):
    """Oct 24's only NFL game is out of policy: an em dash, not 0.00u."""
    index = read(policy_site, "index.html")
    today = re.search(r'<th scope="row">Today</th>(.*?)</tr>', index, re.S).group(1)
    assert "0.00u" not in today
    assert today.count("&#8212;") == 3


# --------------------------------------------------------- (6) methodology

def test_methodology_explains_the_horizon(policy_site):
    text = prose(policy_site, "methodology.html")
    assert "Prediction horizon" in text
    assert "3–7 days out" in text
    assert "keep changing the inputs" in text or "still moving" in text
    assert "kept and labelled" in text
    assert "excluded from every P/L figure" in text
    assert "counted in the straight-up accuracy record" in text
    assert "Backtests are unaffected" in text


def test_methodology_horizon_section_is_omitted_without_a_policy(legacy_site):
    assert "horizon-method" not in read(legacy_site, "methodology.html")


# ---------------------------------------------------- (7) site invariants

@pytest.mark.parametrize("page", PAGES)
def test_disclaimer_and_stamp_survive(policy_site, page):
    text = read(policy_site, page)
    assert DISCLAIMER in text
    assert re.search(r"Last updated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC from \S+", text)


@pytest.mark.parametrize("page", PAGES)
def test_hrefs_stay_relative(policy_site, page):
    for href in re.findall(r'href="([^"]*)"', read(policy_site, page)):
        assert not href.startswith("/"), f"absolute href {href!r} in {page}"


def test_new_styles_are_theme_aware(policy_site):
    """The badge and the notes must be legible in dark mode too, which here
    means: they take their colours from variables the dark block redefines."""
    css = read(policy_site, "style.css")
    assert "@media (prefers-color-scheme: dark)" in css
    badge = css.split(".badge-policy {")[1].split("}")[0]
    assert "var(--ink-muted)" in badge and "var(--border)" in badge
    assert "#" not in badge, "hardcoded colour in .badge-policy"
    note = css.split(".policy-note {")[1].split("}")[0]
    assert "var(--ink-secondary)" in note and "#" not in note
    row = css.split("table.history tr.row-out-of-policy td {")[1].split("}")[0]
    assert "var(--ink-secondary)" in row and "#" not in row
