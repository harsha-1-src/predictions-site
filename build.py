#!/usr/bin/env python3
"""Static site builder for the predictions site.

Reads payloads/nfl.json and payloads/nba.json (either may be missing) and
renders plain HTML into docs/. Python 3 stdlib only, zero JavaScript output.

Usage:
    python build.py                # payloads/ -> docs/
    build(payload_dir, out_dir)    # injectable paths, used by tests
"""
from __future__ import annotations

import html
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

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

DISCLAIMER = (
    "These are the outputs of a hobby statistical model, published for fun "
    "and transparency. Not betting advice."
)

HISTORY_ROW_CAP = 200


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


def render_index(payloads: dict) -> str:
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
    return intro + "\n" + "\n".join(sections)


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


def render_record_summary(record: dict, sport: str) -> str:
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
    ats = record.get("ats")
    if ats:
        stats.append(
            (
                "Against the spread",
                f"{ats.get('w', 0)}&#8211;{ats.get('l', 0)}&#8211;{ats.get('p', 0)}"
                f" ({fmt_pct(ats.get('pct'))})",
            )
        )
    cells = "\n    ".join(
        f'<div class="stat"><dt>{name}</dt><dd>{value}</dd></div>'
        for name, value in stats
    )
    return f'<dl class="stat-grid">\n    {cells}\n  </dl>'


def render_history_table(history: list, sport: str) -> str:
    graded = [g for g in history if g.get("su_correct") is not None]
    graded.sort(key=lambda g: (g.get("date") or "", g.get("game_id") or ""), reverse=True)
    graded = graded[:HISTORY_ROW_CAP]
    if not graded:
        return ""
    show_ats = any(g.get("ats_result") for g in graded)
    ats_head = "<th scope=\"col\">ATS</th>" if show_ats else ""
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
        rows.append(
            "<tr>"
            f"<td>{fmt_date_short(g.get('date'))}</td>"
            f"<td>{esc(matchup)}</td>"
            f"<td>{esc(g.get('pick') or '?')} ({fmt_pct(g.get('pick_prob'), 0)})</td>"
            f'<td class="{mark_cls}"><span aria-hidden="true">{mark}</span>'
            f'<span class="visually-hidden">{mark_label}</span></td>'
            f"<td>{score}</td>"
            f"{ats_cell}"
            "</tr>"
        )
    body = "\n      ".join(rows)
    return f"""<div class="table-scroll">
  <table class="history">
    <thead>
      <tr><th scope="col">Date</th><th scope="col">Matchup</th><th scope="col">Pick</th><th scope="col">Result</th><th scope="col">Score</th>{ats_head}</tr>
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
                parts = [render_record_summary(record, sport)]
                chart = running_chart_svg(record.get("running") or [], label)
                if chart:
                    parts.append(chart)
                table = render_history_table(payload.get("history") or [], sport)
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
  Because it uses no market data, it publishes no spread comparison.</p>
  {render_backtest_stats(payloads.get("nba"))}
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

def build(payload_dir=None, out_dir=None) -> Path:
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
            render_index(payloads),
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
    return out_dir


if __name__ == "__main__":
    out = build()
    print(f"built site into {out}")
