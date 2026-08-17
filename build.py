#!/usr/bin/env python3
"""Static site builder for the predictions site.

Reads payloads/nfl.json and payloads/nba.json (either may be missing) and
renders plain HTML into docs/. Python 3 stdlib only, zero JavaScript output.

Also writes the raw payloads to docs/data/<sport>.json so "what is live" is
fetchable by the model repos' `sync` command.

Usage:
    python build.py                     # payloads/ -> docs/
    python build.py --now 2026-10-24    # pin the clock (previews and tests)
    build(payload_dir, out_dir, now)    # injectable paths, used by tests
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import units

ROOT = Path(__file__).resolve().parent

SPORTS = (("nfl", "NFL"), ("nba", "NBA"))

TIER_CLASS = {"Strong": "strong", "Lean": "lean", "Toss-up": "tossup"}

ATS_LABEL = {
    "win": "Win",
    "loss": "Loss",
    "push": "Push",
    "no-line": "no line",
    "no-pick": "no pick",
}

MARKET_LABEL = {"ats": "Against the spread", "ml": "Moneyline"}

DISCLAIMER = (
    "These are the outputs of a hobby statistical model, published for fun "
    "and transparency. Not betting advice."
)

HISTORY_ROW_CAP = 200

#: Rows of the home-page P/L dashboard (all-time lives on the track record).
DASH_WINDOWS = (("today", "Today"), ("week", "This week"), ("month", "This month"))

NO_ODDS_NOTE = "units require an odds source &#8212; showing record only"

NO_GRADED_NOTE = (
    "No graded picks yet &#8212; P/L starts when the first games are played."
)

#: Odds coverage is per game, so a league can have real units that cover only
#: part of its slate. Say so rather than implying the units cover everything.
PARTIAL_ODDS_NOTE = (
    "{ungraded} of {graded} graded games had no odds logged and are "
    "ungraded for units"
)

UNGRADED_UNITS_TITLE = "no odds logged &#8212; ungraded for units"

UNGRADED_UNITS_LABEL = "ungraded for units, no odds logged"

POST_KICKOFF_NOTE = "logged after kickoff &#8212; not graded"

EMDASH = "&#8212;"


# ---------------------------------------------------------------- formatting

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_pct(x, digits: int = 1) -> str:
    if x is None:
        return "&#8212;"
    return f"{x * 100:.{digits}f}%"


def fmt_num(x, digits: int = 3) -> str:
    if x is None:
        return "&#8212;"
    return f"{x:.{digits}f}"


def fmt_score(x) -> str:
    if x is None:
        return "&#8212;"
    return str(int(round(float(x))))


def fmt_date(s) -> str:
    """'2026-09-13' -> 'Sun, Sep 13, 2026' (readable, no locale tricks)."""
    try:
        dt = datetime.strptime(str(s), "%Y-%m-%d")
    except (TypeError, ValueError):
        return esc(s if s is not None else "")
    return f"{dt.strftime('%a')}, {dt.strftime('%b')} {dt.day}, {dt.year}"


def fmt_date_short(s) -> str:
    try:
        dt = datetime.strptime(str(s), "%Y-%m-%d")
    except (TypeError, ValueError):
        return esc(s if s is not None else "")
    return f"{dt.strftime('%b')} {dt.day}"


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_time_utc(s):
    dt = parse_iso(s)
    if dt is None:
        return None
    return f"{dt.strftime('%H:%M')} UTC"


def fmt_stamp(s) -> str:
    dt = parse_iso(s)
    if dt is None:
        return esc(s if s is not None else "")
    return f"{dt.strftime('%Y-%m-%d %H:%M')} UTC"


def fmt_logged(s) -> str:
    dt = parse_iso(s)
    if dt is None:
        return esc(s if s is not None else "")
    return dt.strftime("%Y-%m-%d")


def fmt_units(u) -> str:
    """'+1.82u' / '-0.91u' / '0.00u' — always signed so colour is not the
    only cue that a number is negative."""
    if u is None:
        return EMDASH
    if abs(u) < 0.005:
        return "0.00u"
    return f"{u:+.2f}u"


def units_class(u) -> str:
    if u is None or abs(u) < 0.005:
        return "pl-flat"
    return "pl-pos" if u > 0 else "pl-neg"


def fmt_price(price) -> str:
    """American odds with an explicit sign: -180, +145."""
    if price is None:
        return EMDASH
    return f"{int(price):+d}"


# ------------------------------------------------------------------- loading

def load_payload(payload_dir: Path, sport: str):
    path = Path(payload_dir) / f"{sport}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as err:
        print(f"warning: could not read {path}: {err}", file=sys.stderr)
        return None


# --------------------------------------------------------------- page shell

def page_shell(title: str, active: str, body: str, updated: str | None) -> str:
    nav_items = (
        ("index.html", "Picks", "picks"),
        ("track-record.html", "Track record", "track"),
        ("methodology.html", "Methodology", "methodology"),
    )
    links = []
    for href, label, key in nav_items:
        current = ' aria-current="page"' if key == active else ""
        links.append(f'<a href="{href}"{current}>{label}</a>')
    nav = "\n      ".join(links)
    updated_html = (
        f'<p class="updated">Updated {esc(updated)}</p>' if updated else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{esc(title)}</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <p class="brand"><a href="index.html">Model Picks</a></p>
    <nav aria-label="Site">
      {nav}
    </nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>{DISCLAIMER}</p>
    {updated_html}
  </div>
</footer>
</body>
</html>
"""


