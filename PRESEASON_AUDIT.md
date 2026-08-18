# PRE-SEASON ACCEPTANCE AUDIT — 2026-08-17

Scope: the full sports-model pipeline (nfl-model, nba-model,
predictions-site) as deployed on **models-vps** (`vps3507025`), audited
before the 2026 NFL season opens. Method: every item below produced
evidence — command output, file hashes, rendered artifacts — not
assurances. Sandboxed items ran in throwaway clones on the VPS
(`~/audit-rehearsal`, `~/audit-rollover`, both destroyed afterwards);
production was touched only where an item sanctioned it (items 4 and 5).
The real prediction logs are diff-proven unchanged at the bottom.

## Item 1 — full-lifecycle dress rehearsal (sandboxed, simulated clock, mock odds) — **PASS**

Sandbox clones on the VPS, driven through the modules' own injection
seams (`now=`, `provider_events=`, `fetch_events=`, `grade_log(results)`,
`build(..., now=)`); zero real odds calls; simulated date 2026-09-13.

| Sub-check | Verdict |
|---|---|
| `daily` at sim 03:03 PT | PASS |
| Prediction rows carry the SHOPPED line/price/book | PASS |
| Line shopping exercised both ways (line-first: fanduel +3.5/−115 beat pinnacle +5.0/−105; price-tiebreak at equal lines: pinnacle −104 won) | PASS |
| Closing snapshots: toward / against / crossing zero; unquoted games stay open | PASS |
| Injected finals graded via `grade_log(results=...)` | PASS |
| Units + CLV hand-check reproduced by payload AND the site units engine | PASS |
| `record.clv` `\|d\|>2` slice present when a game qualifies | PASS |
| Legacy Aug out-of-policy rows coexist with fresh in-window rows; fresh row settles; flag flips false | PASS |
| Rendered track record shows P/L, the CLV block, the `\|d\|>2` line, the disclaimer | PASS |
| NBA lifecycle no-ops cleanly (no games) | PASS |

Hand-check (2026_01_WAS_PHI): morning PHI +3.5@−115 (fanduel) → close
+2.5@−110 (pinnacle) → `line_move_toward_model` = −1.0 (against),
`clv_pp` = −1.107, `clv_cents` = −5; final PHI by 7 → ATS +0.8696u at
−115, ML +0.5051u at −198. Every number reproduced end-to-end.
Observation (not a failure): `run_daily` stamps its log rows on the wall
clock (no `now=` seam); morning/close/sync are fully clock-injectable.

## Item 2 — season rollover (sandboxed) — **PASS**

| Sub-check | Verdict |
|---|---|
| NFL 2026 pbp EMPTY: refresh survives, features rebuild, 272 schedule-only rows | PASS |
| NFL partial week 1: played teams' EWMAs moved; control team bit-identical | PASS |
| Stale-model refusal fires (`trained through 2026-02-08, newest result 2026-09-14`), `needs_retrain` True | PASS |
| Leakage/truncation tests on partially-refreshed caches (8 passed) | PASS |
| NBA "2026-27" ingest + refresh end-to-end vs real stats.nba.com (0-row REG cached cleanly, schedule 1,206 games, features 20,457) | PASS |
| Season-id arithmetic (`current_season()`="2025-26" today, "2026-27" from Oct) | PASS |

Also re-confirmed: un-mocked 2026 pbp raises the non-transient
`ValueError` that `_retry` correctly refuses to retry. Observation filed:
an ~1e-5 intra-game ordering artifact in season-boundary league means
(home row processed before away); does not trip any leakage invariant.

## Item 3 — recovery drill from the private backups (PC, temp dir) — **PASS**

Fresh clones of all three repos from the private remotes; `.env` + 38 MB
of caches restored; venvs built; **nfl 498 / nba 566 / site 251 tests
passed**; one backtest per repo matched the PC-canonical numbers to all
six decimals (NFL 0.671474/0.211486, NBA 0.646913/0.218798); prediction
logs content-identical to production (the only byte difference is
`.gitattributes` LF vs Windows CRLF — documented). Whole drill ≈ 4 min
20 s plus venv builds. The exact commands are now the restore runbook in
`OPERATIONS.md`.

## Item 4 — ops hardening on models-vps — **PASS**

- **Cron survives reboot**: `cronie` is systemd-`enabled` and `active`;
  the crontab is persisted in `/var/spool/cron/crontabs`. Evidence in
  session log; the box last rebooted 2026-08-07 and the daemon came back.
- **Disk-space guard**: `daily.py` now checks free space FIRST and below
  2 GiB (override `MIN_FREE_GB`) aborts loudly — banner to stderr,
  `DISK-GUARD ABORT` in automation.log, exit 1, nothing run. Live line
  after deploy: `... disk_free_gb=59.7 ...` at 60G free. 18 new tests.
