"""Tests for the closing-line-value (CLV) block on the track record.

CLV is **display only** on this site: every number comes from the payload's
``record.clv`` and per-game ``clv`` blocks. So the tests here are about
honesty of presentation rather than arithmetic:

* what is shown when the data is there (mean CLV, the directional hit rate
  with its n, the no-move count kept *separate* from that hit rate, the
  bucket table, and the large-disagreement slice);
* what is shown when a piece is missing (`large_disagreement: null` -> that
  line simply does not exist, `n_graded: 0` -> a sentence, never zeros);
* what happens to a payload with no CLV at all, which must render **exactly**
  as it did before CLV existed. That one is asserted byte-for-byte.

It is a paper trail and never a betting system, so the page says so.
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
from build import build  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = ("index.html", "track-record.html", "methodology.html")

DISCLAIMER = (
    "These are the outputs of a hobby statistical model, published for fun "
    "and transparency. Not betting advice."
)

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
BUILT_AT = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)
PUBLISHER = "fixturebox"


def make_site(tmp_path, nfl=None, nba=None, name="docs"):
    payload_dir = tmp_path / f"payloads-{name}"
    payload_dir.mkdir()
    if nfl:
        shutil.copyfile(FIXTURES / nfl, payload_dir / "nfl.json")
    if nba:
        shutil.copyfile(FIXTURES / nba, payload_dir / "nba.json")
    out = tmp_path / name
    build(payload_dir, out, NOW, built_at=BUILT_AT, publisher=PUBLISHER)
    return out


def site_from(tmp_path, payloads: dict, name="docs"):
    """Build from in-memory payloads, so a test can bend one key."""
    payload_dir = tmp_path / f"payloads-{name}"
    payload_dir.mkdir()
    for sport, payload in payloads.items():
        (payload_dir / f"{sport}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    out = tmp_path / name
    build(payload_dir, out, NOW, built_at=BUILT_AT, publisher=PUBLISHER)
    return out


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def strip_clv(obj):
    """The same payload as if CLV had never been added to the contract."""
    if isinstance(obj, dict):
        return {k: strip_clv(v) for k, v in obj.items() if k != "clv"}
    if isinstance(obj, list):
        return [strip_clv(v) for v in obj]
    return obj


def read(out_dir, name):
    return (out_dir / name).read_text(encoding="utf-8")


def prose(text):
    """Readable text: tags stripped, entities resolved."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))


def record_section(out_dir, sport):
    parts = read(out_dir, "track-record.html").split(f'id="{sport}-record"')
    assert len(parts) == 2, f"{sport} record section missing"
    return parts[1].split("</section>\n<section")[0]


def clv_section(out_dir, sport):
    section = record_section(out_dir, sport)
    assert '<section class="clv"' in section, f"no CLV block for {sport}"
    return section.split('<section class="clv"')[1].split("</section>")[0]


@pytest.fixture(scope="module")
def clv_site(tmp_path_factory):
    """NFL: priced snapshots, a large-disagreement slice, two incomplete picks.
    NBA: line-only snapshots (no prices, so no cents) and no such slice."""
    return make_site(
        tmp_path_factory.mktemp("clv"), "nfl_clv.json", "nba_clv.json"
    )


# ------------------------------------------------------ (1) the block itself

def test_the_clv_block_sits_with_the_units_on_the_track_record(clv_site):
    """Next to the P/L presentation, in the same league section, above the
    per-game table — not on a page of its own."""
    section = record_section(clv_site, "nfl")
    assert section.index('class="stat-grid"') < section.index('class="clv"')
    assert section.index('class="clv"') < section.index('table class="history"')
    assert "Closing line value" in section


def test_mean_clv_leads_in_percentage_points_with_cents_beside_it(clv_site):
    nfl = clv_section(clv_site, "nfl")
    assert "Mean CLV" in nfl
    assert "+1.20 pp" in nfl
    assert "+0.2 cents" in nfl


