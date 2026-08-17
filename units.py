#!/usr/bin/env python3
"""Units (profit and loss) engine for the predictions site.

Python 3 standard library only. No I/O, no globals that change: everything
here is a pure function of the payload entries you hand it, plus an optional
``now`` so callers (and tests) can pin the clock.

Conventions
-----------
* One flat unit is staked per pick. There is no staking plan, no Kelly, no
  parlays -- 1u a pick, every pick.
* Against the spread (ATS) settles at the logged ``settle.spread_price``,
  defaulting to -110 when the payload does not carry one. A win therefore
  returns +100/110 = +0.9091u, a loss -1.0u, a push 0.0u.
* Moneyline (ML) settles at the logged ``settle.ml_price`` in American odds:
  a negative price pays 100/|price|, a positive price pays price/100.
* A game with no price for a market is **not a bet** at all. It is excluded
  from the counts entirely rather than being scored as 0.0 -- otherwise an
  ungraded slate would look like a break-even one.
* A market with zero settled bets reports ``None``, never ``0.0``, so the UI
  can say "units unavailable" instead of showing a fabricated break-even.
* Pushes are counted in their own bucket. They are never folded into wins.

Windows are America/Los_Angeles (Pacific) calendar windows: see
``window_bounds``. A game is attributed to a window by its ``date`` field,
which the payload defines as the game's local calendar date.

Payload tolerance: everything here treats missing ``settle``, ``revisions``
and ``ml_price`` keys (schema v1) as absent, so a v1 payload simply produces
``None`` blocks rather than an error.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo

__all__ = [
    "ATS_DEFAULT_PRICE",
    "WINDOWS",
    "american_profit",
    "ats_pnl",
    "combine",
    "cumulative_series",
    "filter_window",
    "graded_count",
    "ml_pnl",
    "pacific_tz",
    "su_record",
    "summarize",
    "window_bounds",
]

ATS_DEFAULT_PRICE = -110

#: (key, human label) for every supported window, widest last.
WINDOWS = (
    ("today", "Today"),
    ("week", "This week"),
    ("month", "This month"),
    ("all", "All time"),
)

_SETTLED = ("win", "loss", "push")


# ------------------------------------------------------------------ timezone

_PST = timedelta(hours=-8)
_ONE_HOUR = timedelta(hours=1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Date of the ``n``-th ``weekday`` (0=Mon) in ``month`` of ``year``."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


class _PacificApprox(tzinfo):
    """Stand-in for America/Los_Angeles when the IANA tz database is missing.

    Windows ships no system tz database, so ``zoneinfo`` raises
    ``ZoneInfoNotFoundError`` unless the ``tzdata`` package is installed. This
    repo is stdlib-only and cannot depend on it, so we approximate Pacific
    time with the post-2007 US rule: PDT (UTC-07:00) from the second Sunday in
    March at 02:00 local to the first Sunday in November at 02:00 local, and
    PST (UTC-08:00) the rest of the year.

    The approximation is exact for 2007 onwards under current law. It would be
    wrong for pre-2007 dates and for any future change to the DST rule (for
    instance permanent DST). It is only ever used to decide which Pacific
    calendar day "now" falls on, so an hour of slop at a DST cutover is the
    worst case.
    """

    def utcoffset(self, dt):
        return _PST + self.dst(dt)

    def dst(self, dt):
        if dt is None:
            return timedelta(0)
        naive = dt.replace(tzinfo=None)
        year = naive.year
        start = datetime(*_nth_weekday(year, 3, 6, 2).timetuple()[:3], 2, 0)
        end = datetime(*_nth_weekday(year, 11, 6, 1).timetuple()[:3], 2, 0)
        return _ONE_HOUR if start <= naive < end else timedelta(0)

    def tzname(self, dt):
        return "PDT" if self.dst(dt) else "PST"

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<PacificApprox (no tzdata)>"


_TZ_CACHE: list = []


def pacific_tz() -> tzinfo:
    """America/Los_Angeles, falling back to a fixed-rule approximation.

    Returns a real ``zoneinfo.ZoneInfo`` when the tz database is available and
    ``_PacificApprox`` when it is not (see that class for the caveat).
    """
    if _TZ_CACHE:
        return _TZ_CACHE[0]
    tz: tzinfo
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            tz = ZoneInfo("America/Los_Angeles")
        except (ZoneInfoNotFoundError, KeyError, ValueError, OSError):
            tz = _PacificApprox()
    except ImportError:  # pragma: no cover - zoneinfo exists on 3.9+
        tz = _PacificApprox()
    _TZ_CACHE.append(tz)
    return tz


def coerce_now(now=None) -> datetime:
    """Normalize a ``now`` argument to an aware UTC-based datetime.

    Accepts None (real clock), an ISO-8601 string (the same form the
    ``--now`` CLI flag takes, so the programmatic API and the CLI agree),
    a naive datetime (read as UTC), or an aware datetime.
    """
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now


def pacific_today(now=None) -> date:
    """The current Pacific calendar date.

    ``now`` may be omitted (real clock), an ISO string, naive (read as
    UTC) or aware.
    """
    return coerce_now(now).astimezone(pacific_tz()).date()


def window_bounds(window: str, now=None):
    """Inclusive ``(start, end)`` Pacific dates for a window, ``(None, None)``
    for ``"all"``.

    * ``today``      -- the current Pacific calendar day
    * ``week``       -- Monday through Sunday of the current Pacific week
    * ``month``      -- the 1st through the last day of the current month
    * ``all``        -- unbounded
    """
    if window == "all":
        return None, None
    today = pacific_today(now)
    if window == "today":
        return today, today
    if window == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        return start, start + timedelta(days=6)
    if window == "month":
        start = today.replace(day=1)
        if start.month == 12:
            nxt = start.replace(year=start.year + 1, month=1)
        else:
            nxt = start.replace(month=start.month + 1)
        return start, nxt - timedelta(days=1)
    raise ValueError(f"unknown window {window!r}")


def entry_date(entry):
    """Parse an entry's ``date`` as a Pacific calendar date, or ``None``."""
    raw = (entry or {}).get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def filter_window(entries, window: str = "all", now=None) -> list:
    """Entries whose ``date`` falls inside ``window``.

    Entries with a missing or unparseable date are kept for ``"all"`` and
    dropped from every bounded window -- an undated result cannot honestly be
    attributed to a day.
    """
    entries = list(entries or [])
    start, end = window_bounds(window, now)
    if start is None:
        return entries
    kept = []
    for entry in entries:
        day = entry_date(entry)
        if day is not None and start <= day <= end:
            kept.append(entry)
    return kept


