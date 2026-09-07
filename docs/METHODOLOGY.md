# Methodology

## Research question

The question answered here is descriptive: given an explicitly defined outcome
distribution and one market's prices, what is the expected monetary value and
downside distribution of **opening** a case?

A separate, unanswered question is predictive: does an unopened case appreciate,
and does any measure computed here explain that? Cases stop being obtainable
over time and trade on their own market, so the two questions have different
answers. This project does not generate BUY or SELL labels and does not claim
the predictive result.

## Probability model

For standard key-opened weapon cases, the official China disclosure lists these
unconditional rarity probabilities:

| Rarity | Probability |
|---|---:|
| Mil-Spec | 79.923% |
| Restricted | 15.985% |
| Classified | 3.197% |
| Covert | 0.639% |
| Rare Special Item | 0.256% |

The same disclosure states that items of equal rarity have equal probability and
that, when an item can be StatTrak, its conditional StatTrak probability is 10%.
[T1-OFFICIAL: Perfect World / CS:GO probability disclosure](https://www.csgo.com.cn/news/gamebroad/20170911/206155.html)

**Standing assumption.** The disclosure was published on 2017-09-11 for the
Chinese release of CS:GO. This project applies it to the current global CS2
build without independent re-verification. It is the largest single assumption
in the model: if these rates have changed, every downstream number changes with
them. Re-verifying it is the highest-value open task.

### Wear grades

Valve documents that a random wear value is chosen within a finish's range but
does not publish the probability density used by case openings.
[T1-OFFICIAL: Valve workshop finishes](https://www.counter-strike.net/workshop/workshopfinishes)

Version 0.2 responded by comparing two theoretical densities — a uniform
baseline and the piecewise-uniform distribution reported by CSFloat's
observational study. Measured on a full case the two produced expected net ROI
figures within 1.4 percentage points of each other, far inside the uncertainty
contributed by prices and by the catalogue's rare-special pools. The comparison
cost a substantial amount of unfalsifiable modelling for a difference that did
not change any conclusion, so it was removed.

Version 0.3 measures the split instead of assuming it. Each wear grade of a skin
is a distinct market listing carrying its own counts, so the split across an
item's grades is a directly observed quantity with a timestamp and a provider.
Grades outside a skin's float range are excluded first, so an observation on an
unreachable listing cannot leak probability into it.

The preferred count is **resting listings**: how many of that grade are
currently offered. It is preferred over 24-hour sales for a specific reason —
sales exist only for items that traded today, which excludes almost the entire
rare tail, and the rare tail is where the money is. Sales volume is used when
listings are unavailable, and a uniform density when neither is measurable.

Three limitations are recorded rather than argued away:

- **Neither count is drop frequency.** Listings measure accumulated supply and
  sales measure turnover. Holders keep some grades and dump others, so both are
  biased relative to how often a grade actually drops. They are proxies, chosen
  because they are observations rather than assumptions.
- **Thin markets cannot be measured.** Below a configurable total (20 by
  default) the split is noise and the uniform density is used instead.
- **Every valuation reports the split.** A result that leans on the fallback
  cannot be mistaken for a fully observed one.

## Value definitions

Let `C` be case price plus key price and any opening charge. For outcome `i`,
let `p_i` be its probability, `v_i` its gross value, and `f_i` its selling fee
rate.

```text
gross_ev = Σ p_i v_i
gross_return_ratio = gross_ev / C
net_ev = Σ p_i v_i (1 - f_i)
expected_net_roi = (net_ev - C) / C
loss_probability = Σ p_i · 1[v_i (1 - f_i) < C]
```

The gross return ratio is sometimes called RTP. It is not profit. A gross return
ratio of 56.2% corresponds to a gross expected ROI of -43.8% before selling
fees.

## Missing data

An outcome without a price contributes to missing probability coverage. Known
outcomes are not reweighted to sum to one. This prevents a missing expensive
rare item, or a missing cheap common item, from silently changing the estimate.

Until coverage reaches 100%, calculated EV is labelled a partial observed EV.
The interface displays coverage beside the estimate.

## Market consistency

One calculation uses one venue and one currency for both costs and outcomes.
Source, currency and price type must be identical across a snapshot; mixing a
listing price with a completed-sale price, or two venues, produces a number that
means nothing.

Observation *times* may differ inside a snapshot, because a throttled crawl of a
few hundred names genuinely takes minutes. The spread is bounded, recorded as
`observation_span_seconds`, and rejected past a limit so a resumed crawl cannot
be presented as one instant.

Steam wallet prices are not treated as cash because Steam states that wallet
funds have no cash value and cannot be exchanged for cash.
[T1-OFFICIAL: Steam Subscriber Agreement §3.C](https://store.steampowered.com/subscriber_agreement/)
A Steam valuation and a cash-market valuation are therefore reported as separate
results, never blended.

### Why two venues

They fail in opposite directions, and reporting both makes each one's failure
visible:

| | Steam Community Market | Skinport |
|---|---|---|
| Price meaning | lowest current ask | median completed sale |
| Coverage of the rare-special tail | complete | frequently missing |
| Proceeds | Steam balance only, not withdrawable | withdrawable cash |
| Bias | ask overstates realisable value | survivorship toward liquid items |

A result shown on one venue alone is either complete or cashable, never both.

## Reproducibility

Each saved snapshot includes source and endpoint; currency and price type; UTC
observation time and crawl span; the provider's own update time when available;
missing values and coverage; model version and assumptions; and the pinned
catalogue commit.

Live observations are cached on disk under `data/raw/` with their original
observation times, so a stale snapshot stays visibly stale rather than appearing
fresh. Tests use fixed synthetic inputs so results can be checked by hand and do
not depend on live API availability.

## Catalogue provenance

The case-to-item and exact market-name mapping comes from a commit-pinned
revision of ByMykel/CSGO-API. Its `crates.json`, `skins.json`, and
`skins_not_grouped.json` are joined by stable item IDs. Exact `market_hash_name`
values are used directly, and Souvenir variants are filtered because they are
not ordinary case-opening outcomes.

The catalogue is MIT licensed and community maintained. Ordinary skin data is
generated automatically from the game's own manifest, which makes it
considerably stronger than a hand-typed list. The rare-special pools are the
exception: they are maintained manually against third-party references, so the
project labels the catalogue as community data, never as Valve's API, and treats
per-case auditing of the rare-special pool as a prerequisite for publication.
[PROJECT SOURCE: ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) /
[PROJECT LICENSE: MIT](https://github.com/ByMykel/CSGO-API/blob/main/LICENSE) /
[MAINTAINER PROVENANCE STATEMENT](https://github.com/ByMykel/CSGO-API/discussions/166)