def test_a_league_with_no_cents_shows_the_percentage_points_alone(clv_site):
    """NBA's snapshots carry no price, so there are no cents to show — and
    none are invented."""
    nba = clv_section(clv_site, "nba")
    assert "+0.42 pp" in nba
    assert "cents" not in nba


def test_the_directional_hit_rate_is_shown_with_its_n(clv_site):
    nfl = prose(clv_section(clv_site, "nfl"))
    assert "Closed toward the model 50.0%" in nfl
    assert "n = 4 lines that moved" in nfl


def test_no_move_is_reported_separately_and_never_folded_into_the_hit_rate(clv_site):
    """A line that never moved is not a miss. It gets its own figure, and the
    hit rate's n is the moved lines only: 5 graded, 1 no-move, n = 4."""
    nfl = prose(clv_section(clv_site, "nfl"))
    assert "No line move 1 not counted in the hit rate" in nfl
    # ...and the hit-rate denominator excludes it.
    assert "n = 4 lines that moved" in nfl
    assert "n = 5" not in nfl


def test_mean_line_movement_is_shown_in_points(clv_site):
    assert "Mean line move" in clv_section(clv_site, "nfl")
    assert "+0.40 pts" in clv_section(clv_site, "nfl")


def test_the_bucket_table_renders_every_disagreement_bucket(clv_site):
    nfl = clv_section(clv_site, "nfl")
    assert 'class="clv-table"' in nfl
    body = nfl.split("<tbody>")[1].split("</tbody>")[0]
    rows = re.findall(r"<tr>(.*?)</tr>", body, re.S)
    assert len(rows) == 3
    assert ">0-1<" in rows[0] and ">1-2<" in rows[1] and ">2+<" in rows[2]
    biggest = prose(rows[2])
    assert "2+ 2 100.0% +1.75 pts +5.25 pp" in biggest


def test_the_ungraded_count_is_disclosed_rather_than_dropped(clv_site):
    """Picks with only one snapshot are skipped — and counted out loud."""
    nfl = prose(clv_section(clv_site, "nfl"))
    assert "2 picks have only one of the two snapshots and are not counted above" in nfl
    nba = prose(clv_section(clv_site, "nba"))
    assert "1 pick has only one of the two snapshots and is not counted above" in nba


def test_the_block_says_it_is_a_paper_trail_not_a_betting_system(clv_site):
    for sport in ("nfl", "nba"):
        text = prose(clv_section(clv_site, sport))
        assert "A paper trail, not a betting system" in text
        assert "Nothing is staked and no bet is placed" in text


def test_the_clv_block_suggests_no_action_anywhere_on_the_site(clv_site):
    """No hedging, no cash-out, no alerts, no bet sizing. Ever."""
    for page in PAGES:
        text = prose(read(clv_site, page)).lower()
        for word in ("hedge", "cash out", "cash-out", "alert", "bet size",
                     "stake size", "bankroll", "kelly"):
            assert word not in text, f"{word!r} leaked onto {page}"


# --------------------------------------------- (2) the large-disagreement line

def test_the_large_disagreement_slice_is_its_own_labelled_line(clv_site):
    nfl = clv_section(clv_site, "nfl")
    assert 'class="clv-large"' in nfl
    line = prose(nfl.split('class="clv-large"')[1].split("</p>")[0])
    assert "Large disagreement (|d|>2)" in line
    assert "2 picks" in line
    assert "closed toward the model 100.0%" in line
    assert "mean line move +1.75 pts" in line
    assert "live hypothesis" in line


def test_a_null_large_disagreement_renders_no_line_and_no_stray_label(clv_site):
    """NBA supplies `large_disagreement: null`. Nothing is drawn — not the
    line, not the label, not an empty container."""
    nba = clv_section(clv_site, "nba")
    assert "clv-large" not in nba
    assert "Large disagreement" not in nba
    assert "live hypothesis" not in nba
    # ...while the rest of NBA's CLV block is fully present.
    assert 'class="clv-table"' in nba


