# predictions-site

A tiny static site publishing the picks and track record of two hobby sports
prediction models (NFL and NBA). Plain HTML plus one CSS file, zero
JavaScript, built with the Python 3 standard library only — no dependencies
to install. Served by GitHub Pages from `main:/docs`.

**These are the outputs of a hobby statistical model, published for fun and
transparency. Not betting advice.** Neither model has a betting edge — both
sit near 50% against the spread with vig-negative ROI, which is the expected
honest result against closing lines. See the site's Methodology page.

## Layout

```
payloads/           input payloads (nfl.json, nba.json) — gitignored
assets/style.css    the one stylesheet (copied into docs/ at build time)
units.py            flat-1u profit and loss engine (settlement + PST windows)
build.py            payloads -> docs/ (index, track-record, methodology, data)
publish.py          export payloads from the model repos, build, commit, push
daily.py            the daily cycle: run both models, republish, log
docs/               generated output, served by GitHub Pages
logs/               local run log (gitignored; only .gitkeep is tracked)
tests/              pytest suite with fixture payloads
```

`docs/` is fully regenerated on every build; never edit it by hand.

## Building

```
python build.py
python build.py --now 2026-10-24T18:00:00+00:00   # pin the clock (previews)
```

Reads `payloads/nfl.json` and `payloads/nba.json` (either may be missing —
that sport renders in an empty state) and writes the site into `docs/`.
`--now` only affects which games fall into the Today / This week / This month
dashboard rows; it exists so previews and tests are deterministic.

## Units and P/L conventions

The home page carries a Today / This week / This month × NFL / NBA / Combined
profit-and-loss dashboard, and the track record carries a cumulative-units
chart. All of it comes from `units.py`, which follows one set of rules:

* **One flat unit per pick.** No staking plan, no Kelly, no parlays.
* **ATS settles at the logged `settle.spread_price`.** A real spread price is
  *not* guaranteed to be -110: it is commonly -110, but -105, -120 and +100 all
  turn up. A win pays `american_profit(price)`, a loss **-1.0u**, a push
  **0.0u**.
* **-110 is a fallback, not the rule.** When a payload logs a spread *line*
  with no price, ATS settles at `units.ATS_DEFAULT_PRICE` (-110, so
  +100/110 = **+0.9091u** on a win). That is the NFL case and only the NFL
  case: nflverse publishes historical closing lines without the juice that
  went with them, so the price has to be assumed. It is the one assumed price
  anywhere on the site, and the Methodology page says so.
* **Moneylines settle at the logged price** (`settle.ml_price`, American
  odds): a negative price pays 100/|price|, a positive price pays price/100.
  The price is the one that was logged with the pick, not a later one.
* **Pushes are counted separately** (the record is W-L-P) and are never
  reported as wins. They stay in the ROI denominator, because a push still
  used a slot on the card.
* **Unpriced games are not bets.** A null `ats_result` (or a null
  `settle.spread_line`), an `ats_result` of `no-line` / `no-pick`, or a null
  `ml_price`, is excluded from that market's counts entirely — not scored as
  0.0 and *not* counted as a loss. This is the missing-spread path: a game we
  never had a spread for never had an ATS bet on it.
* **Ungraded for units** is a game that was played and graded straight-up but
  settled *no* market, because no odds were on record for it. It keeps its
  straight-up result and its row in the graded table, and shows an em dash in
  the Units column with a `title` and a screen-reader label explaining why.
  `units.coverage()` returns `{graded, priced, ungraded}` so the site can say
  how much of a slate its real units actually cover.
* **A market with no settled bets reports `null`, never `0.0`** — ATS exactly
  as much as moneyline. A league with nothing priced at all shows the
  straight-up record plus the note *"units require an odds source — showing
  record only"* instead of fabricated pricing. Before anything is graded at
  all, the dashboard renders its shell with em-dashes and *"No graded picks
  yet"*.
* **Coverage is per game, not per league.** An odds API can price part of a
  slate and miss the rest, so a league can have real units that cover only
  some of its games. Those leagues show their units *and* a note: *"NBA: 1 of
  4 graded games had no odds logged and are ungraded for units"*. A fully
  priced league gets no note.
