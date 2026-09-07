# Roadmap

## v0.1 — calculation contract

- Correct EV, gross return ratio, net ROI, loss probability, and coverage.
- Skinport documented API adapter with retries and timestamps.
- Fixed-input unit tests and a static research-result page.
- Public methodology, limitations, and AI contribution statement.

## v0.2 — live case pipeline

- [x] Add a version-pinned community case catalogue and label its provenance.
- [x] Join exact market names from the catalogue and filter Souvenir variants.
- [x] Split StatTrak per eligible item and compare empirical/uniform wear scenarios.
- [x] Refuse mixed source, currency, price type, or observation time.
- [x] Report overall and per-rarity missing-price coverage.
- [ ] Manually audit every ordinary and rare-special outcome for the first 3–5 cases.
- [ ] Save timestamped snapshots locally and publish only data allowed by provider terms.

## v0.3 — empirical study

- Collect genuine time-series observations; do not reuse the legacy synthetic series.
- Pre-register a simple hypothesis relating value-to-price measures to future case returns.
- Compare against simple baselines in chronological train/test splits.
- Include fees, missingness, sensitivity analysis, uncertainty, drawdown, and failure cases.

## Publication gate

Before the first GitHub release:

- revoke the legacy CSFloat key that was embedded in local source (the files now read an environment variable, but code removal does not revoke the credential);
- run secret scanning and all tests;
- verify provider attribution and data redistribution terms;
- replace illustrative demo values with an audited snapshot or label them prominently as synthetic;
- record which parts the user designed, verified, and can explain, and which parts used AI assistance.
