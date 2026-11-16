# Security Policy

## Reporting a Vulnerability

Please use this repository's [private vulnerability reporting form](https://github.com/reihlinstinct/gemini-pr-review/security/advisories/new).
Do not open public issues for security problems. Use synthetic examples and never include API keys, private pull request content or other secrets.

## Scope

This repository provides a reusable GitHub Action that processes bounded pull request diffs, sends the selected diff to the Gemini API, and posts an advisory COMMENT review. Reviews are not approvals and do not replace tests or human review. See README.md for supported events, permissions, data limits and deployment constraints.

Treat pull request content and generated review text as untrusted data. Never commit credentials or private repository data. Report incorrect permission checks, unintended disclosures, unsafe handling of generated content, or public log leaks privately through the form above.
