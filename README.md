# CSMarket Research v3

CSMarket Research estimates the expected value of opening a CS2 case while making every source, fee, missing price, and assumption visible. It is an educational research project, not an investment recommendation or a promise of profit.

This version replaces the legacy ranking prototype's fixed rare-item price, global StatTrak multiplier, synthetic history, and misleading use of “ROI.” The old prototype remains outside this directory as a record of how the project developed.

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

Missing outcomes reduce coverage and are never silently treated as zero or redistributed across the other outcomes. An estimate with incomplete coverage is a lower-bound partial estimate, not a complete case value.

## Data policy

- Opening probabilities come from the [official CS:GO China probability disclosure](https://www.csgo.com.cn/news/gamebroad/20170911/206155.html). It states the rarity probabilities, equal probability within a rarity, and the conditional 10% StatTrak probability when StatTrak is available.
- Market observations use documented provider adapters. The first adapter supports [Skinport's public API](https://docs.skinport.com/).
- The item-to-case catalogue still requires a versioned community dataset and per-case validation. Community data must be labelled as community maintained, never as a Valve API.
- Steam wallet values and cash-market values are different units and are not combined in one estimate.
- Runtime snapshots retain provider, currency, price type, observation time, and original aggregate statistics.

## Run locally

```powershell
cd public_v3
python -m pip install -e .
python -m unittest discover -s tests -v
python -m csmarket calculate examples/synthetic_case.json
python -m csmarket skinport-price "Kilowatt Case"
```

The static demonstration can be served without a framework:

```powershell
python -m http.server 8000 -d web
```

Then open `http://localhost:8000`.

The calculation example is deliberately synthetic. The Skinport command performs a live source check and labels the observation as a completed-sale aggregate or current listing. It does not produce a case EV until a complete, audited outcome catalogue is supplied.

## Current scope

Version 0.1 establishes the calculation contract, the first documented price-source adapter, tests, and an honest result view. It does not yet claim to forecast future case prices, validate a trading strategy, or backtest the legacy 16.6% live result. Those claims require timestamped historical observations, a baseline, transaction costs, and chronological out-of-sample evaluation.

## Authorship

The research question and product direction are user led. Version 3 is being developed with AI assistance for code generation, review, testing, and documentation. The legacy prototype and the learning notes are retained so the evolution of the assumptions can be audited.