def test_the_slice_is_driven_by_the_data_and_not_by_the_league(tmp_path):
    """Move the slice from NFL to NBA and the line moves with it."""
    nfl = load("nfl_clv.json")
    nba = load("nba_clv.json")
    nba["record"]["clv"]["large_disagreement"] = nfl["record"]["clv"].pop(
        "large_disagreement"
    )
    nfl["record"]["clv"]["large_disagreement"] = None
    out = site_from(tmp_path, {"nfl": nfl, "nba": nba})
    assert "Large disagreement" not in clv_section(out, "nfl")
    assert "Large disagreement" in clv_section(out, "nba")


# ------------------------------------------------------- (3) the empty state

def empty_clv_payload():
    """A league that has graded picks but no complete CLV snapshot yet."""
    payload = strip_clv(load("nfl_clv.json"))
    payload["record"]["clv"] = {
        "n_graded": 0,
        "n_ungraded": 3,
        "hit_rate": None,
        "no_move": 0,
        "mean_line_move": None,
        "mean_clv_pp": None,
        "mean_clv_cents": None,
        "buckets": [],
        "large_disagreement": None,
    }
    return payload


def test_the_empty_state_is_a_calm_sentence_and_not_a_row_of_zeros(tmp_path):
    out = site_from(tmp_path, {"nfl": empty_clv_payload()})
    nfl = clv_section(out, "nfl")
    text = prose(nfl)
    assert (
        "No CLV data yet — CLV is recorded from the first morning snapshot onward"
        in text
    )
    # Nothing is fabricated: no zero measurements, no empty furniture.
    assert "0.00 pp" not in nfl and "0.00 pts" not in nfl
    assert "0.0%" not in nfl
    assert "clv-table" not in nfl
    assert "clv-grid" not in nfl
    assert "Mean CLV" not in nfl
    # ...and the picks that are waiting on a second snapshot are still counted.
    assert "3 picks have only one of the two snapshots" in text


def test_the_empty_state_does_not_touch_the_units_shown_beside_it(tmp_path):
    out = site_from(tmp_path, {"nfl": empty_clv_payload()})
    nfl = record_section(out, "nfl")
    assert "+0.73u" in nfl                 # the ATS units are unaffected
    assert "Line move" not in nfl          # no per-game column either


# ------------------------------- (4) a payload with no CLV renders as before

def test_a_payload_without_clv_renders_byte_for_byte_as_before(tmp_path):
    """The regression guard. `nfl_clv.json` is `nfl_priced.json` plus CLV and
    nothing else, so stripping CLV back out must reproduce the pre-CLV pages
    exactly — same bytes, on every page."""
    stripped = site_from(
        tmp_path,
        {"nfl": strip_clv(load("nfl_clv.json")),
         "nba": strip_clv(load("nba_clv.json"))},
        name="stripped",
    )
    before = make_site(tmp_path, "nfl_priced.json", "nba_priced.json", "before")
    for page in PAGES:
        assert read(stripped, page) == read(before, page), (
            f"{page} changed for a payload carrying no CLV"
        )


def test_a_payload_without_clv_grows_no_empty_clv_furniture(tmp_path):
    out = make_site(tmp_path, "nfl_priced.json", "nba_priced.json")
    track = read(out, "track-record.html")
    assert "Closing line value" not in track
    assert "clv" not in track
    assert "Line move" not in track
    assert "snapshot" not in track


@pytest.mark.parametrize("page", PAGES)
def test_no_clv_payload_leaks_no_literals(tmp_path, page):
    out = make_site(tmp_path, "nfl.json", "nba.json")  # v1, pre-settle payloads
    text = read(out, page)
    assert "None" not in text
    assert "NaN" not in text
    assert "null" not in text


def test_a_record_block_with_a_junk_clv_value_is_ignored(tmp_path):
    """Tolerance runs one step past "absent": a clv that is not an object is
    not renderable, so nothing is rendered."""
    payload = strip_clv(load("nfl_clv.json"))
    payload["record"]["clv"] = "soon"
    out = site_from(tmp_path, {"nfl": payload})
    assert "Closing line value" not in read(out, "track-record.html")


# ------------------------------------------------------- (5) per-game rows

