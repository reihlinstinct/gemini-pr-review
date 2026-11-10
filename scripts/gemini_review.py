#!/usr/bin/env python3
"""Event-driven Gemini PR review.

Posts one COMMENT review on the pull request that triggered the workflow.
Never approves, never requests changes, never merges. Idempotent per head
SHA: a run that finds its own marker for the current head skips posting.

Every external failure (GitHub API, Gemini API, quota exhausted) becomes a
note in the step summary instead of a failed check: this review is advisory
and must never block CI. Missing configuration (environment) does fail the
run, because that is a setup bug worth surfacing.

Environment:
    GH_TOKEN        GitHub token with pull-requests: write on this repo.
    GEMINI_API_KEY  Gemini API key (free tier).
    REPO            owner/name of the repository.
    PR_NUMBER       pull request number.
    HEAD_SHA        head SHA of the pull request.
    MODEL           Gemini model (default gemini-2.5-flash).
    MAX_DIFF_CHARS  diff cap in characters (default 12000).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

GITHUB_API = "https://api.github.com"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"

MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
MAX_DIFF_CHARS = int(os.environ.get("MAX_DIFF_CHARS", "12000"))
MARKER = "gemini-action-review"

SYSTEM_PROMPT = (
    "You are Gemini reviewing a GitHub pull request as a careful teammate. "
    "Review only the diff you are given. Report real findings on the changed "
    "lines: bugs, security issues, leaked secrets or personal data, broken "
    "tests. Be professional and short: findings first, one line each, naming "
    "the file and line where you can. If the diff looks fine, say so in one "
    "or two sentences and add at most one optional suggestion. Never request "
    "work outside the diff. Your review is advisory: it never approves and "
    "never blocks."
)

USER_PROMPT = (
    "Repository: {repo}\nPull request #{number}: {title}\n\n"
    "Diff (unified format{truncated}):\n\n{diff}\n\n"
    "Write the review now. Findings first, then one closing line."
)


class Note(Exception):
    """A failure that must end the run as a note, not a failed check."""


def _http(url, token=None, method="GET", payload=None,
          accept="application/vnd.github+json", timeout=60, log_url=None):
    """One HTTP call. Returns raw response bytes. Raises Note on any failure."""
    headers = {"Accept": accept, "User-Agent": "gemini-pr-review-action"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    safe_url = log_url or url
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise Note(f"HTTP {exc.code} from {safe_url}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Note(f"request to {safe_url} failed: {exc}") from exc


def _github_json(path, token, method="GET", payload=None):
    raw = _http(f"{GITHUB_API}{path}", token=token, method=method, payload=payload)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise Note(f"bad JSON from {path}: {exc}") from exc


def fetch_pr_title(repo, number, token):
    pr = _github_json(f"/repos/{repo}/pulls/{number}", token)
    return pr.get("title", "")


def fetch_diff_capped(repo, number, token, max_chars=MAX_DIFF_CHARS):
    raw = _http(f"{GITHUB_API}/repos/{repo}/pulls/{number}", token=token,
                accept="application/vnd.github.v3.diff")
    diff = raw.decode("utf-8", "replace")
    if len(diff) <= max_chars:
        return diff, False
    cut = diff[:max_chars]
    last_nl = cut.rfind("\n")
    if last_nl > 0:
        cut = cut[:last_nl + 1]
    return cut, True


def already_reviewed(repo, number, token, head_sha):
    reviews = _github_json(
        f"/repos/{repo}/pulls/{number}/reviews?per_page=100", token)
    tag = f"<!-- {MARKER} sha={head_sha} "
    return any(tag in (r.get("body") or "") for r in reviews)


def post_comment_review(repo, number, token, body):
    _github_json(f"/repos/{repo}/pulls/{number}/reviews", token,
                 method="POST", payload={"body": body, "event": "COMMENT"})


def gemini_review_text(api_key, prompt, model=MODEL):
    url = f"{GEMINI_API}/{model}:generateContent?key={api_key}"
    log_url = f"{GEMINI_API}/{model}:generateContent?key=<redacted>"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
    }
    raw = _http(url, method="POST", payload=payload,
                accept="application/json", log_url=log_url)
    try:
        data = json.loads(raw.decode("utf-8"))
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise Note(f"unexpected Gemini response shape: {exc}") from exc
    if not text:
        raise Note("Gemini returned an empty review")
    return text


def format_body(review_text, head_sha, truncated, model=MODEL,
                max_chars=MAX_DIFF_CHARS):
    parts = [
        f"Gemini review (Action): {model} on head {head_sha[:8]}",
        "",
        review_text,
    ]
    if truncated:
        parts += [
            "",
            f"_Diff capped at {max_chars} characters; "
            "this review covers the first part only._",
        ]
    parts += [
        "",
        "---",
        f"<!-- {MARKER} sha={head_sha} model={model} -->",
        "Gemini",
    ]
    return "\n".join(parts)


def note(message):
    print(f"::notice::{message}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"Gemini review: {message}\n")


def run(repo, number, head_sha, token, api_key):
    if already_reviewed(repo, number, token, head_sha):
        note(f"head {head_sha[:8]} already reviewed; skipping")
        return 0
    title = fetch_pr_title(repo, number, token)
    diff, truncated = fetch_diff_capped(repo, number, token)
    if not diff.strip():
        note("empty diff; skipping")
        return 0
    prompt = USER_PROMPT.format(
        repo=repo, number=number, title=title,
        truncated=", capped" if truncated else "", diff=diff)
    text = gemini_review_text(api_key, prompt)
    body = format_body(text, head_sha, truncated)
    post_comment_review(repo, number, token, body)
    note(f"posted COMMENT review on PR #{number} at head {head_sha[:8]}")
    return 0


def main():
    try:
        repo = os.environ["REPO"]
        number = int(os.environ["PR_NUMBER"])
        head_sha = os.environ["HEAD_SHA"]
        token = os.environ["GH_TOKEN"]
        api_key = os.environ["GEMINI_API_KEY"]
    except KeyError as exc:
        print(f"::error::missing required environment variable {exc}")
        return 1
    try:
        return run(repo, number, head_sha, token, api_key)
    except Note as exc:
        note(str(exc))
        return 0


if __name__ == "__main__":
    sys.exit(main())
