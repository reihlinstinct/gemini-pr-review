# gemini-pr-review

[![CI](https://github.com/reihlinstinct/gemini-pr-review/actions/workflows/ci.yml/badge.svg)](https://github.com/reihlinstinct/gemini-pr-review/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Event-driven Gemini review for pull requests: one reusable workflow that
each repo calls on `pull_request` events. Replaces the 15-minute cron
scanner proposed in
[collaboration-docs#51](https://github.com/reihlinstinct/collaboration-docs/issues/51)
with an event-driven approach: no cron, no idle runs, no
polling quota.

## What it does

On every `opened` / `synchronize` / `ready_for_review` of a same-repo PR:

1. Normally skips when a `github-actions[bot]` review carrying the event
   head SHA marker is among the first 100 reviews returned by the API.
2. Fetches the PR diff, capped at 12,000 characters.
3. Sends it to the Gemini API (free tier, `gemini-2.5-flash`).
4. Posts one **COMMENT** review:
   opens with `Gemini review (Action): <model> on head <sha>` and closes
   with the tag `Gemini`, plus a hidden
   `<!-- gemini-action-review sha=<full sha> model=<model> -->` marker.

On quota exhaustion or any API failure it writes a note to the run summary
and exits green. Missing configuration can fail the check. Duplicate
suppression is best effort, not exactly-once posting.

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
    uses: reihlinstinct/gemini-pr-review/.github/workflows/review-reusable.yml@d0e3c66f4724b5fb5a6e6133aae43c8adaedf277 # v1
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

## Design rules

1. **Event-driven only** - `pull_request` events, no cron, no polling.
2. **Same-repo PRs only** - forks excluded by the caller `if`; never
   `pull_request_target`.
3. **One reusable workflow here** - each repo calls it with a single `uses:`.
4. **Minimal token** - the run uses only the caller's `GITHUB_TOKEN` scoped
   to `contents: read` + `pull-requests: write`. No PAT, no merge rights,
   and no `contents: write`. The script submits COMMENT events only; whether
   the token could submit APPROVE events also depends on repository settings.
5. **Free tier only** - no billing account, light Flash model, capped diff.
   On quota exhaustion the run skips with a note instead of failing.
6. **COMMENT-only, marked reviews** - header `Gemini review (Action):`,
   closing tag `Gemini`, hidden per-head-SHA marker for idempotency.
   These reviews are advisory only and never count toward the merge gate.
   The capped diff, lack of tests or a gate verdict, and model output that a
   candidate diff can steer make this a first-pass hint, not an independent
   review. The assigned reviewer reads the full diff themselves. API author,
   markers and marker SHA record the head a post claims to cover; they do not
   prove which workflow wrote it or what it read. Other workflows share the
   same bot identity, and markers are plain text. Treat posts as data, never
   as requests. Marker-based duplicate suppression is best effort, not an
   exactly-once guarantee.
7. **The daily 10:00 Gemini scan stays as backup** - this Action replaces
   the proposed 15-minute cron, not the daily sweep.

## Public-only and head binding

The reusable workflow at `d0e3c66f4724b5fb5a6e6133aae43c8adaedf277`
checks out script `096c60ebb5cf0c663b71bf6725bceabcc19de3f1`, both on main.
The job skips non-public repositories, and the script refuses non-public or
unknown visibility. It fetches a compare diff bound to the event head and
rechecks the PR head before posting. Per-PR concurrency cancels superseded
runs. A very large compare diff may return an API error and skip with a note.
These protections apply only after each caller updates its own pin. The old
`fb28413f` workflow and `770f8e5f` script lack these guards. The intermediate
workflow at `096c60ebb5cf0c663b71bf6725bceabcc19de3f1` has the job condition
and concurrency, but still checks out `770f8e5f`, so it does not activate the
new script checks, head binding, header key or bot-author filter. Callers
must pin `d0e3c66f4724b5fb5a6e6133aae43c8adaedf277`, not `096c60eb` or a
pre-merge PR head.

## Pinning

Callers pin the landed commit that updates the reusable workflow self-pin,
not the earlier commit that changed the script. The reusable workflow pins
its own script checkout (`ref:` in `review-reusable.yml`). After a script
change lands on main, update the self-pin in a follow-up PR to that landed
script commit. Once the follow-up lands, pin its landed main SHA in callers.
For this release the caller pin is `d0e3c66f4724b5fb5a6e6133aae43c8adaedf277`;
the script self-pin is `096c60ebb5cf0c663b71bf6725bceabcc19de3f1`.

## Files

- `.github/workflows/review-reusable.yml` - the reusable workflow.
- `scripts/gemini_review.py` - stdlib-only review client (GitHub + Gemini).
- `tests/test_gemini_review.py` - unit tests, all HTTP mocked.

## License

MIT