* **Nothing is keyed on the league name.** Whether a league shows ATS, a
  moneyline, both or neither is decided purely by the fields present in its
  payload — `units.py` has no idea which sport it is looking at, and `build.py`
  picks the track-record columns from the data.
* ROI is `units / bets`, printed as a percentage.

### Where the odds come from

| League | Source | Price |
| --- | --- | --- |
| NFL | nflverse historical closing lines | line only — settled at the -110 convention |
| NBA | live odds APIs at prediction time: **ParlayAPI** primary, **The Odds API** fallback (both free tier) | real American price, settled exactly as logged |

NBA odds coverage is **per game**: some games get a spread and a moneyline,
some only one of the two, some neither. Prices are recorded with the pick
before the game and are never back-filled or invented afterwards, so a day
with no odds available produces ungraded-for-units games rather than assumed
ones.

### Window definitions (Pacific)

Windows are **America/Los_Angeles calendar** windows, and a game is attributed
to one by its payload `date` field (the game's local calendar date):

| Window | Definition |
| --- | --- |
| Today | the current Pacific calendar day |
| This week | **Monday to Sunday** of the current Pacific week |
| This month | the 1st to the last day of the current Pacific month |
| All time | everything, including entries with no usable date |

So a game dated `2026-12-31` and one dated `2027-01-01` are always different
days and different months, but they share a Mon–Sun week.

### The zoneinfo / tzdata caveat

`units.py` uses stdlib `zoneinfo`. Windows ships no system tz database, so
`ZoneInfo("America/Los_Angeles")` raises `ZoneInfoNotFoundError` unless the
`tzdata` package is installed — and this repo is deliberately dependency-free.
When that happens we fall back to `units._PacificApprox`, a documented
approximation of the post-2007 US rule: PDT (UTC-07:00) from the second Sunday
in March at 02:00 local to the first Sunday in November at 02:00 local, PST
(UTC-08:00) otherwise.

The approximation is exact under current law from 2007 onwards. It would be
wrong for pre-2007 dates or after any future rule change (permanent DST, say).
It is only ever used to decide which Pacific day "now" falls on, so the worst
case is an hour of slop at a DST cutover. On the machine this was developed on
the real tz database *was* available (the NFL repo's venv has `tzdata`), so the
fallback is insurance rather than the normal path — `tests/test_units.py`
exercises it directly either way.

## The `docs/data/*.json` contract

Every build also writes the raw payloads to:

```
docs/data/nfl.json
docs/data/nba.json
```

This is the machine-readable *"what is currently live"* record. The model
repos' `sync` command fetches these and diffs them against a freshly generated
payload to decide whether the published site is stale. They are re-serialised
from the parsed payload (indented, key-sorted) so the published file is always
valid JSON and diffs stay stable. A sport whose payload is missing or
unparseable is left alone rather than replaced with a misleading empty object.

## Publishing

```
python publish.py               # export + build + commit + push
python publish.py --skip-export # reuse whatever is already in payloads/
python publish.py --dry-run     # build and report; never commit or push
```

Without `--skip-export`, publish.py runs each sibling model repo's exporter
(`../nfl-model` and `../nba-model`, via each repo's own venv:
`.venv/Scripts/python.exe main.py site-payload`). A failed export prints a
warning and the previous payload is reused. It then copies each repo's
`reports/site_payload.json` into `payloads/`, rebuilds `docs/`, commits
(`publish: <UTC timestamp>`, skipped cleanly when nothing changed), and
pushes to `origin main` if a remote named `origin` is configured.

Each model's `weekly` command triggers `publish.py --skip-export`
automatically, so that path must keep working.

## The daily cycle

```
python daily.py                 # the live cycle
python daily.py --dry-run       # build and report; no commit, no push
python daily.py --skip-models   # publish the payloads the models already have
python publish.py --daily       # alias for the first form
```

`daily.py` is the once-a-day entry point:

1. run each sibling repo's own `daily` (`<repo>/.venv/Scripts/python.exe
   main.py daily`, from the repo's directory, 1800s timeout);
2. copy both `reports/site_payload.json` files into `payloads/`;
3. rebuild `docs/` (including `docs/data/*.json`);
4. commit and push to `origin` when there is anything to commit;
5. append one line to `logs/automation.log`.

A model repo that is missing, has no venv, fails, or hangs produces a warning
and the cycle continues with that sport's previous payload. One broken model
must not take the whole site down, and a stale-but-honest page beats no page.

Use `--dry-run` to rehearse: it does everything except stage, commit and push,
and prints the paths that *would* be committed.

The log line looks like:

```
2026-10-24T09:14:07Z daily nba=OK nfl=FAIL site=changed pushed=y
```

`logs/` is gitignored (only `logs/.gitkeep` is tracked) — it is a local
operational record, not site content.

## Scheduling (the canonical setup)

This repo's `daily.py` is the ONE thing to schedule: it runs both model
repos' `daily` and then builds, commits and pushes. Per-repo entries are
only a fallback (see each model's README).

Target: **03:00 America/Los_Angeles**, timezone-pinned rather than
assuming the machine's clock.

Pin the interpreter too: use a model repo's venv python, which has the
`tzdata` package. The build falls back to a built-in US-Pacific DST rule
when `zoneinfo` has no database (verified to render byte-identical
output), but a real tz database is the better default.

**cron** (Vixie/Debian — `CRON_TZ` applies to entries that follow it; on
cron implementations without `CRON_TZ`, set `TZ=America/Los_Angeles` in
the crontab instead):

```cron
CRON_TZ=America/Los_Angeles
# nightly full cycle at 03:00 PT
0 3 * * * cd /path/to/predictions-site && ../nfl-model/.venv/bin/python daily.py >> logs/automation.log 2>&1
# intraday revision checks, hourly 06:00-20:00 PT (each model's sync
# exits immediately once the day's first game has started)
0 6-20 * * * cd /path/to/nfl-model && .venv/bin/python main.py sync >> logs/automation.log 2>&1
5 6-20 * * * cd /path/to/nba-model && .venv/bin/python main.py sync >> logs/automation.log 2>&1
```

**launchd** (macOS, `~/Library/LaunchAgents/com.predictions.daily.plist`)
— launchd fires on system-local time, so pin TZ explicitly:

```xml
<key>EnvironmentVariables</key><dict>
  <key>TZ</key><string>America/Los_Angeles</string></dict>
<key>WorkingDirectory</key><string>/path/to/predictions-site</string>
<key>ProgramArguments</key><array>
  <string>/path/to/nfl-model/.venv/bin/python</string><string>daily.py</string></array>
<key>StartCalendarInterval</key><dict>
  <key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
<key>StandardOutPath</key><string>/path/to/predictions-site/logs/automation.log</string>
<key>StandardErrorPath</key><string>/path/to/predictions-site/logs/automation.log</string>
```

**Windows Task Scheduler** (set the machine TZ to Pacific, or schedule
the Pacific-equivalent local time):

```powershell
$act  = New-ScheduledTaskAction -Execute "C:\path\to\nfl-model\.venv\Scripts\python.exe" `
        -Argument "daily.py" -WorkingDirectory "C:\path\to\predictions-site"
$trg  = New-ScheduledTaskTrigger -Daily -At 3:00am
$set  = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable
Register-ScheduledTask -TaskName "predictions-daily" -Action $act -Trigger $trg -Settings $set
```

**Waking the machine.** A scheduler cannot run on a sleeping host unless
you ask it to wake:

- macOS: `sudo pmset repeat wakeorpoweron MTWRFSU 02:55:00`
- Windows: enable *Power Options → Sleep → Allow wake timers*, plus the
  `-WakeToRun` setting above.
- A fully powered-off machine cannot be woken by cron/launchd; use
  `wakeorpoweron` (Mac) or BIOS wake-on-RTC, or run the job on an
  always-on host.

`StartWhenAvailable` / `anacron`-style catch-up matters: a missed 03:00
run is harmless because `daily` is idempotent — re-running it appends
nothing and publishes nothing when nothing changed.

## Tests

The site code is stdlib-only, so any Python with pytest works. This repo has
no venv of its own; the sibling NFL repo's venv is convenient:

```
../nfl-model/.venv/Scripts/python.exe -m pytest -q
```

| File | Covers |
| --- | --- |
| `tests/test_build.py` | page rendering, empty states, site-wide invariants |
| `tests/test_units.py` | settlement arithmetic, Pacific window boundaries |
| `tests/test_dashboard.py` | the P/L dashboard, units chart, `docs/data`, v1 payloads |
| `tests/test_ats_pricing.py` | priced spreads, partial odds coverage, the odds methodology |
| `tests/test_revisions.py` | the revision disclosures |
| `tests/test_daily.py` | the daily cycle, dry runs, the run log |

Fixture payloads: `nfl.json` / `nba.json` are v1 (no `settle`), `empty.json` is
the pre-season state, `nfl_priced.json` is a full v2 NFL slate, and there are
two NBA v2 slates — `nba_unpriced.json` (no odds at all, the record-only path)
and `nba_priced.json` (mixed coverage: spread + moneyline, spread only,
neither, and a push).

## Payload schema

The builder reads schema **v2** and tolerates **v1** (the pre-P/L payloads):
missing `settle`, `revisions` and `ml_price` keys are treated as absent, so a
v1 payload builds cleanly and simply reports no units. That matters during a
rollout where the two model repos may upgrade at different times.

Schema v2 adds, per upcoming entry:

```jsonc
"ml_price": -145 | null,
"revisions": [ /* as below */ ]
```

and per history entry:

```jsonc
"settle": {
  "spread_line": -3.5 | null, "spread_price": -110 | null,
  "ml_price": -180 | null,    "ml_result": "win" | "loss" | "push" | null
},
"revisions": [{
  "logged_at": "2026-09-24T13:00:00+00:00", "pick": "PHI",
  "pick_prob": 0.61, "pred_margin": -4.0,
  "spread_line": -3.0 | null, "ml_price": -165 | null,
  "post_kickoff": false
}]
```

A graded game with more than one revision renders a `<details>` disclosure on
the track record listing the original pick and every edit with its timestamp.
Revisions with `post_kickoff: true` are labelled *"logged after kickoff — not
graded"*: a pick changed once the ball is in the air is not a prediction, and
the site says so rather than quietly showing the improved number.

Every one of those keys is optional as far as the builder is concerned. It
tolerates a missing `settle.spread_price` (older rows, and every NFL row), a
null `ats_result`, a wholly absent `settle` block (v1), and an NBA payload
mixing priced and unpriced games inside one slate. `settle.spread_price` is
absent-or-null on NFL by construction; it is a real American price on NBA
whenever a provider returned one.

## Notes on choices made here

* The dashboard cell for a league shows ATS and moneyline units **combined**
  into one figure, since a reader wants "how did the NFL model do", not two
  numbers to add up. The per-market split lives on the track record page.
* Every units figure is printed with an explicit sign (`+1.24u`, `-0.76u`), so
  the green/red colour coding is reinforcement rather than the only cue. Both
  colours are defined for light and dark themes as CSS variables.
* The cumulative-units chart plots one point per calendar date (multi-game
  days collapse to their end-of-day total) and is skipped entirely when there
  is nothing graded — the same convention as the running-accuracy chart, which
  is unchanged, as is the 200-row cap on the history table.
* The record shown for an unpriced league is the straight-up (pick-the-winner)
  record, since that is the only thing that can honestly be scored without
  prices.
* The partial-coverage note counts **all-time** graded games, not the games in
  the row you are looking at. A per-window count would need a note per cell;
  one honest all-time sentence per league is easier to read and cannot be
  misread as a claim about today.
* A league whose payload still reports `record.ats: null` but whose `settle`
  blocks carry spreads gets its ATS W-L-P row derived from those settled bets.
  The site should lead the model repos on this, not wait for them.
* `docs/` in this commit is a **preview built from `tests/fixtures/`** so the
  new NBA units rendering is reviewable in a diff. It is fixture data, not
  live data — the next `daily.py` / `publish.py` run overwrites it (including
  `docs/data/*.json`) with the real payloads.
