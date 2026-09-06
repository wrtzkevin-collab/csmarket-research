# Contributing

Changes should preserve the project's central rule: every reported number must have a defined meaning, source, observation time, and coverage.

Before opening a pull request:

1. Run `python -m unittest discover -s tests -v`.
2. Add a fixed-input test for changes to probability, fee, or missing-data behaviour.
3. Label listing, completed-sale, Steam-wallet, and cash-market values distinctly.
4. Do not commit API keys or raw provider snapshots without checking redistribution rights.
5. Document new modelling assumptions in `docs/METHODOLOGY.md`.

