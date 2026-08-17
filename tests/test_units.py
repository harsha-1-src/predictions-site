"""Tests for units.py — the flat-1u profit and loss engine."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import units  # noqa: E402

ATS_WIN = 100.0 / 110.0  # +0.9091


def game(day="2026-10-11", **kwargs):
    """A history entry; ``settle`` keys are merged over an all-null default."""
    settle = {
        "spread_line": None,
        "spread_price": None,
        "ml_price": None,
        "ml_result": None,
    }
    settle.update(kwargs.pop("settle", None) or {})
    entry = {"date": day, "ats_result": None, "su_correct": None, "settle": settle}
    entry.update(kwargs)
    return entry


def ats(day, result, line=-3.0, price=-110):
    return game(day, ats_result=result, settle={"spread_line": line, "spread_price": price})


def ml(day, result, price):
    return game(day, settle={"ml_price": price, "ml_result": result})


# ------------------------------------------------------------- american odds

@pytest.mark.parametrize(
    "price,expected",
    [(-110, 0.909091), (-180, 0.555556), (-300, 0.333333), (100, 1.0),
     (135, 1.35), (250, 2.5)],
)
def test_american_profit(price, expected):
    assert units.american_profit(price) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("price", [0, None])
def test_american_profit_rejects_non_prices(price):
    with pytest.raises(ValueError):
        units.american_profit(price)


# ------------------------------------------------------------------- ATS math

def test_ats_win_loss_push_arithmetic_is_exact():
    entries = [
        ats("2026-10-11", "win"),
        ats("2026-10-11", "loss"),
        ats("2026-10-11", "push"),
    ]
    assert units.ats_pnl(entries[0])[1] == pytest.approx(0.9091, abs=1e-4)
    assert units.ats_pnl(entries[1])[1] == -1.0
    assert units.ats_pnl(entries[2])[1] == 0.0

    block = units.summarize(entries)["ats"]
    assert (block["w"], block["l"], block["p"], block["n"]) == (1, 1, 1, 3)
    assert block["units"] == pytest.approx(ATS_WIN - 1.0, abs=1e-6)
    assert block["roi"] == pytest.approx((ATS_WIN - 1.0) / 3, abs=1e-6)


def test_ats_uses_the_logged_price_when_it_is_not_minus_110():
    entry = ats("2026-10-11", "win", price=-105)
    assert units.ats_pnl(entry)[1] == pytest.approx(100 / 105, abs=1e-9)


def test_ats_defaults_to_minus_110_when_no_price_logged():
    entry = ats("2026-10-11", "win", price=None)
    assert units.ats_pnl(entry)[1] == pytest.approx(ATS_WIN, abs=1e-9)


@pytest.mark.parametrize("result", ["no-line", "no-pick", None])
def test_ats_non_results_are_not_bets(result):
    entry = ats("2026-10-11", result)
    assert units.ats_pnl(entry) is None


def test_ats_without_a_logged_line_is_not_a_bet_even_if_graded():
    entry = game("2026-10-11", ats_result="win")  # settle.spread_line is null
    assert units.ats_pnl(entry) is None
    assert units.summarize([entry])["ats"] is None


# -------------------------------------------------------------------- ML math

def test_ml_negative_and_positive_prices():
    assert units.ml_pnl(ml("2026-10-11", "win", -180))[1] == pytest.approx(0.555556, abs=1e-6)
    assert units.ml_pnl(ml("2026-10-11", "win", 120))[1] == pytest.approx(1.2, abs=1e-9)
    assert units.ml_pnl(ml("2026-10-11", "loss", -180))[1] == -1.0
    assert units.ml_pnl(ml("2026-10-11", "loss", 120))[1] == -1.0
    assert units.ml_pnl(ml("2026-10-11", "push", 120))[1] == 0.0


def test_ml_mixed_odds_across_games():
    entries = [
        ml("2026-10-11", "win", -180),   # +0.555556
        ml("2026-10-11", "loss", -135),  # -1.0
        ml("2026-10-12", "win", 120),    # +1.2
        ml("2026-10-12", "win", -260),   # +0.384615
        ml("2026-10-13", "loss", 135),   # -1.0
        ml("2026-10-13", "win", -300),   # +0.333333
    ]
    block = units.summarize(entries)["ml"]
    assert (block["w"], block["l"], block["p"], block["n"]) == (4, 2, 0, 6)
    expected = 100 / 180 - 1 + 1.2 + 100 / 260 - 1 + 100 / 300
    assert block["units"] == pytest.approx(expected, abs=1e-6)
    assert block["roi"] == pytest.approx(expected / 6, abs=1e-6)


def test_unpriced_games_are_excluded_from_counts_entirely():
    entries = [
        ml("2026-10-11", "win", -180),
        game("2026-10-11", su_correct=True),   # NBA-style: no prices at all
        game("2026-10-12", su_correct=False),
    ]
    block = units.summarize(entries)["ml"]
    assert block["n"] == 1, "unpriced games must not pad the bet count"
    assert block["units"] == pytest.approx(100 / 180, abs=1e-6)


def test_priced_but_ungraded_game_is_not_a_bet_yet():
    entry = game("2026-10-11", settle={"ml_price": -150, "ml_result": None})
    assert units.ml_pnl(entry) is None


# --------------------------------------------- zero priced games -> None


def test_league_with_zero_priced_games_reports_none_not_zero():
    nba = [
        game("2026-10-21", su_correct=True),
        game("2026-10-23", su_correct=False),
    ]
    summary = units.summarize(nba)
    assert summary["ats"] is None
    assert summary["ml"] is None
    # and specifically NOT a zeroed block
    assert summary["ml"] != {"units": 0.0, "w": 0, "l": 0, "p": 0, "n": 0, "roi": 0.0}
    assert units.su_record(nba) == {"w": 1, "l": 1, "n": 2}


def test_combine_of_all_empty_blocks_is_none():
    assert units.combine(None, None) is None


def test_combine_merges_markets_and_leagues():
    nfl = units.summarize([ats("2026-10-11", "win"), ml("2026-10-11", "loss", -150)])
    merged = units.combine(nfl["ats"], nfl["ml"], None)
    assert merged["n"] == 2
    assert merged["w"] == 1 and merged["l"] == 1 and merged["p"] == 0
    assert merged["units"] == pytest.approx(ATS_WIN - 1.0, abs=1e-6)


# ------------------------------------------------------------ v1 tolerance

def test_v1_entries_without_settle_or_revisions_are_tolerated():
    v1 = [
        {"date": "2026-09-06", "ats_result": "win", "su_correct": True},
        {"date": "2026-09-07", "ats_result": "loss", "su_correct": False},
    ]
    summary = units.summarize(v1)
    assert summary == {"ats": None, "ml": None}
    assert units.su_record(v1) == {"w": 1, "l": 1, "n": 2}
    assert units.cumulative_series(v1) == {}


# ------------------------------------------------------------ PST windows

def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_pacific_midnight_boundary_picks_the_right_day():
    # 07:59:59Z on Jan 1 is still 23:59:59 on Dec 31 in Pacific (PST, UTC-8).
    assert units.pacific_today(utc("2027-01-01T07:59:59")) == date(2026, 12, 31)
    assert units.pacific_today(utc("2027-01-01T08:00:00")) == date(2027, 1, 1)


def test_pacific_midnight_boundary_in_summer_is_utc_minus_seven():
    assert units.pacific_today(utc("2026-07-02T06:59:59")) == date(2026, 7, 1)
    assert units.pacific_today(utc("2026-07-02T07:00:00")) == date(2026, 7, 2)


def test_new_year_boundary_splits_day_week_and_month():
    dec31 = ats("2026-12-31", "win")
    jan1 = ats("2027-01-01", "loss")
    entries = [dec31, jan1]

    just_before = utc("2027-01-01T07:59:59")  # Pacific: Thu 2026-12-31
    just_after = utc("2027-01-01T08:00:00")   # Pacific: Fri 2027-01-01

    assert units.summarize(entries, "today", just_before)["ats"]["n"] == 1
    assert units.summarize(entries, "today", just_before)["ats"]["w"] == 1
    assert units.summarize(entries, "today", just_after)["ats"]["n"] == 1
    assert units.summarize(entries, "today", just_after)["ats"]["l"] == 1

    # Dec is one month, Jan another — never pooled.
    assert units.summarize(entries, "month", just_before)["ats"]["n"] == 1
    assert units.summarize(entries, "month", just_after)["ats"]["n"] == 1

    # ...but Dec 31 2026 (Thu) and Jan 1 2027 (Fri) share a Mon-Sun week.
    assert units.summarize(entries, "week", just_before)["ats"]["n"] == 2
    assert units.summarize(entries, "week", just_after)["ats"]["n"] == 2

    assert units.summarize(entries, "all")["ats"]["n"] == 2


def test_week_starts_on_monday():
    # 2026-10-24 is a Saturday; its Pacific week is Mon 19th .. Sun 25th.
    start, end = units.window_bounds("week", utc("2026-10-24T18:00:00"))
    assert (start, end) == (date(2026, 10, 19), date(2026, 10, 25))
    assert start.strftime("%a") == "Mon" and end.strftime("%a") == "Sun"

    # Monday itself is the first day of its own week, not the last of the old.
    start, _ = units.window_bounds("week", utc("2026-10-19T18:00:00"))
    assert start == date(2026, 10, 19)

    # Sunday belongs to the week that started six days earlier.
    start, _ = units.window_bounds("week", utc("2026-10-25T18:00:00"))
    assert start == date(2026, 10, 19)


def test_month_bounds_cover_the_whole_calendar_month():
    assert units.window_bounds("month", utc("2026-02-14T18:00:00")) == (
        date(2026, 2, 1),
        date(2026, 2, 28),
    )
    assert units.window_bounds("month", utc("2026-12-14T18:00:00")) == (
        date(2026, 12, 1),
        date(2026, 12, 31),
    )


def test_all_window_is_unbounded_and_keeps_undated_entries():
    undated = ats(None, "win")
    assert units.window_bounds("all") == (None, None)
    assert units.summarize([undated], "all")["ats"]["n"] == 1
    assert units.summarize([undated], "today", utc("2026-10-24T18:00:00"))["ats"] is None


def test_unknown_window_is_rejected():
    with pytest.raises(ValueError):
        units.window_bounds("fortnight")


# --------------------------------------------------- the tz fallback itself

def test_pacific_approximation_matches_the_us_dst_rule():
    """The tzdata-less fallback still puts DST in the right place."""
    tz = units._PacificApprox()
    winter = utc("2026-01-15T20:00:00").astimezone(tz)
    summer = utc("2026-07-15T20:00:00").astimezone(tz)
    assert winter.utcoffset().total_seconds() == -8 * 3600
    assert winter.tzname() == "PST"
    assert summer.utcoffset().total_seconds() == -7 * 3600
    assert summer.tzname() == "PDT"
    # DST starts the second Sunday in March, ends the first Sunday in November.
    assert utc("2026-03-08T09:59:00").astimezone(tz).tzname() == "PST"
    assert utc("2026-03-08T11:00:00").astimezone(tz).tzname() == "PDT"
    assert utc("2026-11-01T08:00:00").astimezone(tz).tzname() == "PDT"
    assert utc("2026-11-01T10:00:00").astimezone(tz).tzname() == "PST"


# ----------------------------------------------------------- cumulative plot

def test_cumulative_series_accumulates_and_collapses_by_date():
    entries = [
        ats("2026-10-11", "win"),
        ats("2026-10-11", "loss"),
        ats("2026-10-12", "win"),
    ]
    series = units.cumulative_series(entries)
    assert list(series) == ["ats"]
    assert [d for d, _ in series["ats"]] == ["2026-10-11", "2026-10-12"]
    assert series["ats"][0][1] == pytest.approx(ATS_WIN - 1.0, abs=1e-6)
    assert series["ats"][1][1] == pytest.approx(2 * ATS_WIN - 1.0, abs=1e-6)


def test_cumulative_series_has_both_markets_when_both_are_priced():
    entries = [
        game(
            "2026-10-11",
            ats_result="win",
            settle={
                "spread_line": -3.0,
                "spread_price": -110,
                "ml_price": -150,
                "ml_result": "win",
            },
        )
    ]
    series = units.cumulative_series(entries)
    assert sorted(series) == ["ats", "ml"]


# --------------------------------------------------------- now-coercion (API)
def test_coerce_now_accepts_the_same_iso_string_as_the_cli():
    """build(now=...) and --now must agree; a bare ISO string used to
    raise AttributeError deep inside window_bounds."""
    from datetime import datetime, timezone

    import units

    got = units.coerce_now("2026-10-24T18:00:00Z")
    assert got == datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
    assert units.coerce_now("2026-10-24T18:00:00+00:00") == got
    # naive is read as UTC; aware is preserved; None is the live clock
    assert units.coerce_now(datetime(2026, 10, 24, 18, 0)) == got
    assert units.coerce_now(got) == got
    assert units.coerce_now().tzinfo is not None
    # and the Pacific date derived from the string is the expected one
    assert str(units.pacific_today("2026-10-24T18:00:00Z")) == "2026-10-24"
    assert str(units.pacific_today("2026-10-24T05:00:00Z")) == "2026-10-23"
