# Contributing

## Propose a change

Open a GitHub issue for a bug or enhancement, then work on a branch or fork and submit a focused pull request referencing that issue. Include the reason for the change, the expected behavior and test results. Bug reports and contributions may be written in English.

## Development and tests

Python code lives in `scripts/`; automated tests live in `tests/`; reusable workflows live in `.github/workflows/`. The test suite uses the Python standard library and mocks outbound HTTP calls. Run it from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Add automated tests for new functionality and a regression test for every bug fix. Keep tests offline and use synthetic diffs, API responses and credentials. Never add real API keys, private repository content or personal data. Follow the style of the surrounding code and keep dependencies minimal.

Update README.md when behavior, workflow inputs, permissions or limits change. Reviews must remain advisory COMMENT reviews, not approval decisions. Preserve event authorization, diff caps and bounded API access. CI and independent review must pass before merge. Do not merge your own unreviewed change.

## Security reports

Use the private reporting link in [SECURITY.md](SECURITY.md), not public issues, for vulnerabilities. Never paste a real secret into an issue or pull request.
