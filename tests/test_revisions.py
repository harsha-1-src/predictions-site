"""Tests for the revision disclosures on the track-record page."""
import html
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from build import build, render_revisions  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def track(tmp_path_factory):
    base = tmp_path_factory.mktemp("revisions")
    payload_dir = base / "payloads"
    payload_dir.mkdir()
    shutil.copyfile(FIXTURES / "nfl_priced.json", payload_dir / "nfl.json")
    shutil.copyfile(FIXTURES / "nba_unpriced.json", payload_dir / "nba.json")
    out = base / "docs"
    build(payload_dir, out, NOW)
    return (out / "track-record.html").read_text(encoding="utf-8")


def phi_row(track):
    """The PHI @ WAS row — the fixture's three-revision game."""
    match = re.search(r"<tr>(?:(?!</tr>).)*PHI @ WAS.*?</tr>", track, re.S)
    assert match, "PHI @ WAS row missing"
    return match.group(0)


# ------------------------------------------------------------- the disclosure

def test_a_revised_game_renders_a_no_js_details_disclosure(track):
    row = phi_row(track)
    assert '<details class="rev-details">' in row
    assert "<summary>3 revisions</summary>" in row
    assert "<script" not in track


def test_all_three_revision_timestamps_are_shown(track):
    row = phi_row(track)
    for stamp in (
        "2026-09-24 13:00 UTC",
        "2026-09-26 13:05 UTC",
        "2026-09-27 21:40 UTC",
    ):
        assert stamp in row, f"missing revision timestamp {stamp}"


def test_the_original_pick_and_each_edit_are_labelled(track):
    row = phi_row(track)
    assert ">Original</span>" in row
    assert ">Edit 1</span>" in row
    assert ">Edit 2</span>" in row


def test_each_revision_carries_its_probability_line_and_price(track):
    row = html.unescape(phi_row(track))
    assert "61%" in row and "line -3.0" in row and "ML -165" in row
    assert "66%" in row and "line -3.5" in row and "ML -180" in row
    assert "71%" in row and "ML -190" in row


# ------------------------------------------------------------ post-kickoff

def test_post_kickoff_revision_is_flagged_as_not_graded(track):
    row = html.unescape(phi_row(track))
    assert "logged after kickoff — not graded" in row
    assert row.count("logged after kickoff") == 1, "only the late edit is flagged"


def test_only_the_post_kickoff_revision_carries_the_late_class(track):
    row = phi_row(track)
    assert row.count('class="rev-late"') == 1
    # ...and it is the last one listed, matching the fixture.
    assert row.index('class="rev-late"') > row.index("2026-09-26 13:05 UTC")


# ------------------------------------------------- when NOT to show anything

def test_a_single_revision_is_not_a_revision_history(track):
    # GB @ DET has exactly one logged revision: nothing was ever edited.
    row = re.search(r"<tr>(?:(?!</tr>).)*GB @ DET.*?</tr>", track, re.S).group(0)
    assert "rev-details" not in row


def test_a_game_with_no_revisions_key_renders_nothing():
    assert render_revisions({"away": "SF", "home": "LAR"}) == ""
    assert render_revisions({"revisions": None}) == ""
    assert render_revisions({"revisions": []}) == ""


def test_revisions_tolerate_missing_optional_fields():
    out = render_revisions(
        {
            "revisions": [
                {"logged_at": "2026-09-24T13:00:00+00:00", "pick": "PHI"},
                {"logged_at": "2026-09-25T13:00:00+00:00", "pick": "WAS"},
            ]
        }
    )
    assert "2 revisions" in out
    assert "None" not in out and "NaN" not in out