def empty_card(text: str) -> str:
    return f'<div class="card empty-card"><p>{esc(text)}</p></div>'


# --------------------------------------------------------------- dashboard

def _cell(inner: str) -> str:
    return f'<td class="pl-cell">{inner}</td>'


def _units_cell(block) -> str:
    """A units figure plus its W-L-P record. Pushes get their own slot and are
    never rolled into the win count."""
    if not block:
        return _cell(EMDASH)
    u = block["units"]
    record = f'{block["w"]}-{block["l"]}-{block["p"]}'
    return _cell(
        f'<span class="pl-units {units_class(u)}">{fmt_units(u)}</span>'
        f'<span class="pl-rec">{record}</span>'
    )


def _record_cell(record) -> str:
    """Fallback for a league with no priced market: straight-up W-L only."""
    if not record or not record["n"]:
        return _cell(EMDASH)
    return _cell(
        f'<span class="pl-rec pl-rec-only">{record["w"]}-{record["l"]}</span>'
    )


def _coverage_note(label: str, cov: dict) -> str:
    """The note under the dashboard for one league's odds coverage, or "".

    Three honest states, decided by the data and never by the league's name:
    nothing priced at all (record only), partly priced (real units plus how
    much of the slate they miss), and fully priced (no note needed).
    """
    if not cov["graded"]:
        return ""
    if not cov["priced"]:
        return f'<p class="pl-note">{esc(label)}: {NO_ODDS_NOTE}.</p>'
    if cov["ungraded"]:
        return (
            f'<p class="pl-note">{esc(label)}: '
            + PARTIAL_ODDS_NOTE.format(**cov)
            + ".</p>"
        )
    return ""


def render_dashboard(payloads: dict, now=None) -> str:
    """Compact Today / This week / This month by league P/L table.

    A league with no priced market anywhere falls back to a straight-up record
    and says so; a partly priced league shows the units it genuinely has plus
    a note naming how many games those units miss; a site with nothing graded
    at all still renders the shell so the page never loses its shape.
    """
    histories = {
        sport: ((payloads.get(sport) or {}).get("history") or [])
        for sport, _ in SPORTS
    }
    total_graded = sum(units.graded_count(h) for h in histories.values())

    # A league counts as "priced" if any market ever settled a bet for it.
    priced = {}
    for sport, _ in SPORTS:
        alltime = units.summarize(histories[sport], "all")
        priced[sport] = bool(alltime["ats"] or alltime["ml"])

    rows = []
    for key, label in DASH_WINDOWS:
        cells = []
        blocks = []
        for sport, _ in SPORTS:
            if not total_graded:
                cells.append(_cell(EMDASH))
                continue
            scoped = units.summarize(histories[sport], key, now)
            block = units.combine(scoped["ats"], scoped["ml"])
            blocks.append(block)
            if block or priced[sport]:
                cells.append(_units_cell(block))
            else:
                cells.append(_record_cell(units.su_record(histories[sport], key, now)))
        cells.append(_units_cell(units.combine(*blocks)) if total_graded else _cell(EMDASH))
        rows.append(
            f'<tr><th scope="row">{esc(label)}</th>' + "".join(cells) + "</tr>"
        )

    heads = "".join(
        f'<th scope="col">{esc(label)}</th>' for _, label in SPORTS
    ) + '<th scope="col">Combined</th>'

    notes = []
    if not total_graded:
        notes.append(f'<p class="pl-note">{NO_GRADED_NOTE}</p>')
    else:
        for sport, label in SPORTS:
            note = _coverage_note(label, units.coverage(histories[sport], "all"))
            if note:
                notes.append(note)
    notes_html = "\n  ".join(notes)

    return f"""<section class="dashboard" aria-labelledby="pl-heading">
  <h2 id="pl-heading">Profit &amp; loss</h2>
  <div class="table-scroll">
    <table class="pl-table">
      <caption class="visually-hidden">Units won or lost per league, at one
      flat unit a pick, with the win-loss-push record. Pacific time.</caption>
      <thead>
        <tr><th scope="col">Period</th>{heads}</tr>
      </thead>
      <tbody>
        {chr(10).join("        " + r for r in rows).strip()}
      </tbody>
    </table>
  </div>
  {notes_html}
</section>"""


