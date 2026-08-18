# predictions-site

A tiny static site publishing the picks and track record of two hobby sports
prediction models (NFL and NBA). Plain HTML plus one CSS file, zero
JavaScript, built with the Python 3 standard library only — no dependencies
to install. Served by GitHub Pages from `main:/docs`.

**These are the outputs of a hobby statistical model, published for fun and
transparency. Not betting advice.** Neither model has a betting edge — both
sit near 50% against the spread with vig-negative ROI, which is the expected
honest result against closing lines. See the site's Methodology page.

A **closing-line-value paper trail** is published alongside the record — a
morning line-and-price snapshot per pick against a closing one. It is a paper
trade, not a betting system: nothing is staked and nothing is recommended. See
[Closing line value](#closing-line-value-display-only-and-a-paper-trail).

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

## The footer publisher stamp (headless monitoring)

Every page footer carries the disclaimer and one freshness line:

```
Last updated 2026-08-17 20:25 UTC from vps3508171
```

This is the site's own health check. Once the VPS runs the daily cycle
unattended, nobody logs into the box to see whether it is still alive — but
anyone can load the page and read the last successful publish off the footer.
A timestamp that stopped moving means the scheduler stopped running; a
hostname you did not expect means the site is being published from somewhere
you did not intend.

Two deliberate choices:

* **The timestamp is the *build* clock, not the payloads' `generated_at`.**
  The site is only ever as fresh as its last successful publish. A payload can
  be days older than the run that shipped it (an export failed and the
  previous payload was reused, say) — reporting the payload's age would hide
  exactly the failure the stamp exists to surface.
* **The publisher comes from the build environment, not from any file.**
  `build.resolve_publisher()` uses `socket.gethostname()`, shortened to its
  first label so `vps3508171.hosting.example.net` reads as `vps3508171`. Set
  `SITE_PUBLISHER` to override it verbatim when the provider's hostname is
  meaningless and you would rather label the box:

  ```
  SITE_PUBLISHER=vps-prod python daily.py
  ```

  A blank or whitespace-only value is ignored, and a host that will not name
  itself publishes as `unknown-host` rather than an empty footer.

### How this interacts with no-op publishing

`publish.py` refuses to commit a rebuild whose only diff is the run's own
timestamps (see [The daily cycle](#the-daily-cycle)), and the stamp is built
to respect that split:

| What changed | Committed? | Why |
| --- | --- | --- |
| The build clock only | no | `_VOLATILE_TS` masks it — otherwise the site churns a commit a day |
| The publishing host | **yes** | a hostname is not a timestamp; moving boxes is real news |
| Both | **yes** | the host change survives the masking |

`tests/test_daily.py` pins all three rows, so a future change to the footer's
wording cannot quietly reintroduce daily commit churn or, worse, silently
swallow a host change.

## The prediction horizon (and one deliberate asymmetry)

The model repos publish live predictions only for games starting **3–7 days
out** (targeting 3–5, hard max 7). Nearer than that, a prediction is still
being revised; further out, none is made at all. Each payload states the
window in a top-level `policy` block, and **this repo never hardcodes the
numbers** — every sentence on the site is formatted from that block, so
changing the window is a payload change, not a code change. A payload with no
`policy` block gets no policy prose anywhere rather than prose quoting a
window nobody chose.

**Picks page.** Only entries with `in_window: true` are shown. The payload
deliberately stays complete (it still carries legacy far-future picks with
`in_window: false`, and `docs/data/*.json` publishes all of them); filtering
for display is this repo's job. A payload with no `in_window` key *anywhere*
predates the contract and every upcoming entry is shown — "no key" is not the
same statement as `in_window: false`, and an old payload must never be able to
blank the picks page.

Three picks-page states, each a calm sentence rather than a blank or an error:

| State | What the page says |
| --- | --- |
| games in window | the pick cards |
| upcoming games, none in window | *"Nothing is inside the publishing window yet. The next games on the schedule start further out than 7 days…"* |
| no upcoming entries at all | *"No upcoming picks logged yet — check back at the start of the season."* |

The middle one is the common case right now: it is the off-season and nothing
is in window. It is distinguished from the third because they are genuinely
different facts, and a reader landing on the page deserves to know which one
they are looking at.

**Track record: the asymmetry.** A handful of historic rows (16 NFL week-1, 3
NBA opening-night) were predicted long before the policy existed. The
prediction log is append-only, so they are kept and flagged
`out_of_policy: true` rather than deleted, and then treated *two different
ways on purpose*:

* **Excluded from every units and P/L figure** — ATS, moneyline, the
  cumulative chart, every window. The exclusion works exactly like an
  unbetable game: not a loss, not a 0.0, simply never a bet. Crediting units
  to picks the current policy would never have published would overstate what
  this site does.
* **Kept in the straight-up accuracy record.** They were real graded
  predictions, and dropping them from the accuracy record would *flatter* it.

That is the honesty trade, and it is stated rather than hidden: the rows stay
visible on the track record badged *"outside window"* (with a `title` and a
screen-reader explanation, *"predicted before the 3–7 day policy; excluded
from P/L"*), their Units cell is an em dash carrying the same explanation, and
a note under the charts counts them: *"2 graded games were predicted outside
the current 3–7 day policy and are excluded from P/L. They are still counted
in the straight-up record above, so straight-up covers more games than the
units do."* The Methodology page carries the long-form version.

Backtests are unaffected. This is a live-publication policy, not a modelling
change.

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
* **Out-of-policy games are excluded from every units figure**, and from
  `units.coverage()` — they are missing from the P/L for a policy reason, not
  an odds reason, and folding them into the "no odds logged" count would blame
  the odds provider for a decision the model repo made. `coverage()` therefore
  describes only the games eligible for P/L; `units.out_of_policy_count()`
  counts the rest. `su_record()` is the one function that keeps them.
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

## Closing line value (display only, and a paper trail)

The model repos are accumulating a CLV paper trail: a **morning** line-and-price
snapshot logged with each pick, and a **closing** snapshot taken shortly before
tip-off/kickoff. The track record renders it beside the units, per league.

**This site computes no CLV of its own.** Every figure is read straight from the
payload — `record.clv` for the summary and a per-game `clv` block for the rows —
because only the repo that made the pick knows what the two snapshots were.
`build.py` formats; it does not derive.

**It is a paper trade, not a betting system**, and the block says so on its face
every time it renders. There is deliberately nothing here that resembles
hedging, cash-out, alerts or bet sizing, and there never should be.

What the block shows:

* **Mean CLV** in percentage points (`mean_clv_pp`) as the headline, because
  percentage points are unambiguous, with `mean_clv_cents` beside it *when the
  payload has it* — a line-only snapshot source has no cents and none are
  invented.
* **The directional hit rate** (`hit_rate`) — the share of picks whose close
  moved toward the model — quoted with its n. The n is `n_graded - no_move`,
  the moved lines, matching both studies' convention.
* **`no_move` on its own tile**, never folded into that hit rate: a line that
  never moved is neither a hit nor a miss, and both studies report it
  separately for exactly that reason. The count is shown even when it is 0.
* **Mean line movement** in points (`mean_line_move`).
* **The bucket table** by disagreement size, straight from `buckets`.
* **The large-disagreement slice** (`large_disagreement`) on its own clearly
  labelled line, called out because it is the study's live hypothesis. It is
  driven purely by that key being present — *never* by a league name, in
  keeping with the rest of this repo. Ship the key from NBA instead and the
  line moves to NBA; `tests/test_clv.py` asserts precisely that.
* **`n_ungraded`**, whenever it is non-zero: picks with only one of the two
  snapshots are excluded from every figure above and the page says how many
  were skipped rather than dropping them silently.

Three states, all decided by the payload and none by the league:

| Payload | Renders |
| --- | --- |
| no `clv` anywhere | nothing — no heading, no empty grid, no zeros |
| `clv` present, `n_graded: 0` | *"No CLV data yet — CLV is recorded from the first morning snapshot onward"* |
| `clv` present, graded picks | the full block above |

The first row is a hard compatibility guarantee, and it is tested the strict
way: `tests/fixtures/nfl_clv.json` is `nfl_priced.json` **plus CLV keys and
nothing else**, so a test can strip every `clv` key back out and assert the
rendered pages are **byte-for-byte identical** to the pre-CLV build.

Per-game rows gain a **Line move** column whenever at least one graded game has
`clv.graded: true` — the same data-driven rule the ATS and Units columns follow.
A graded row shows the movement and the book that priced the close, with the
full `morning → close` pair (line, price, book) in the `title`. A row whose
snapshots are incomplete shows an em dash with a `title` and a screen-reader
explanation, exactly as the Units column already handles a game with no odds.

**CLV is not money, so it borrows none of the win/loss palette.** Units are
green and red; CLV figures are plain ink with an explicit printed sign. A line
moving your way is information about the model, not a profit, and colouring it
like a P/L would quietly claim otherwise.

### What the CLV study found, and why the site only paper-trades

The Methodology page carries a short note, and it is **static prose** rather
than payload-driven: it reports a completed retrospective study, not today's
data, so it renders regardless of what the payloads contain. In brief —

* there is a **real directional signal in both sports**: the close moves toward
  the model more often than chance, and more so the more the model disagrees
  with the opener;
* **NFL landed essentially on the breakeven line** — 52.43% against a 52.38%
  breakeven betting the opener at an assumed -110 — and **the sign of that
  verdict is unresolved**, because the study's source published lines *without
  prices*: the same record re-priced at -105 is positive (+2.28%) and at -115
  is negative (-1.92%);
* **NBA was decisively negative** (-4.89%, CI excluding zero), and the
  reconciling reason is that **the opening line already forecasts better than
  the model** (margin MAE 10.38 vs 10.66) — CLV is a necessary condition for a
  betting edge, not a sufficient one;
* therefore the site **records a forward paper trail with real prices**; it does
  not run a betting system. No stakes, no advice.

Several of those figures are pinned by `tests/test_clv.py` so they cannot be
quietly softened later. The upstream studies are `../nfl-model/clv_study.md`
and `../nba-model/clv_study.md`.

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
# Optional: label this box in the footer stamp instead of using its hostname.
SITE_PUBLISHER=vps-prod
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
| `tests/test_build.py` | page rendering, empty states, site-wide invariants, the footer publisher stamp |
| `tests/test_units.py` | settlement arithmetic, Pacific window boundaries |
| `tests/test_dashboard.py` | the P/L dashboard, units chart, `docs/data`, v1 payloads |
| `tests/test_ats_pricing.py` | priced spreads, partial odds coverage, the odds methodology |
| `tests/test_revisions.py` | the revision disclosures |
| `tests/test_daily.py` | the daily cycle, dry runs, the run log, publish idempotency |
| `tests/test_policy.py` | the prediction horizon: picks filtering, both empty states, out-of-policy exclusions, back-compat |
| `tests/test_clv.py` | the CLV block, the large-disagreement line, the empty state, the byte-for-byte no-CLV regression, the methodology note's numbers |

Fixture payloads: `nfl.json` / `nba.json` are v1 (no `settle`), `empty.json` is
the pre-season state, `nfl_priced.json` is a full v2 NFL slate, and there are
two NBA v2 slates — `nba_unpriced.json` (no odds at all, the record-only path)
and `nba_priced.json` (mixed coverage: spread + moneyline, spread only,
neither, and a push).

Two more carry the horizon policy: `nfl_policy.json` (two in-window picks, one
legacy far-future pick, two graded games in policy and two out of it — chosen
so that excluding the flagged games moves the units from +0.82u to -0.09u
while leaving the 2-2 straight-up record untouched) and
`nba_policy_offseason.json` (nothing in window at all, plus one graded game
out of policy, which is the off-season empty state and the singular wording of
the exclusion note).

Two more carry CLV, and each is its priced counterpart **plus `clv` keys and
nothing else** — that is what makes the byte-for-byte no-CLV regression test
possible. `nfl_clv.json` has priced snapshots (so cents are shown), five graded
picks including one whose line never moved, two with only a morning snapshot,
one pending pick with no `clv` key at all, and a `large_disagreement` slice.
`nba_clv.json` has a line-only snapshot source (no prices, so no cents), three
graded picks, one incomplete, and `large_disagreement: null` — so a single
build exercises both halves of every tolerance rule.

## Payload schema

The builder reads schema **v2** and tolerates **v1** (the pre-P/L payloads):
missing `settle`, `revisions` and `ml_price` keys are treated as absent, so a
v1 payload builds cleanly and simply reports no units. That matters during a
rollout where the two model repos may upgrade at different times.

The **horizon-policy keys** are the newest addition and are likewise optional
— a payload without them renders exactly as it did before. At the top level:

```jsonc
"policy": {"min_days": 3, "max_days": 7}
```

per upcoming entry:

```jsonc
"horizon_days": 4.2,       // days from prediction time to tip-off/kickoff
"in_window": true,         // 0 <= horizon_days <= max_days
"out_of_policy": false     // predicted outside the policy
```

and per history entry:

```jsonc
"out_of_policy": false     // the settling prediction was made outside policy
```

The **CLV keys** are newer still and equally optional. Per history entry:

```jsonc
"clv": {
  "morning_line": -3.0 | null, "morning_price": -110 | null,
  "morning_book": "DraftKings" | null,
  "close_line": -4.5 | null,   "close_price": -115 | null,
  "close_book": "Pinnacle" | null,
  "line_move_toward_model": 1.5 | null,   // points, signed toward the model
  "clv_pp": 4.5 | null,                   // percentage points
  "clv_cents": 5.0 | null,                // cents of price
  "disagreement": 2.4 | null,             // |model - morning line|, points
  "graded": true                          // both snapshots present
}
```

and on `record`:

```jsonc
"clv": {
  "n_graded": 5, "n_ungraded": 2,
  "hit_rate": 0.5 | null,                 // a fraction, like su_acc
  "no_move": 1,
  "mean_line_move": 0.4 | null,           // points
  "mean_clv_pp": 1.2 | null,
  "mean_clv_cents": 0.2 | null,
  "buckets": [{"label": "2+", "n": 2, "hit_rate": 1.0,
               "mean_line_move": 1.75, "mean_clv_pp": 5.25}],
  "large_disagreement": {"label": "|d|>2", "n": 2, "hit_rate": 1.0,
                         "mean_line_move": 1.75} | null
}
```

Rates are **fractions** (`0.5` = 50%), matching `su_acc` and `record.ats.pct`
elsewhere in the payload. `mean_clv_pp` and `clv_cents` are already in their
units and are printed as given. Every one of these keys may be absent, null or
non-numeric: a missing figure renders an em dash and a missing block renders
nothing at all. A `clv` that is not an object is ignored outright.

`min_days` / `max_days` may arrive as `3` or `3.0`; both render as "3". A
missing `out_of_policy` is `false`, so every pre-policy payload stays fully
inside P/L scope. Only `in_window` drives the picks page, and only
`out_of_policy` drives the units exclusion — the site never re-derives either
from `horizon_days`, because only the repo that made the pick knows how far
out the game was *at the time it was predicted*.

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
* The horizon policy is read from **whichever payload states one first**, in
  the fixed NFL-then-NBA order. Both repos emit the same window, so a
  disagreement would be a bug in one of them; taking the first is
  deterministic and never invents a blended window that neither repo uses.
* The policy sentence sits on the picks page only once, under the heading,
  rather than once per league. Both leagues share the window, and repeating it
  per section would read like a per-sport rule.
* `in_window` as the contract defines it (`0 <= horizon_days <= max_days`)
  admits games *nearer* than `min_days`, so a pick made at four days out is
  still displayed on the day before the game rather than vanishing from the
  page as the game approaches. That is the contract's intent and the site
  follows it literally instead of re-filtering on `min_days`.
* Out-of-policy rows are styled quieter (`--ink-secondary`) but never hidden,
  greyed out to illegibility, or coloured like a loss. The badge marks a
  *scope*, not a bad result, so it deliberately borrows none of the win/loss
  palette.
* The CLV hit rate is quoted against the **moved** lines (`n_graded -
  no_move`), not against every graded pick, because that is the denominator
  both studies use and because a line that never moved is not evidence either
  way. The site derives that one subtraction and nothing else; if the payload's
  two counts disagree with each other it falls back to quoting `n_graded`
  rather than printing a denominator it cannot justify.
* The large-disagreement slice gets its own line rather than a row in the
  bucket table, because it is a *different claim* — the open hypothesis, not
  another bucket — and burying it in the table would read as one bucket among
  five.
* CLV figures deliberately use no colour. Units are green and red; a line
  moving toward the model is information, not profit, and giving it the P/L
  palette would imply money that this site explicitly does not claim.
* The methodology CLV note is static prose, not payload-driven. It reports a
  finished study, so it should not appear and disappear as payloads change —
  and keeping it static is what lets the no-CLV regression test assert every
  page byte-for-byte.
* `docs/` in this commit is a **preview built from `tests/fixtures/`**
  (`nfl_clv.json` + `nba_clv.json`, clock pinned to 2026-10-24) so the CLV
  block, the large-disagreement line, the `Line move` column and the em-dashed
  ungraded rows are all reviewable in a diff. It is fixture data, not live data
  — the next `daily.py` / `publish.py` run overwrites it (including
  `docs/data/*.json`) with the real payloads. The previous preview was built
  from the horizon-policy fixtures; regenerate that pairing if you need to
  review the out-of-policy rows again.

## Production deployment

The site is built and pushed by **models-vps** (`vps3507025`, user `model`),
which also hosts the MLB model; schedules are staggered apart. Migrated from
amazin-vps on 2026-08-17.

| | |
|---|---|
| Path | `~/models/predictions-site` |
| Schedule | `daily.py` at `03:03` **America/Los_Angeles** (host clock is Eastern; `CRON_TZ` pins it) |
| Interpreter | `~/models/nfl-model/.venv/bin/python` (has `tzdata`, so the Pacific windows use a real tz database) |
| Logs | `~/models/predictions-site/logs/automation.log` |

The footer of every page names the publishing host, so `from vps3507025`
is the at-a-glance confirmation that production is the box you think it is.
