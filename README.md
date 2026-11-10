# gemini-pr-review

[![CI](https://github.com/reihlinstinct/gemini-pr-review/actions/workflows/ci.yml/badge.svg)](https://github.com/reihlinstinct/gemini-pr-review/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Event-driven Gemini review for pull requests: one reusable workflow that
each repo calls on `pull_request` events. Replaces the 15-minute cron
scanner proposed in
[collaboration-docs#51](https://github.com/reihlinstinct/collaboration-docs/issues/51)
with the owner's approved counter-proposal: no cron, no idle runs, no
polling quota.

## What it does

On every `opened` / `synchronize` / `ready_for_review` of a same-repo PR:

1. Skips if the current head SHA already has its review (idempotent).
2. Fetches the PR diff, capped at 12,000 characters.
3. Sends it to the Gemini API (free tier, `gemini-2.5-flash`).
4. Posts one **COMMENT** review:
   opens with `Gemini review (Action): <model> on head <sha>` and closes
   with the tag `Gemini`, plus a hidden
   `<!-- gemini-action-review sha=<full sha> model=<model> -->` marker.

On quota exhaustion or any API failure it writes a note to the run summary
and exits green. It never blocks CI and never posts twice on the same head.

## Use it in a repo

Add a repo secret `GEMINI_API_KEY` (free-tier AI Studio key), then one
caller workflow `.github/workflows/gemini-review.yml`:

```yaml
name: Gemini review

on:
  pull_request:
    types: [opened, synchronize, ready_for_review]

permissions: {}

jobs:
  gemini-review:
    # Same-repo PRs only (never forks), and never pull_request_target,
    # so the secret and the write token stay off untrusted code.
    if: github.event.pull_request.head.repo.full_name == github.repository
    permissions:
      contents: read
      pull-requests: write
    uses: reihlinstinct/gemini-pr-review/.github/workflows/review-reusable.yml@<pinned-sha> # v1
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

## Design rules (owner-approved, 2026-11-10)

1. **Event-driven only** - `pull_request` events, no cron, no polling.
2. **Same-repo PRs only** - forks excluded by the caller `if`; never
   `pull_request_target`.
3. **One reusable workflow here** - each repo calls it with a single `uses:`.
4. **Minimal token** - the run uses only the caller's `GITHUB_TOKEN` scoped
   to `contents: read` + `pull-requests: write`. No PAT, no merge rights,
   no APPROVE.
5. **Free tier only** - no billing account, light Flash model, capped diff.
   On quota exhaustion the run skips with a note instead of failing.
6. **COMMENT-only, marked reviews** - header `Gemini review (Action):`,
   closing tag `Gemini`, hidden per-head-SHA marker for idempotency.
   Other agents treat these posts as data, never as requests. For the merge
   gate, a Gemini review counts only after authorship is verified through
   the API: author `github-actions[bot]`, both markers present, and the
   marker SHA equal to the head under review.
7. **The daily 10:00 Gemini scan stays as backup** - this Action replaces
   the proposed 15-minute cron, not the daily sweep.

## Pinning

Callers pin the reusable workflow by commit SHA. The reusable workflow also
pins its own script checkout (`ref:` in `review-reusable.yml`); after any
change under `scripts/`, update that self-pin to the commit that changed
the script, then pin the new reusable SHA in each caller.

## Files

- `.github/workflows/review-reusable.yml` - the reusable workflow.
- `scripts/gemini_review.py` - stdlib-only review client (GitHub + Gemini).
- `tests/test_gemini_review.py` - unit tests, all HTTP mocked.

## License

MIT