# ------------------------------------------------------------------- index

def render_game_card(game: dict, sport: str) -> str:
    matchup = f"{game.get('away', '?')} @ {game.get('home', '?')}"
    tier = game.get("tier") or "Toss-up"
    tier_cls = TIER_CLASS.get(tier, "tossup")

    when = fmt_date(game.get("date"))
    time_utc = fmt_time_utc(game.get("datetime_utc"))
    if time_utc:
        when = f"{when} &#183; {esc(time_utc)}"

    pick = esc(game.get("pick")) if game.get("pick") else "&#8212;"
    pick_prob = game.get("pick_prob")
    prob = fmt_pct(pick_prob, 0) if pick_prob is not None else "&#8212;"

    away_s = fmt_score(game.get("pred_away_score"))
    home_s = fmt_score(game.get("pred_home_score"))
    proj = (
        f"Projected: {esc(game.get('away', ''))} {away_s}"
        f"&#8211;{home_s} {esc(game.get('home', ''))}"
    )

    lines_html = ""
    model_line = game.get("model_line")
    market_line = game.get("market_line")
    if model_line or market_line:
        parts = []
        if model_line:
            parts.append(f"Model line {esc(model_line)}")
        if market_line:
            parts.append(f"market {esc(market_line)}")
        line_txt = " vs ".join(parts)
        market_total = game.get("market_total")
        if market_total is not None:
            line_txt += f" &#183; market total {market_total:g}"
        lines_html = f'<p class="lines">{line_txt}</p>'

    ml_price = game.get("ml_price")
    if ml_price is not None:
        ml_html = f'<p class="lines">Moneyline {fmt_price(ml_price)}</p>'
        lines_html = lines_html + ml_html if lines_html else ml_html

    logged = ""
    if game.get("logged_at"):
        logged = f'<p class="logged">picked {esc(fmt_logged(game["logged_at"]))}</p>'

    return f"""<article class="card game-card">
  <div class="game-top">
    <h3 class="matchup">{esc(matchup)}</h3>
    <span class="badge badge-{tier_cls}">{esc(tier)}</span>
  </div>
  <p class="game-when">{when}</p>
  <p class="pick-line">Pick: <strong>{pick}</strong> <span class="prob">{prob} win probability</span></p>
  <p class="proj">{proj}</p>
  {lines_html}
  {logged}
</article>"""


def render_index(payloads: dict, now=None) -> str:
    sections = []
    for sport, label in SPORTS:
        payload = payloads.get(sport)
        upcoming = (payload or {}).get("upcoming") or []
        if not upcoming:
            body = empty_card(
                "No upcoming picks logged yet — check back at the "
                "start of the season."
            )
        else:
            body = "\n".join(
                render_game_card(g, sport)
                for g in sorted(upcoming, key=lambda g: (g.get("date") or "", g.get("game_id") or ""))
            )
        sections.append(f"""<section class="sport-section" aria-labelledby="{sport}-picks">
  <h2 id="{sport}-picks">{label}</h2>
  {body}
</section>""")
    intro = '<h1>This week&#8217;s picks</h1>'
    dashboard = render_dashboard(payloads, now)
    return intro + "\n" + dashboard + "\n" + "\n".join(sections)


# ------------------------------------------------------------- track record

