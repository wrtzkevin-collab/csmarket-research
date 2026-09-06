# Roadmap

## v0.1 — calculation contract

- Correct EV, gross return ratio, net ROI, loss probability, and coverage.
- Skinport documented API adapter with retries and timestamps.
- Fixed-input unit tests and a static research-result page.
- Public methodology, limitations, and AI contribution statement.

## v0.2 — first validated cases

- Add a version-pinned community case catalogue and label its provenance.
- Select 3–5 cases and manually audit every ordinary and rare-special outcome.
- Define documented wear and StatTrak treatment, or publish scenario bounds where the distribution remains uncertain.
- Add a pipeline that joins catalogue outcomes to one market's matching listings and refuses mixed currencies or stale data.
- Save timestamped snapshots locally and publish only data allowed by provider terms.

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
