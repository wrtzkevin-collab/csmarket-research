# CSMarket Research

[![Tests](https://github.com/wrtzkevin-collab/csmarket-research/actions/workflows/tests.yml/badge.svg)](https://github.com/wrtzkevin-collab/csmarket-research/actions/workflows/tests.yml)

[View the research page](https://wrtzkevin-collab.github.io/csmarket-research/)

CSMarket Research estimates the expected value of **opening** a CS2 case while
making every source, fee, missing price, and assumption visible. It is an
educational research project, not an investment recommendation or a promise of
profit.

## What this does and does not answer

It answers one descriptive question: given a published outcome distribution and
a dated market snapshot, what is the expected monetary value and downside of
opening a case? The answer is reliably and unsurprisingly negative, because
that is how the game is designed.

It does **not** answer whether an unopened case is worth holding. Case supply is
capped over time and unopened cases trade on their own market, which is a
different question needing timestamped history, a baseline, transaction costs,
and out-of-sample testing. None of that exists here yet; see the roadmap.

## What the model reports

For total opening cost `C` and priced outcomes `i`:

```text
gross EV              = sum(probability_i * listed_value_i)
gross return ratio    = gross EV / C
net EV                = sum(probability_i * value_after_sell_fee_i)
expected net ROI      = (net EV - C) / C
loss probability      = sum(probability_i where net_value_i < C)
probability coverage  = sum(probability_i with a usable price)
```

Missing outcomes reduce coverage and are never silently treated as zero or
redistributed across the other outcomes. An estimate with incomplete coverage is
a lower-bound partial estimate, not a complete case value.

## Where the numbers come from

| Input | Source | Standing |
|---|---|---|
| Rarity and StatTrak probabilities | [Official CS:GO China probability disclosure](https://www.csgo.com.cn/news/gamebroad/20170911/206155.html) | Official, but published in 2017 for the Chinese release. Treating it as current for CS2 is this project's single largest assumption. |
| Case contents and exact market names | [ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API), commit-pinned | Community maintained, MIT. Ordinary skins are bot-parsed from the game manifest; **rare-special pools are curated by hand** and need per-case checking. |
| Prices, Steam | [Steam Community Market](https://steamcommunity.com/market/) `priceoverview` | Lowest current ask. Lists every tradable variant, so coverage is complete, but Steam balance cannot be withdrawn as cash and an ask is not a sale. |
| Prices, cash | [Skinport public API](https://docs.skinport.com/) | Median completed sale. Withdrawable as real money, but the illiquid tail has no recent sale. |
| Key price | A configured constant | **Not observed.** It dominates opening cost, so verify it before relying on a result. |
| Wear-grade weights | Observed sales volume per grade, uniform float density as fallback | See below. |

The two price venues answer different questions, so `analyze-case` values a case
against each separately and reports them side by side rather than blending them.

### Wear grades

Valve documents that a random float is drawn inside a finish's range but has
never published the distribution. Earlier versions compared two theoretical
densities; on a real case they differed by under two percentage points of
expected ROI, which did not justify the assumptions.

Weights are now measured from the market: each wear grade is its own listing
with its own sales volume, so the observed split across an item's grades is used
directly. Where the market is too thin to measure — typically the knives, which
also matter most — the uniform density is used and the result records how much
probability mass rests on each basis.

Volume measures turnover, not drop frequency: grades that holders keep rather
than sell are under-represented. It is a proxy with a timestamp and a source,
which an assumed density is not.

## Install

Requires Python 3.11 or newer.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/python -m unittest discover -s tests -v
```

```bash
.venv/bin/python -m csmarket calculate examples/synthetic_case.json
```

```bash
.venv/bin/python -m csmarket price "Kilowatt Case" --source steam
```

```bash
.venv/bin/python -m csmarket analyze-case "Kilowatt Case" --progress --export-web
```

`calculate` runs offline against an explicit, deliberately synthetic outcome set
and demonstrates the calculation contract. `price` is a single live source
check. `analyze-case` runs the full pipeline: pinned catalogue, live prices from
each venue, observed wear weights, and a coverage-annotated valuation.

Steam is crawled one name at a time and answers `429` above roughly twenty
requests per minute, so a case takes about fifteen minutes on a cold cache.
Observations are cached in `data/raw/price-cache.json` and reused for 24 hours;
`--refresh` forces a re-fetch and `--no-cache` disables it.

## The published page

`web/` is a dependency-free static page deployed to GitHub Pages on push. It
renders `web/results.json` and nothing else: there are no illustrative numbers
built into it, and with no data file it says so rather than showing invented
figures. Regenerate and publish with:

```bash
.venv/bin/python -m csmarket analyze-case "Kilowatt Case" --export-web && python3 -m http.server 8000 -d web
```

## Current scope

Version 0.3 provides an end-to-end live valuation for supported standard weapon
cases across two venues, with observed wear weighting and a page fed only by
calculated output. Rare-special mappings still come from a hand-curated
catalogue, the key price is still a configured constant, and the 2017
probability disclosure has not been independently re-verified against the
current build. The project does not forecast future case prices, validate a
trading strategy, or backtest any earlier result.

## Authorship

The research question and product direction are user led. Development uses AI
assistance for code generation, review, testing, and documentation. The learning
notes are retained so the evolution of the assumptions can be audited.
