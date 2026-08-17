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
build.py            payloads -> docs/ (index, track-record, methodology)
publish.py          export payloads from the model repos, build, commit, push
docs/               generated output, served by GitHub Pages
tests/              pytest suite with fixture payloads
```

`docs/` is fully regenerated on every build; never edit it by hand.

## Building

```
python build.py
```

Reads `payloads/nfl.json` and `payloads/nba.json` (either may be missing —
that sport renders in an empty state) and writes the site into `docs/`.

## Publishing

```
python publish.py               # export + build + commit + push
python publish.py --skip-export # reuse whatever is already in payloads/
```

Without `--skip-export`, publish.py runs each sibling model repo's exporter
(`../nfl-model` and `../nba-model`, via each repo's own venv:
`.venv/Scripts/python.exe main.py site-payload`). A failed export prints a
warning and the previous payload is reused. It then copies each repo's
`reports/site_payload.json` into `payloads/`, rebuilds `docs/`, commits
(`publish: <UTC timestamp>`, skipped cleanly when nothing changed), and
pushes to `origin main` if a remote named `origin` is configured.

Each model's `weekly` command triggers `publish.py` automatically, so the
site normally updates itself whenever a model runs its weekly cycle. A cron
fallback works too, e.g. every Tuesday at 09:00:

```
0 9 * * 2 cd /path/to/predictions-site && python publish.py
```

## Tests

The site code is stdlib-only, so any Python with pytest works. This repo has
no venv of its own; the sibling NFL repo's venv is convenient:

```
../nfl-model/.venv/Scripts/python.exe -m pytest -q
```