def history_row(out_dir, sport, matchup):
    section = record_section(out_dir, sport)
    rows = [r for r in section.split("<tr") if matchup in r]
    assert rows, f"no row for {matchup}"
    return rows[0]


def test_a_graded_game_shows_its_line_move_and_the_book(clv_site):
    row = history_row(clv_site, "nfl", "SEA @ ARI")
    assert '<th scope="col">Line move</th>' in record_section(clv_site, "nfl")
    assert "+2.0 pts" in row
    assert "Pinnacle" in row
    # the full snapshot pair is available on hover, both ends with their price
    assert "morning -1.0 at -110 (FanDuel)" in row
    assert "close -3.0 at -105 (Pinnacle)" in row


def test_a_game_whose_line_did_not_move_reads_as_zero_not_as_missing(clv_site):
    row = history_row(clv_site, "nfl", "SF @ LAR")
    assert "0.0 pts" in row
    assert "clv-na" not in row


def test_an_ungraded_game_shows_an_em_dash_with_a_spoken_explanation(clv_site):
    """Exactly how the units column treats a game with no odds: an em dash,
    a title, and a screen-reader line saying why — never a fabricated 0."""
    row = history_row(clv_site, "nfl", "HOU @ TEN")
    assert 'class="pl-cell clv-na"' in row
    assert 'title="no complete morning and closing snapshot &#8212; ungraded for CLV"' in row
    assert '<span aria-hidden="true">&#8212;</span>' in row
    assert '<span class="visually-hidden">ungraded for CLV, snapshots incomplete</span>' in row
    assert "0.0 pts" not in row


def test_a_game_with_no_clv_key_at_all_still_renders_its_row(clv_site):
    """The pending NFL game carries no `clv` key; nothing breaks, and the
    graded rows around it are unaffected."""
    nfl = record_section(clv_site, "nfl")
    assert "NYJ @ DEN" not in nfl  # ungraded straight-up, so not in the table
    assert nfl.count('class="pl-cell clv-na"') == 2  # MIA @ NE and HOU @ TEN


def test_the_column_disappears_when_no_game_is_clv_graded(tmp_path):
    payload = strip_clv(load("nfl_clv.json"))
    payload["record"]["clv"] = empty_clv_payload()["record"]["clv"]
    for game in payload["history"]:
        game["clv"] = {"graded": False}
    out = site_from(tmp_path, {"nfl": payload})
    nfl = record_section(out, "nfl")
    assert "Line move" not in nfl
    assert "clv-na" not in nfl


# ------------------------------------------------- (6) the methodology note

def method_note(out_dir):
    text = read(out_dir, "methodology.html")
    assert 'id="clv-method"' in text, "no CLV note on the methodology page"
    return prose(text.split('aria-labelledby="clv-method"')[1].split("</section>")[0])


def test_the_methodology_note_reports_a_real_signal_in_both_sports(clv_site):
    note = method_note(clv_site)
    assert "real directional signal" in note
    assert "moved toward the model more often than chance" in note
    # ...and immediately says a free line move is not money
    assert "free of vig" in note


def test_the_nfl_verdict_keeps_its_numbers_and_its_unresolved_sign(clv_site):
    """The honest numbers, asserted so nobody can quietly soften them: NFL
    landed on the breakeven line, and which side of it is unknown because the
    source published no prices."""
    note = method_note(clv_site)
    assert "52.43%" in note
    assert "52.38%" in note
    assert "the sign of that verdict is unresolved" in note.lower()
    assert "without prices" in note
    assert "-105 turns it positive" in note
    assert "+2.28%" in note
    assert "-115 turns it negative" in note
    assert "−1.92%" in note
    assert "assumption, not a measurement" in note


def test_the_nba_verdict_is_stated_as_decisively_negative(clv_site):
    note = method_note(clv_site)
    assert "decisively negative" in note
    assert "−4.89%" in note
    assert "confidence interval that excludes zero" in note


def test_the_note_gives_the_reconciling_reason_with_both_maes(clv_site):
    """CLV positive and ROI negative is not a contradiction: the opener is
    simply the better forecast. Both MAEs are named."""
    note = method_note(clv_site)
    assert "opening line already forecasts better than the model" in note
    assert "10.38" in note
    assert "10.66" in note
    assert "necessary condition" in note and "not a sufficient one" in note