# ----------------------------------------------------------------- settlement

def american_profit(price) -> float:
    """Profit on a winning 1u stake at an American price.

    -110 -> 0.9091, +150 -> 1.5. Raises ``ValueError`` on a 0/None price,
    which is malformed rather than merely absent.
    """
    if price is None:
        raise ValueError("no price")
    price = float(price)
    if price < 0:
        return 100.0 / abs(price)
    if price > 0:
        return price / 100.0
    raise ValueError("american price of 0 is not a price")


def ats_pnl(entry):
    """``(result, profit)`` for the ATS side of a game, or ``None``.

    ``None`` means "not a bet": no logged spread line, or an ``ats_result`` of
    no-line / no-pick / null. NBA sends null for every spread field, so NBA
    entries always land here.
    """
    settle = (entry or {}).get("settle") or {}
    if settle.get("spread_line") is None:
        return None
    result = (entry or {}).get("ats_result")
    if result not in _SETTLED:
        return None
    if result == "push":
        return result, 0.0
    if result == "loss":
        return result, -1.0
    price = settle.get("spread_price")
    if price is None or price == 0:
        price = ATS_DEFAULT_PRICE
    return result, american_profit(price)


def ml_pnl(entry):
    """``(result, profit)`` for the moneyline side of a game, or ``None``.

    ``None`` means "not a bet": no logged price (no odds source configured) or
    no settled ``ml_result`` yet.
    """
    settle = (entry or {}).get("settle") or {}
    price = settle.get("ml_price")
    if price is None or price == 0:
        return None
    result = settle.get("ml_result")
    if result not in _SETTLED:
        return None
    if result == "push":
        return result, 0.0
    if result == "loss":
        return result, -1.0
    return result, american_profit(price)


