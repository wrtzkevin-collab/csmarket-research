# Methodology

## Research question

The first question is descriptive: given an explicitly defined outcome distribution and one market's prices, what is the expected monetary value and downside distribution of opening a case?

A separate later question is predictive: does the relationship between a case's opening value and market price explain its future market return? Version 0.1 does not answer the predictive question and does not generate BUY or SELL labels.

## Probability model

For standard key-opened weapon cases, the official China disclosure lists these unconditional rarity probabilities:

| Rarity | Probability |
|---|---:|
| Mil-Spec | 79.923% |
| Restricted | 15.985% |
| Classified | 3.197% |
| Covert | 0.639% |
| Rare Special Item | 0.256% |

The same disclosure states that items of equal rarity have equal probability and that, when an item can be StatTrak, its conditional StatTrak probability is 10%. [T1-OFFICIAL: Perfect World / CS:GO probability disclosure](https://www.csgo.com.cn/news/gamebroad/20170911/206155.html)

These rules do not by themselves provide a complete probability for every market listing. Wear, float, finish phase, and other attributes still require a documented model. Version 0.1 therefore accepts explicit outcome probabilities and reports how much probability mass has a usable price. It does not invent a global multiplier for unresolved attributes.

### Wear sensitivity models

Valve's workshop documentation says a random wear value is chosen within a finish's range, but it does not publish the probability density used by case openings. Uniform wear is therefore an explicit assumption, not an official drop rule. [T1-OFFICIAL: Valve workshop finishes](https://www.counter-strike.net/workshop/workshopfinishes)

The live case command reports two scenarios on the same price snapshot:

- `uniform_allowed_range_v1` assumes the final float is uniform across the skin's allowed range. This is a simple stress case and is marked as an assumption.
- `csfloat_empirical_2020_v1` implements the 3%/24%/33%/24%/16% latent wear buckets reported in CSFloat's observational study, with linear mapping into each skin's float range. It is empirical community evidence, not a Valve guarantee. [T3-COMMUNITY: CSFloat wear study](https://blog.csfloat.com/analysis-of-float-value-and-paint-seed-distribution-in-cs-go/)

Differences between these scenarios measure model sensitivity. They are not confidence intervals.

## Value definitions

Let `C` be case price plus key price and any opening charge. For outcome `i`, let `p_i` be its probability, `v_i` its gross value, and `f_i` its selling fee rate.

```text
gross_ev = Σ p_i v_i
gross_return_ratio = gross_ev / C
net_ev = Σ p_i v_i (1 - f_i)
expected_net_roi = (net_ev - C) / C
loss_probability = Σ p_i · 1[v_i (1 - f_i) < C]
```

The gross return ratio is sometimes called RTP. It is not profit. A gross return ratio of 56.2% corresponds to a gross expected ROI of -43.8% before selling fees.

## Missing data

An outcome without a price contributes to missing probability coverage. Known outcomes are not reweighted to sum to one. This prevents a missing expensive rare item, or a missing cheap common item, from silently changing the estimate.

Until coverage reaches 100%, calculated EV is labelled a partial observed EV. The interface displays coverage beside the estimate.

## Market consistency

One calculation uses one market and one currency for both costs and outcomes. Steam wallet prices are not treated as cash because Steam states that wallet funds have no cash value and cannot be exchanged for cash. [T1-OFFICIAL: Steam Subscriber Agreement §3.C](https://store.steampowered.com/subscriber_agreement/)

Listing prices and completed-sale prices are also different measures. Every observation records its source and price type. Cross-market comparisons appear as separate estimates rather than a blended price.

## Reproducibility

Each saved snapshot should include:

- source and endpoint;
- currency and price type;
- UTC observation time;
- the provider's own update time when available;
- missing values and coverage;
- model version and assumptions;
- a hash or immutable copy of the raw input, subject to the provider's data licence.

Tests use fixed synthetic inputs so results can be checked by hand and do not depend on live API availability.

## Catalogue provenance

The case-to-item and exact market-name mapping comes from a commit-pinned revision of ByMykel/CSGO-API. Its `crates.json`, `skins.json`, and `skins_not_grouped.json` are joined by stable item IDs. Exact `market_hash_name` values are used directly, and Souvenir variants are filtered because they are not ordinary case-opening outcomes.

This catalogue is MIT licensed and community maintained. Its rare-special pools are manually maintained with third-party references, so the project labels them as community data and does not describe them as Valve's API. [PROJECT SOURCE: ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) / [PROJECT LICENSE: MIT](https://github.com/ByMykel/CSGO-API/blob/main/LICENSE) / [MAINTAINER PROVENANCE STATEMENT](https://github.com/ByMykel/CSGO-API/discussions/166)