def test_the_note_says_this_is_a_paper_trail_and_not_a_betting_system(clv_site):
    note = method_note(clv_site)
    assert "records a forward paper trail with real prices" in note
    assert "rather than running a betting system" in note
    assert "Nothing is staked, nothing is recommended" in note
    assert "not advice to bet anything" in note


def test_the_note_never_claims_an_edge(clv_site):
    note = method_note(clv_site).lower()
    for claim in ("profitable", "beats the market", "beat the market",
                  "guaranteed", "edge over the market"):
        assert claim not in note, f"spin in the CLV note: {claim!r}"


def test_the_existing_honest_backtest_framing_is_untouched(clv_site):
    text = prose(read(clv_site, "methodology.html"))
    assert "Neither model beats the betting market" in text
    assert "negative return on investment" in text
    assert "walk-forward only" in text
    assert "The honest betting finding" in text


def test_the_note_is_present_even_for_a_payload_carrying_no_clv(tmp_path):
    """It reports a completed study, not today's payload, so it does not
    come and go with the data."""
    out = make_site(tmp_path, "nfl_priced.json", "nba_priced.json")
    assert "52.43%" in method_note(out)


# ---------------------------------------------------- (7) site invariants

@pytest.mark.parametrize("page", PAGES)
def test_disclaimer_and_stamp_survive(clv_site, page):
    text = read(clv_site, page)
    assert DISCLAIMER in text
    assert re.search(r"Last updated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC from \S+", text)


@pytest.mark.parametrize("page", PAGES)
def test_hrefs_stay_relative(clv_site, page):
    for href in re.findall(r'href="([^"]*)"', read(clv_site, page)):
        assert not href.startswith("/"), f"absolute href {href!r} in {page}"


@pytest.mark.parametrize("page", PAGES)
def test_clv_pages_leak_no_literals(clv_site, page):
    text = read(clv_site, page)
    assert "None" not in text
    assert "NaN" not in text
    assert "null" not in text


def test_clv_styles_are_theme_aware(clv_site):
    """Every new colour is a variable the dark block redefines, and CLV
    borrows none of the win/loss palette — a line moving your way is
    information, not money."""
    css = read(clv_site, "style.css")
    assert "@media (prefers-color-scheme: dark)" in css
    for selector in (".clv-note {", ".clv-large {", ".clv-book {",
                     ".clv-move {", "table.history td.clv-na {"):
        rule = css.split(selector)[1].split("}")[0]
        assert "var(--" in rule, f"{selector} sets no themed colour"
        assert "#" not in rule, f"hardcoded colour in {selector}"
    large = css.split(".clv-large {")[1].split("}")[0]
    assert "--good" not in large and "--bad" not in large


def test_the_formatters_refuse_to_print_a_missing_number():
    assert build_mod.fmt_pp(None) == build_mod.EMDASH
    assert build_mod.fmt_points(None) == build_mod.EMDASH
    assert build_mod.fmt_cents(None) == build_mod.EMDASH
    assert build_mod.fmt_pp("soon") == build_mod.EMDASH
    assert build_mod.fmt_pp(True) == build_mod.EMDASH
    assert build_mod.fmt_pp(float("nan")) == build_mod.EMDASH
    # a real zero is a measurement and prints as one, unsigned
    assert build_mod.fmt_points(0.0) == "0.00 pts"
    assert build_mod.fmt_points(-1.5, 1) == "-1.5 pts"
    assert build_mod.fmt_pp(1.2) == "+1.20 pp"


def test_the_moved_denominator_refuses_an_inconsistent_payload():
    assert build_mod.clv_moved_count({"n_graded": 5, "no_move": 1}) == 4
    assert build_mod.clv_moved_count({"n_graded": 5, "no_move": 9}) is None
    assert build_mod.clv_moved_count({"n_graded": 5}) is None
    assert build_mod.clv_moved_count({}) is None