def running_chart_svg(running: list, label: str) -> str:
    """Inline SVG: running straight-up accuracy over time, 50% reference."""
    pts = [
        (r.get("date"), r.get("su_acc"))
        for r in running
        if r.get("date") and r.get("su_acc") is not None
    ]
    if not pts:
        return ""
    width, height = 640, 260
    ml, mr, mt, mb = 52, 16, 16, 40
    plot_w = width - ml - mr
    plot_h = height - mt - mb
    n = len(pts)

    def px(i: int) -> float:
        if n == 1:
            return ml + plot_w / 2
        return ml + plot_w * i / (n - 1)

    def py(acc: float) -> float:
        acc = min(max(acc, 0.0), 1.0)
        return mt + (1.0 - acc) * plot_h

    coords = [(px(i), py(a)) for i, (_, a) in enumerate(pts)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "\n  ".join(
        f'<circle class="chart-dot" cx="{x:.1f}" cy="{y:.1f}" r="3"/>'
        for x, y in coords
    )
    y50 = py(0.5)
    first_date = fmt_date_short(pts[0][0])
    last_date = fmt_date_short(pts[-1][0])
    latest = fmt_pct(pts[-1][1], 1)
    x_labels = f'<text class="chart-label" x="{ml}" y="{height - 12}" text-anchor="start">{first_date}</text>'
    if n > 1:
        x_labels += (
            f'\n  <text class="chart-label" x="{width - mr}" y="{height - 12}"'
            f' text-anchor="end">{last_date}</text>'
        )
    aria = (
        f"{label} running straight-up accuracy over {n} "
        f"point{'s' if n != 1 else ''}, latest {latest}"
    )
    return f"""<figure class="chart">
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(aria)}" preserveAspectRatio="xMidYMid meet">
  <line class="chart-grid" x1="{ml}" y1="{py(1.0):.1f}" x2="{width - mr}" y2="{py(1.0):.1f}"/>
  <line class="chart-ref" x1="{ml}" y1="{y50:.1f}" x2="{width - mr}" y2="{y50:.1f}"/>
  <line class="chart-grid" x1="{ml}" y1="{py(0.0):.1f}" x2="{width - mr}" y2="{py(0.0):.1f}"/>
  <text class="chart-label" x="{ml - 8}" y="{py(1.0) + 4:.1f}" text-anchor="end">100%</text>
  <text class="chart-label" x="{ml - 8}" y="{y50 + 4:.1f}" text-anchor="end">50%</text>
  <text class="chart-label" x="{ml - 8}" y="{py(0.0) + 4:.1f}" text-anchor="end">0%</text>
  {x_labels}
  <polyline class="chart-line" points="{poly}"/>
  {dots}
</svg>
<figcaption>Running straight-up accuracy by date. The dashed line marks 50%.</figcaption>
</figure>"""


def units_chart_svg(series: dict, label: str) -> str:
    """Inline SVG: cumulative units over time, with a zero (break-even) line.

    ``series`` is ``units.cumulative_series(...)``. Both markets are drawn when
    both exist, with a small legend. Returns "" when there is nothing to plot,
    so an ungraded league renders no chart at all rather than an empty frame.
    """
    series = {k: v for k, v in (series or {}).items() if v}
    if not series:
        return ""

    width, height = 640, 260
    mleft, mright, mtop, mbottom = 60, 16, 16, 40
    plot_w = width - mleft - mright
    plot_h = height - mtop - mbottom

    days = sorted({d for points in series.values() for d, _ in points})
    index = {d: i for i, d in enumerate(days)}
    n = len(days)

    def px(i: int) -> float:
        if n == 1:
            return mleft + plot_w / 2
        return mleft + plot_w * i / (n - 1)

    values = [v for points in series.values() for _, v in points] + [0.0]
    hi, lo = max(values), min(values)
    if hi - lo < 1e-9:
        hi, lo = hi + 1.0, lo - 1.0
    pad = (hi - lo) * 0.12
    hi, lo = hi + pad, lo - pad
    span = hi - lo

    def py(v: float) -> float:
        return mtop + (hi - v) / span * plot_h

    order = [m for m in ("ats", "ml") if m in series]
    lines = []
    for pos, market in enumerate(order):
        suffix = "" if pos == 0 else "-2"
        coords = [(px(index[d]), py(v)) for d, v in series[market]]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        lines.append(f'<polyline class="chart-line{suffix}" points="{poly}"/>')
        lines.extend(
            f'<circle class="chart-dot{suffix}" cx="{x:.1f}" cy="{y:.1f}" r="3"/>'
            for x, y in coords
        )
    lines_html = "\n  ".join(lines)

    y0 = py(0.0)
    x_labels = (
        f'<text class="chart-label" x="{mleft}" y="{height - 12}"'
        f' text-anchor="start">{fmt_date_short(days[0])}</text>'
    )
    if n > 1:
        x_labels += (
            f'\n  <text class="chart-label" x="{width - mright}" y="{height - 12}"'
            f' text-anchor="end">{fmt_date_short(days[-1])}</text>'
        )

    endings = ", ".join(
        f"{MARKET_LABEL[m].lower()} ends at {fmt_units(series[m][-1][1])}"
        for m in order
    )
    aria = f"{label} cumulative units over {n} date{'s' if n != 1 else ''}; {endings}"

    legend = ""
    if len(order) > 1:
        items = "".join(
            f'<li><span class="swatch{"" if pos == 0 else " swatch-2"}"'
            f' aria-hidden="true"></span>{esc(MARKET_LABEL[m])}</li>'
            for pos, m in enumerate(order)
        )
        legend = f'\n<ul class="chart-legend">{items}</ul>'

    return f"""<figure class="chart">
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(aria)}" preserveAspectRatio="xMidYMid meet">
  <line class="chart-grid" x1="{mleft}" y1="{mtop}" x2="{width - mright}" y2="{mtop}"/>
  <line class="chart-ref" x1="{mleft}" y1="{y0:.1f}" x2="{width - mright}" y2="{y0:.1f}"/>
  <line class="chart-grid" x1="{mleft}" y1="{mtop + plot_h}" x2="{width - mright}" y2="{mtop + plot_h}"/>
  <text class="chart-label" x="{mleft - 8}" y="{mtop + 4}" text-anchor="end">{fmt_units(hi)}</text>
  <text class="chart-label" x="{mleft - 8}" y="{y0 + 4:.1f}" text-anchor="end">0.00u</text>
  <text class="chart-label" x="{mleft - 8}" y="{mtop + plot_h + 4}" text-anchor="end">{fmt_units(lo)}</text>
  {x_labels}
  {lines_html}
</svg>{legend}
<figcaption>Cumulative units at one flat unit a pick. The dashed line marks
break-even. Both markets settle at the price logged with the pick; a spread
published without a price settles at the -110 convention. Games with no odds
on record are ungraded for units and plot nothing.</figcaption>
</figure>"""


def render_revisions(game: dict) -> str:
    """A no-JS <details> disclosure listing every logged revision of a pick.

    Only rendered when a pick was actually edited (more than one revision) —
    a single logged pick is just the pick. Revisions logged after kickoff are
    flagged as not graded, because they are not honest predictions.
    """
    revisions = game.get("revisions") or []
    if len(revisions) < 2:
        return ""
    items = []
    for i, rev in enumerate(revisions):
        kind = "Original" if i == 0 else f"Edit {i}"
        bits = [f"<strong>{esc(rev.get('pick') or '?')}</strong>"]
        prob = rev.get("pick_prob")
        if prob is not None:
            bits.append(fmt_pct(prob, 0))
        margin = rev.get("pred_margin")
        if margin is not None:
            bits.append(f"margin {margin:+.1f}")
        line = rev.get("spread_line")
        if line is not None:
            bits.append(f"line {line:+.1f}")
        price = rev.get("ml_price")
        if price is not None:
            bits.append(f"ML {fmt_price(price)}")
        late = bool(rev.get("post_kickoff"))
        flag = f' <span class="rev-flag">{POST_KICKOFF_NOTE}</span>' if late else ""
        cls = ' class="rev-late"' if late else ""
        items.append(
            f"<li{cls}><span class=\"rev-when\">{fmt_stamp(rev.get('logged_at'))}</span>"
            f' <span class="rev-kind">{esc(kind)}</span> '
            + " &#183; ".join(bits)
            + f"{flag}</li>"
        )
    body = "\n      ".join(items)
    return f"""<details class="rev-details">
    <summary>{len(revisions)} revisions</summary>
    <ol class="rev-list">
      {body}
    </ol>
  </details>"""


def ats_breakdown(record: dict, pnl=None):
    """The ATS W-L-P row for the summary grid, or ``None``.

    Prefers the payload's own ``record.ats`` and falls back to the settled ATS
    bets in ``pnl``. The fallback is what gives a league the same breakdown NFL
    has the moment its payload starts carrying spreads, even if the model repo
    has not caught up and still reports ``record.ats: null`` -- presence of the
    data decides, not the league.
    """
    ats = (record or {}).get("ats")
    if ats:
        return ats
    block = (pnl or {}).get("ats")
    if not block:
        return None
    decided = block["w"] + block["l"]
    return {
        "w": block["w"],
        "l": block["l"],
        "p": block["p"],
        "pct": (block["w"] / decided) if decided else None,
    }


def render_record_summary(record: dict, sport: str, pnl=None) -> str:
    su_wins = record.get("su_wins", 0)
    su_losses = record.get("su_losses", 0)
    stats = [
        ("Graded", str(record.get("graded", 0))),
        ("Pending", str(record.get("pending", 0))),
        (
            "Straight-up",
            f"{su_wins}&#8211;{su_losses} ({fmt_pct(record.get('su_acc'))})",
        ),
        ("Brier score", fmt_num(record.get("brier"))),
    ]
    ats = ats_breakdown(record, pnl)
    if ats:
        stats.append(
            (
                "Against the spread",
                f"{ats.get('w', 0)}&#8211;{ats.get('l', 0)}&#8211;{ats.get('p', 0)}"
                f" ({fmt_pct(ats.get('pct'))})",
            )
        )
    for market in ("ats", "ml"):
        block = (pnl or {}).get(market)
        if not block:
            continue
        stats.append(
            (
                f"Units &#183; {MARKET_LABEL[market].lower()}",
                f'<span class="{units_class(block["units"])}">'
                f'{fmt_units(block["units"])}</span> '
                f'<span class="stat-sub">{block["w"]}-{block["l"]}-{block["p"]}'
                f", ROI {fmt_pct(block['roi'])}</span>",
            )
        )
    cells = "\n    ".join(
        f'<div class="stat"><dt>{name}</dt><dd>{value}</dd></div>'
        for name, value in stats
    )
    return f'<dl class="stat-grid">\n    {cells}\n  </dl>'


def _row_units_cell(game: dict) -> str:
    """The per-game units cell, or an explicit ungraded-for-units marker.

    A game with no odds on record is never allowed to look like a settled 0.00u
    or a loss: it gets an em dash carrying both a ``title`` and a screen-reader
    label saying why.
    """
    u = units.entry_units(game)
    if u is None:
        return (
            f'<td class="pl-cell units-na" title="{UNGRADED_UNITS_TITLE}">'
            f'<span aria-hidden="true">{EMDASH}</span>'
            f'<span class="visually-hidden">{UNGRADED_UNITS_LABEL}</span></td>'
        )
    return (
        f'<td class="pl-cell"><span class="pl-units {units_class(u)}">'
        f"{fmt_units(u)}</span></td>"
    )


def render_history_table(history: list, sport: str) -> str:
    """The graded-games table.

    Which columns appear is decided by what the payload contains, never by the
    sport: an ATS column whenever any graded game carries an ``ats_result``,
    and a units column whenever any graded game settled at least one priced
    market.
    """
    graded = [g for g in history if g.get("su_correct") is not None]
    graded.sort(key=lambda g: (g.get("date") or "", g.get("game_id") or ""), reverse=True)
    graded = graded[:HISTORY_ROW_CAP]
    if not graded:
        return ""
    show_ats = any(g.get("ats_result") for g in graded)
    show_units = any(units.is_priced(g) for g in graded)
    ats_head = "<th scope=\"col\">ATS</th>" if show_ats else ""
    units_head = '<th scope="col">Units</th>' if show_units else ""
    rows = []
    for g in graded:
        matchup = f"{g.get('away', '?')} @ {g.get('home', '?')}"
        correct = bool(g.get("su_correct"))
        mark = "&#10003;" if correct else "&#10007;"
        mark_cls = "result-win" if correct else "result-loss"
        mark_label = "correct" if correct else "incorrect"
        away_s = g.get("away_score")
        home_s = g.get("home_score")
        if away_s is not None and home_s is not None:
            score = f"{fmt_score(away_s)}&#8211;{fmt_score(home_s)}"
        else:
            score = "&#8212;"
        ats_cell = ""
        if show_ats:
            ats_txt = ATS_LABEL.get(g.get("ats_result"), "&#8212;")
            ats_cell = f"<td>{ats_txt}</td>"
        units_cell = _row_units_cell(g) if show_units else ""
        revisions = render_revisions(g)
        rows.append(
            "<tr>"
            f"<td>{fmt_date_short(g.get('date'))}</td>"
            f'<td class="matchup-cell">{esc(matchup)}{revisions}</td>'
            f"<td>{esc(g.get('pick') or '?')} ({fmt_pct(g.get('pick_prob'), 0)})</td>"
            f'<td class="{mark_cls}"><span aria-hidden="true">{mark}</span>'
            f'<span class="visually-hidden">{mark_label}</span></td>'
            f"<td>{score}</td>"
            f"{ats_cell}"
            f"{units_cell}"
            "</tr>"
        )
    body = "\n      ".join(rows)
    return f"""<div class="table-scroll">
  <table class="history">
    <thead>
      <tr><th scope="col">Date</th><th scope="col">Matchup</th><th scope="col">Pick</th><th scope="col">Result</th><th scope="col">Score</th>{ats_head}{units_head}</tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</div>"""


def render_track_record(payloads: dict) -> str:
    sections = []
    for sport, label in SPORTS:
        payload = payloads.get(sport)
        if payload is None:
            body = empty_card(
                "No results published yet — check back once the "
                "season is underway."
            )
        else:
            record = payload.get("record") or {}
            graded = record.get("graded", 0)
            if not graded:
                pending = record.get("pending", 0)
                body = empty_card(
                    f"Awaiting first results — {pending} picks are "
                    "logged and will be graded after the games are played."
                )
            else:
                history = payload.get("history") or []
                pnl = units.summarize(history, "all")
                parts = [render_record_summary(record, sport, pnl)]
                chart = running_chart_svg(record.get("running") or [], label)
                if chart:
                    parts.append(chart)
                units_chart = units_chart_svg(
                    units.cumulative_series(history), label
                )
                if units_chart:
                    parts.append(units_chart)
                note = _coverage_note(label, units.coverage(history, "all"))
                if note:
                    parts.append(note)
                table = render_history_table(history, sport)
                if table:
                    parts.append(table)
                body = "\n  ".join(parts)
        sections.append(f"""<section class="sport-section" aria-labelledby="{sport}-record">
  <h2 id="{sport}-record">{label}</h2>
  {body}
</section>""")
    intro = "<h1>Track record</h1>"
    return intro + "\n" + "\n".join(sections)


# -------------------------------------------------------------- methodology

def render_backtest_stats(payload) -> str:
    backtest = (payload or {}).get("backtest")
    if not backtest:
        return ""
    stats = [
        ("Straight-up accuracy", fmt_pct(backtest.get("su_acc"))),
        ("Brier score", fmt_num(backtest.get("brier"))),
        ("Margin MAE", fmt_num(backtest.get("margin_mae"), 1)),
        ("Games", str(backtest.get("n_games", "—"))),
        ("Seasons", esc(backtest.get("seasons") or "—")),
    ]
    cells = "\n    ".join(
        f'<div class="stat"><dt>{name}</dt><dd>{value}</dd></div>'
        for name, value in stats
    )
    return f'<dl class="stat-grid">\n    {cells}\n  </dl>'


def render_methodology(payloads: dict) -> str:
    nfl_bt = (payloads.get("nfl") or {}).get("backtest") or {}
    nba_bt = (payloads.get("nba") or {}).get("backtest") or {}
    nfl_ats = nfl_bt.get("ats")
    nba_ats = nba_bt.get("ats")

    ats_lines = []
    if nfl_ats:
        ats_lines.append(f"<li>NFL backtest: {esc(nfl_ats)}</li>")
    if nba_ats:
        ats_lines.append(f"<li>NBA backtest: {esc(nba_ats)}</li>")
    ats_list = (
        "\n    <ul>\n      " + "\n      ".join(ats_lines) + "\n    </ul>"
        if ats_lines
        else ""
    )

    return f"""<h1>Methodology</h1>
<p>Two independent hobby models, one per sport. Both are gradient-boosted
tree models (XGBoost) evaluated <strong>walk-forward only</strong>: every
prediction is made using data available strictly before the game, and the
models never see future data during evaluation. Published picks are logged
before kickoff/tip-off and graded after the fact, unedited.</p>

<section class="callout" aria-labelledby="honest-note">
  <h2 id="honest-note">The honest betting finding</h2>
  <p>Neither model beats the betting market. Against closing spreads both sit
  near 50% against the spread, which after the bookmaker&#8217;s vig means a
  <strong>negative return on investment</strong> &#8212; no betting edge.</p>{ats_list}
  <p>That is the expected, honest result against closing lines, which are
  extremely efficient. These models are for fun and for tracking calibrated
  win probabilities, not for beating the market.</p>
</section>

<section class="sport-section" aria-labelledby="nfl-method">
  <h2 id="nfl-method">NFL model</h2>
  <p>A market-anchored XGBoost model built on
  <a href="https://github.com/nflverse" rel="noopener">nflverse</a> data.
  Features include exponentially weighted (EWMA) team form, an Elo rating,
  and a closing-line prior that anchors the model to the market&#8217;s
  opening information. The totals head additionally uses weather, and a
  rolling starting-QB CPOE feature tracks quarterback play.</p>
  {render_backtest_stats(payloads.get("nfl"))}
</section>

<section class="sport-section" aria-labelledby="nba-method">
  <h2 id="nba-method">NBA model</h2>
  <p>A stats-only XGBoost model anchored on an Elo rating &#8212; no betting
  market inputs at all. Features include exponentially weighted four-factors
  (shooting, turnovers, rebounding, free throws) and rest/schedule effects.
  Because it uses no market data, its picks are made without ever seeing a
  line &#8212; the odds below are attached afterwards, purely to settle the
  published units.</p>
  {render_backtest_stats(payloads.get("nba"))}
</section>

<section class="sport-section" aria-labelledby="odds-method">
  <h2 id="odds-method">Where the odds come from</h2>
  <p><strong>NFL spreads</strong> come from
  <a href="https://github.com/nflverse" rel="noopener">nflverse</a> historical
  closing lines. Those are a <em>line only</em> &#8212; nflverse does not
  publish the price that went with it &#8212; so NFL against-the-spread results
  are settled at the standard <strong>-110</strong> convention. That figure is
  a stated assumption, not a recorded price, and it is the only place on this
  site where a price is assumed at all.</p>
  <p><strong>NBA moneylines and spreads</strong> come from live odds APIs read
  at prediction time: <strong>ParlayAPI</strong> first, with
  <strong>The Odds API</strong> as the fallback (both on their free tiers).
  Those carry a real price, so NBA bets settle at the <strong>exact price
  logged with the pick</strong> &#8212; often -110 on a spread, but never
  assumed to be.</p>
  <p>Every price is recorded alongside the pick <em>before</em> the game and is
  never back-filled or invented afterwards. Coverage is <strong>per
  game</strong>, not per league: some games get a spread and a moneyline, some
  only one of the two, some neither. A game played with no odds on record is
  shown as <strong>ungraded for units</strong> &#8212; an em dash in the units
  column, and counted in the note under the P/L table &#8212; rather than being
  assumed into a price it never had. Days with no odds at all simply contribute
  no units.</p>
</section>

<section class="sport-section" aria-labelledby="eval-method">
  <h2 id="eval-method">Evaluation</h2>
  <p>Backtests are strictly walk-forward: the model is retrained through
  season <em>N</em> and scored on season <em>N&#8201;+&#8201;1</em>, then the
  window rolls forward. Accuracy above is straight-up (picking the winner);
  the Brier score measures probability calibration (lower is better); margin
  MAE is the mean absolute error of the predicted point margin.</p>
</section>"""


# -------------------------------------------------------------------- build

def build(payload_dir=None, out_dir=None, now=None) -> Path:
    """Render payloads into ``out_dir``.

    ``now`` pins the clock used for the Pacific dashboard windows; it defaults
    to the real UTC clock and exists so tests (and previews) are deterministic.
    It accepts the same ISO-8601 string the ``--now`` CLI flag takes, as well
    as a datetime.
    """
    now = units.coerce_now(now) if now is not None else None
    payload_dir = Path(payload_dir) if payload_dir else ROOT / "payloads"
    out_dir = Path(out_dir) if out_dir else ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)

    payloads = {sport: load_payload(payload_dir, sport) for sport, _ in SPORTS}

    stamps = [
        parse_iso(p.get("generated_at"))
        for p in payloads.values()
        if p and p.get("generated_at")
    ]
    stamps = [s for s in stamps if s is not None]
    updated = fmt_stamp(max(stamps).isoformat()) if stamps else None

    pages = {
        "index.html": page_shell(
            "This week's picks · Model Picks",
            "picks",
            render_index(payloads, now),
            updated,
        ),
        "track-record.html": page_shell(
            "Track record · Model Picks",
            "track",
            render_track_record(payloads),
            updated,
        ),
        "methodology.html": page_shell(
            "Methodology · Model Picks",
            "methodology",
            render_methodology(payloads),
            updated,
        ),
    }
    for name, content in pages.items():
        (out_dir / name).write_text(content, encoding="utf-8")

    shutil.copyfile(ROOT / "assets" / "style.css", out_dir / "style.css")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    write_data(payloads, out_dir)
    return out_dir


def write_data(payloads: dict, out_dir: Path) -> None:
    """Publish the raw payloads at docs/data/<sport>.json.

    This is the machine-readable "what is currently live" contract: the model
    repos' `sync` command diffs their freshly generated payload against these
    files to decide whether the site is stale. Written from the parsed payload
    so the published file is always valid JSON; a sport with no payload is
    left alone rather than being replaced with a misleading empty object.
    """
    data_dir = Path(out_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for sport, _ in SPORTS:
        payload = payloads.get(sport)
        if payload is None:
            continue
        (data_dir / f"{sport}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the static site.")
    parser.add_argument("--payloads", default=None, help="payload directory")
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument(
        "--now",
        default=None,
        help="ISO timestamp pinning the clock for the P/L windows "
        "(default: the real UTC clock)",
    )
    args = parser.parse_args(argv)

    now = None
    if args.now:
        now = parse_iso(args.now)
        if now is None:
            parser.error(f"could not parse --now {args.now!r} as an ISO timestamp")
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

    out = build(args.payloads, args.out, now)
    print(f"built site into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