- **Log rotation active**: isolated-HOME activity test rotated an
  oversized log to `.1.gz` and left a small one alone; a missing-dir bug
  in the rotation audit trail was found by that test and fixed.
- **Healthcheck**: if `HEALTHCHECK_URL` is set (env or site `.env`), one
  GET after each fully-successful daily; `healthcheck=ok|failed|unset` in
  the run line; never pinged on failed or dry runs. Currently `unset`
  (no URL configured) — verified live.

## Item 5 — quota audit — **FAIL as found → remediated → PASS**

Found: with the shipped `CLOSE_DAILY_CAP = 10`, a worst-case in-season
month (both sports on the shared primary key, 2 credits/call for
`h2h,spreads`, 1 baseline call + cap forced closes per sport per game
day; NBA 31 game days, NFL 18) prices at:

| cap | credits/month | ParlayAPI 1,000 | The Odds API 500 (full failover) |
|---|---|---|---|
| **10 (as found)** | **1,078** | **0.93× — OVER QUOTA** | 0.46× |
| 5 | 588 | 1.70× | 0.85× |
| **4 (remediation)** | **490** | **2.04× — PASS** | 1.02× |
| 3 | 392 | 2.55× | 1.28× |

Remediated in both repos (`CLOSE_DAILY_CAP`/`MAX_CLOSE_CALLS` 10 → 4,
with this arithmetic in comments beside the constants), committed,
pushed, deployed. Coverage survives because each close call prices the
whole due slate and NBA tips cluster into ~4 windows a night; anything
missed stays CLV-ungraded, never assumed. Residual risk, accepted and
documented: a full-month primary outage fits the fallback tier at only
1.02× — the playbook says to halve the caps if an outage persists.

## Item 6 — OPERATIONS.md — **PASS**

Written to this repo: the complete schedule map (all 8 cron entries plus
the 5 MLB systemd timers, with timezones and the off-the-tens minute
policy), healthy-state signals, the failure playbook (odds providers,
nba_api, VPS loss, git conflicts, stale-model, disk guard), the restore
runbook exactly as executed in item 3, the quota budget, and the
Sept 3 / Sept 9-10 / Oct 13 / Oct 20-21 / DST calendar.

## Item 7 — final sweep — **PASS**

Suites (post-remediation code everywhere):

| Repo | PC | models-vps |
|---|---|---|
| nfl-model | 498 passed | 498 passed |
| nba-model | 566 passed | 565 passed + 1 skip (study-only `lxml`, absent on prod by design) |
| predictions-site | 269 passed | 269 passed |

Canonical reports intact (VPS SHAs unchanged through the whole audit:
NFL `a6fceb3996de…`, NBA `ab2b06a82717…`). All trees clean, all repos
pushed including private backups (verified below).

## Diff-proof — the real prediction log gained no row

Baseline captured before any audit work; re-hashed after all of it:

| File | Baseline | After audit |
|---|---|---|
| VPS nfl predictions_log.csv | 33 lines, `bf311e65f7655de6a175c09f` | 33 lines, `bf311e65f7655de6a175c09f` — identical |
| VPS nba predictions_log.csv | 7 lines, `d3f32b15a1c53a1b5c055694` | 7 lines, `d3f32b15a1c53a1b5c055694` — identical |
| PC nfl predictions_log.csv | 33 lines, `bf311e65f7655de6a175c09f` | identical |
| PC nba predictions_log.csv | 7 lines, `2137a1f6f502555982e8b0b8` | identical (differs from VPS by CRLF only) |
| clv_snapshots.csv (both repos, both hosts) | absent | still absent — no snapshot was ever written to production |

Both sandboxes destroyed and shown gone.

## Final table

| # | Item | Verdict |
|---|---|---|
| 1 | Dress rehearsal (sandboxed lifecycle, mock odds, line shopping, CLV hand-check, legacy coexistence, rendered site) | **PASS** |
| 2 | Season rollover (NFL empty/partial pbp, stale refusal, NBA 2026-27 end-to-end) | **PASS** |
| 3 | Recovery drill from private backups (restore proven, numbers match) | **PASS** |
| 4 | Ops hardening (cron reboot, disk guard, rotation, healthcheck) | **PASS** |
| 5 | Quota audit | **FAIL as found (0.93×) → cap 10→4 → PASS (2.04×)** |
| 6 | OPERATIONS.md | **PASS** |
| 7 | Final sweep (suites both hosts, trees clean, reports intact, all pushed) | **PASS** |
| — | Production untouched except items 4/5; prediction logs gained zero rows | **PROVEN** |
