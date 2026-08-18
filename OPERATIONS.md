# OPERATIONS

The complete operating manual for the sports-model pipeline in production.
Production host: **models-vps** (`vps3507025`, user `model`, host clock
America/New_York). All sports-pipeline cron entries are pinned to
**America/Los_Angeles** via `CRON_TZ`, so times below are Pacific unless
marked ET. Everything here was verified live in the 2026-08-17 pre-season
audit (`PRESEASON_AUDIT.md`).

## Schedule map — everything that runs on this box

### Ours (user crontab, CRON_TZ=America/Los_Angeles)

| PT time | What | Where it logs |
|---|---|---|
| 03:03 daily | `predictions-site/daily.py` — disk guard, NFL `daily`, NBA `daily` (grade → refresh → retrain-if-needed → predict → export → backup push), site build, publish, healthcheck ping | `predictions-site/logs/automation.log` (+ each model's own log) |
| 06:00–20:00 at :07 | NFL `sync` — intraday revision check; exits in ms when nothing is in window or the first game started | `nfl-model/logs/automation.log` |
| 06:00–20:00 at :12 | NBA `sync` — same | `nba-model/logs/automation.log` |
| 08:02 daily | NFL `morning` — predict today's in-window games, fetch live odds, shop books, write the CLV baseline snapshot | `nfl-model/logs/automation.log` |
| 08:04 daily | NBA `morning` — same | `nba-model/logs/automation.log` |
| 09:00–21:00 at :48 | NFL `snapshot-close` — closing line/price for games starting within ~75 min (≤1 provider call per run, ≤4/day) | `nfl-model/logs/automation.log` |
| 09:00–21:00 at :52 | NBA `snapshot-close` — same | `nba-model/logs/automation.log` |
| Sun 04:33 | `ops/rotate-logs.sh` — self-contained rotation (1 MiB threshold, 8 gz generations; logrotate is not installed on this host) | `ops/rotation.log` |

### Not ours (the MLB model — systemd USER timers, Eastern; never touch)

| ET time | Timer |
|---|---|
| every 10 min on the tens | `mlb-tick` |
| 03:30 daily | `mlb-backup` |
| 04:00 daily | `mlb-offbox` |
| 09:30 daily | `mlb-morning` |
| Mon 10:30 | `mlb-weekly` |

Our cron minutes (02 03 04 07 12 33 48 52) are deliberately **off the
tens** so nothing ever lands on an `mlb-tick` fire; our jobs run
`nice -n 10` (the daily also `ionice -c2 -n7`) so they yield on this
1-vCPU box. Cron survives reboot: the daemon (`cronie`) is systemd
`enabled` and the crontab lives on disk in `/var/spool/cron/crontabs`.

## What healthy looks like

- `cd ~/models/nfl-model && ./.venv/bin/python main.py status` (same for
  nba): headline `OK last successful daily <26h`, exit 0. Exit 1 = STALE.
- `tail ~/models/*/logs/automation.log`: one `daily` line per day ending
  `backup:OK ... disk_free_gb=NN healthcheck=...`; `sync`/`morning`/
  `snapshot-close` lines with SKIP reasons out of season.
- The live site footer: `Last updated <UTC> from vps3507025`. A different
  host name or an old stamp during the season = investigate. (The stamp
  only advances when site CONTENT changes; `status` is the authoritative
  liveness check.)
- `healthcheck=unset` is normal until `HEALTHCHECK_URL` is set in
  `predictions-site/.env`; after that, `healthcheck=ok` on every
  successful daily, and silence at your monitor means trouble.

## Failure playbook

**Odds providers down / unpriced slate.** The odds step reports `SKIP`,
picks are logged with no prices, affected games end **CLV/units-ungraded
— never assumed**. Check quota: the fetchers log `x-requests-remaining`
at INFO after every real call. Provider order override:
`ODDS_PROVIDER_ORDER=theodds,parlay` in the model repo's `.env`. During a
sustained primary outage, halve the close caps (`CLOSE_DAILY_CAP` in
`nfl_model/forward.py`, `MAX_CLOSE_CALLS` in `nba_model/clv.py`) — the
fallback tier is half the primary's (see Quota).

**nba_api appears blocked.** A raw `curl` to stats.nba.com hanging is
NOT evidence — stats.nba.com blackholes non-nba_api header sets (Phase 1
finding, re-verified on both VPSes). Test with the library:
`./.venv/bin/python -c "from nba_api.stats.endpoints import leaguegamelog; print(len(leaguegamelog.LeagueGameLog(season='2025-26', timeout=45).get_data_frames()[0]))"`.
If genuinely blocked: the daily's refresh step degrades to FAIL, the rest
of the run continues on cached data, and the recovery is a PC-initiated
push (the PC has no inbound SSH): `tar czf - data | ssh models-vps "tar xzf - -C ~/models/nba-model"`.

**VPS unreachable.** The site simply goes stale (footer stamp stops
advancing). Bridge from the PC: `cd Projects/sports-models/predictions-site && python daily.py`
(the PC repos pull from the same remotes). Re-sync the VPS with
`git pull --rebase` in each repo when it returns; the paper-trail
rebase machinery reconciles the logs.

**Git conflict on the backup push.** The unattended path already handles
it: `backup_push` commits ONLY the paper trails, pulls `--rebase`, aborts
on conflict (`backup:FAIL ... stash-conflict` in the log) and never
wedges. Manual fix: `git rebase --abort` if mid-rebase, inspect
`git stash list` (auto-stashed artifacts are kept), resolve, push.

**Stale-model refusal.** Log line: `saved model is stale (trained through
X, newest result Y) — run python main.py retrain; using ad-hoc fit`. This
is a WARNING, not an outage — predictions still happen (ad hoc). The 3am
daily retrains automatically when new results exist; a manual
`main.py retrain` clears it immediately.

**Disk-guard abort.** The daily prints an unmissable banner, logs
`DISK-GUARD ABORT free_gb=... min_free_gb=...`, exits nonzero, and runs
NOTHING. Free space (old `~/backups` gz files are the usual growth),
rerun `daily.py`. Threshold override: `MIN_FREE_GB` (env or site `.env`).

## Restore from backup (verified 2026-08-17, full drill ~4.5 min + venv builds)

```bash
# 1. Pick a restore location
RESTORE=~/restore && mkdir -p "$RESTORE" && cd "$RESTORE"

# 2. Clone the three private backups (auth: harsha-1-src)
git clone https://github.com/harsha-1-src/nfl-model.git
git clone https://github.com/harsha-1-src/nba-model.git
git clone https://github.com/harsha-1-src/predictions-site.git

# 3. Restore secrets — MACHINE-SPECIFIC: .env is NOT in git; source it from
#    an existing machine's nba-model checkout (or the secrets store).
#    One file serves both models.
cp <old-machine>/nba-model/.env "$RESTORE/nba-model/.env"
cp <old-machine>/nba-model/.env "$RESTORE/nfl-model/.env"

# 4. Restore data caches — MACHINE-SPECIFIC: data/ is NOT in git (~38 MB);
#    copy from an existing machine, or rebuild with `python main.py ingest`.
cp -r <old-machine>/nfl-model/data/. "$RESTORE/nfl-model/data/"
cp -r <old-machine>/nba-model/data/. "$RESTORE/nba-model/data/"

# 5. Venv per model repo (Python 3.12)
for R in nfl-model nba-model; do
  cd "$RESTORE/$R" && python3 -m venv .venv
  ./.venv/bin/pip install -r requirements.txt pytest ruff tzdata lxml
done

# 6. Prove it: full suites (2026-08-17 counts: nfl 498, nba 566, site 269)
cd "$RESTORE/nfl-model"        && ./.venv/bin/python -m pytest -q; echo EXIT=$?
cd "$RESTORE/nba-model"        && ./.venv/bin/python -m pytest -q; echo EXIT=$?
cd "$RESTORE/predictions-site" && "$RESTORE"/nfl-model/.venv/bin/python -m pytest -q; echo EXIT=$?

# 7. Numeric parity: one backtest per model. The ALL row must match the
#    SAME machine's canonical numbers to 6 decimals; a different machine
#    differs in the 3rd-4th decimal (xgboost FP — see DECISIONS.md parity
#    entries). Linux-canonical: NFL 0.672826/0.211209, NBA 0.645448/0.218946.
#    PC-canonical: NFL 0.671474/0.211486, NBA 0.646913/0.218798.
cd "$RESTORE/nfl-model" && ./.venv/bin/python main.py backtest
cd "$RESTORE/nba-model" && ./.venv/bin/python main.py backtest

# 8. Paper-trail integrity (line endings normalized; clones check out LF,
#    Windows appends CRLF — content must be identical):
for R in nfl-model nba-model; do
  diff <(tr -d '\r' < "$RESTORE/$R/predictions_log.csv") \
       <(tr -d '\r' < <old-machine>/$R/predictions_log.csv) && echo "$R log OK"
done
```

## Quota budgets (audited; see PRESEASON_AUDIT.md item 5)

Both sports share the primary key. Every provider call requests
`h2h,spreads` = **2 credits**. Per sport per day: 1 cached baseline call
(daily/sync/morning share it) + up to **4** forced closing fetches
(`CLOSE_DAILY_CAP` / `MAX_CLOSE_CALLS` — lowered from 10 in this audit).

Worst-case in-season month (NBA slate all 31 days, NFL 18 game days):
`(18 + 31) × (1 + 4) × 2 = 490 credits` vs ParlayAPI's 1,000/month =
**2.04× headroom**. Fallback (The Odds API, 500/month) is only called on
primary gaps; a full-month primary outage would consume ~490 of 500
(1.02× — fits, thin; halve the caps if an outage persists). Realistic
usage is ~450/month. The caps live in code, with the audit arithmetic in
comments beside them.

## The calendar — what to check and when

| Date | What happens | What to verify |
|---|---|---|
| **Sept 3** | NFL opener (NE@SEA, Sept 9/10) enters the 7-day window | The 3am daily logs its first in-window predictions; the picks page shows the partial week-1 slate with live lines; `predictions_log.csv` gains fresh in-window rows next to the legacy August ones |
| **Sept 9/10** | First NFL game day | 08:02 morning pass prices the slate (shopped books in the log + `clv_snapshots.csv` morning rows); evening `snapshot-close` rows appear; next morning: `score-log` grades, site shows first real P/L and first CLV rows; the legacy out-of-policy rows resolve as documented (fresh row settles) |
| **Oct 13** | NBA opener (BOS@DET, Oct 20) enters the window | Same checks as Sept 3, NBA slate |
| **Oct 20/21** | First NBA game day | Same checks as Sept 9/10; ALSO the first week of NBA+NFL overlap — watch `x-requests-remaining` in the logs against the 490/month budget |
| Early Nov | US DST fall-back (Nov 1) | CRON_TZ handles it; spot-check the 03:03 daily fired once, not twice/zero, on Nov 1-2 |

## Log locations

- `~/models/{nfl-model,nba-model,predictions-site}/logs/automation.log` —
  one line per run, rotated Sundays (gz, 8 generations)
- `~/models/ops/rotation.log` — rotation audit trail
- `~/models/{nfl,nba}-model/predictions_log.csv` + `clv_snapshots.csv` —
  the append-only paper trails, committed to the private backups on every
  daily