def _block(settled):
    """Roll ``[(result, profit), ...]`` into a summary block, or ``None``."""
    if not settled:
        return None
    units = round(sum(profit for _, profit in settled), 6)
    n = len(settled)
    return {
        "units": units,
        "w": sum(1 for result, _ in settled if result == "win"),
        "l": sum(1 for result, _ in settled if result == "loss"),
        "p": sum(1 for result, _ in settled if result == "push"),
        "n": n,
        "roi": round(units / n, 6) if n else None,
    }


def summarize(entries, window: str = "all", now=None) -> dict:
    """``{"ats": block|None, "ml": block|None}`` for ``entries`` in ``window``.

    Each block is ``{"units", "w", "l", "p", "n", "roi"}``. ``n`` counts bets
    placed (wins + losses + pushes) and ``roi`` is ``units / n`` -- pushes are
    included in the denominator because a push still consumed a slot on the
    card, and excluded from ``w``. A market with no settled bets is ``None``
    rather than a zeroed block.
    """
    scoped = filter_window(entries, window, now)
    return {
        "ats": _block([r for r in (ats_pnl(e) for e in scoped) if r]),
        "ml": _block([r for r in (ml_pnl(e) for e in scoped) if r]),
    }


def combine(*blocks):
    """Merge summary blocks (across markets or leagues); ``None`` if all empty."""
    live = [b for b in blocks if b]
    if not live:
        return None
    units = round(sum(b["units"] for b in live), 6)
    n = sum(b["n"] for b in live)
    return {
        "units": units,
        "w": sum(b["w"] for b in live),
        "l": sum(b["l"] for b in live),
        "p": sum(b["p"] for b in live),
        "n": n,
        "roi": round(units / n, 6) if n else None,
    }


# --------------------------------------------------------------- plain record

def graded_count(entries) -> int:
    """How many entries have been graded straight-up (win or loss recorded)."""
    return sum(1 for e in (entries or []) if (e or {}).get("su_correct") is not None)


def su_record(entries, window: str = "all", now=None) -> dict:
    """Straight-up ``{"w", "l", "n"}`` -- the fallback when nothing is priced."""
    scoped = filter_window(entries, window, now)
    w = sum(1 for e in scoped if (e or {}).get("su_correct") is True)
    lost = sum(1 for e in scoped if (e or {}).get("su_correct") is False)
    return {"w": w, "l": lost, "n": w + lost}


# ------------------------------------------------------------------- plotting

def cumulative_series(entries) -> dict:
    """Cumulative units over time, one point per date, per market.

    Returns ``{"ats": [(date, cumulative_units), ...], "ml": [...]}`` with a
    key present only when that market has at least one settled bet. Points are
    ordered oldest first and collapsed to one per calendar date, which keeps
    the chart honest for multi-game days.
    """
    out = {}
    for market, settle in (("ats", ats_pnl), ("ml", ml_pnl)):
        dated = []
        for entry in entries or []:
            day = entry_date(entry)
            if day is None:
                continue
            scored = settle(entry)
            if scored is None:
                continue
            dated.append((day, scored[1]))
        if not dated:
            continue
        dated.sort(key=lambda pair: pair[0])
        points = []
        total = 0.0
        for day, profit in dated:
            total += profit
            if points and points[-1][0] == day.isoformat():
                points[-1] = (day.isoformat(), round(total, 6))
            else:
                points.append((day.isoformat(), round(total, 6)))
        out[market] = points
    return out
