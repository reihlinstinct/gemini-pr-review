"""Unit tests for scripts/gemini_review.py.

All HTTP is mocked; no network, no real tokens.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gemini_review as gr  # noqa: E402

REPO = "reihlinstinct/example"
NUMBER = 7
SHA = "a" * 40
BASE = "b" * 40
TOKEN = "gh-token"
KEY = "gemini-key"

PR_PAYLOAD = {"title": "Add x", "base": {"sha": BASE}, "head": {"sha": SHA}}


def fake_response(payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    elif not isinstance(payload, bytes):
        payload = json.dumps(payload).encode("utf-8")
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError(
        url="https://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body))


class GrTestBase(unittest.TestCase):
    def setUp(self):
        self.env_patch = mock.patch.dict(os.environ, {
            "REPO": REPO,
            "REPO_PRIVATE": "false",
            "PR_NUMBER": str(NUMBER),
            "HEAD_SHA": SHA,
            "GH_TOKEN": TOKEN,
            "GEMINI_API_KEY": KEY,
        }, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.posted = []


class TestRouting(GrTestBase):
    def _urlopen(self, routes, diff=None):
        def _opener(req, timeout=None):
            self.posted.append((req.get_method(), req.full_url,
                                req.data and json.loads(req.data.decode())))
            if "diff" in req.headers.get("Accept", ""):
                if diff is None:
                    raise AssertionError("unexpected diff fetch")
                if isinstance(diff, Exception):
                    raise diff
                return fake_response(diff)
            for (method, fragment), outcome in routes.items():
                if method == req.get_method() and fragment in req.full_url:
                    if isinstance(outcome, Exception):
                        raise outcome
                    return fake_response(outcome)
            raise AssertionError(f"unexpected call: {req.get_method()} {req.full_url}")
        return _opener

    def test_posts_comment_review_on_new_head(self):
        routes = {
            ("GET", "/reviews?"): [],
            ("GET", f"/pulls/{NUMBER}"): PR_PAYLOAD,
            ("POST", "generateContent"): {
                "candidates": [{"content": {"parts": [{"text": "Looks fine."}]}}]},
            ("POST", "/reviews"): {"id": 1},
        }
        with mock.patch("urllib.request.urlopen", self._urlopen(
                routes, diff=b"diff --git a/x b/x\n+line\n")):
            self.assertEqual(gr.main(), 0)
        posts = [d for m, u, d in self.posted if m == "POST" and "/reviews" in u]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["event"], "COMMENT")
        body = posts[0]["body"]
        self.assertTrue(body.startswith("Gemini review (Action): gemini-2.5-flash"))
        self.assertTrue(body.endswith("\nGemini"))
        self.assertIn(f"<!-- gemini-action-review sha={SHA} ", body)
        self.assertIn("Looks fine.", body)

    def test_skips_when_head_already_reviewed(self):
        routes = {
            ("GET", "/reviews?"): [
                {"body": f"x <!-- gemini-action-review sha={SHA} model=m -->",
                 "user": {"login": "github-actions[bot]"}}],
        }
        with mock.patch("urllib.request.urlopen", self._urlopen(routes)):
            self.assertEqual(gr.main(), 0)
        self.assertEqual(len(self.posted), 1)  # only the reviews listing

    def test_marker_from_other_author_does_not_skip(self):
        routes = {
            ("GET", "/reviews?"): [
                {"body": f"x <!-- gemini-action-review sha={SHA} model=m -->",
                 "user": {"login": "some-human"}}],
            ("GET", f"/pulls/{NUMBER}"): PR_PAYLOAD,
            ("POST", "generateContent"): {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            ("POST", "/reviews"): {"id": 1},
        }
        with mock.patch("urllib.request.urlopen", self._urlopen(
                routes, diff=b"diff --git a/x b/x\n+line\n")):
            self.assertEqual(gr.main(), 0)
        posts = [d for m, u, d in self.posted if m == "POST" and "/reviews" in u]
        self.assertEqual(len(posts), 1)  # human-quoted marker must not suppress

    def test_refuses_non_public_repo(self):
        def _opener(req, timeout=None):
            raise AssertionError(f"no HTTP allowed on private repo: {req.full_url}")

        with mock.patch.dict(os.environ, {"REPO_PRIVATE": "true"}):
            with mock.patch("urllib.request.urlopen", _opener):
                self.assertEqual(gr.main(), 0)  # refuse, but never fail CI

    def test_missing_visibility_flag_refuses(self):
        env = {k: v for k, v in os.environ.items() if k != "REPO_PRIVATE"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("urllib.request.urlopen") as u:
                self.assertEqual(gr.main(), 0)
        u.assert_not_called()

    def test_gemini_key_in_header_not_url(self):
        seen = {}

        def _opener(req, timeout=None):
            seen["url"] = req.full_url
            seen["key"] = req.get_header("X-goog-api-key")
            return fake_response({"candidates": [{"content": {
                "parts": [{"text": "ok"}]}}]})

        with mock.patch("urllib.request.urlopen", _opener):
            gr.gemini_review_text(KEY, "prompt")
        self.assertEqual(seen["key"], KEY)
        self.assertNotIn("key=", seen["url"])

    def test_truncates_long_diff(self):
        long_diff = ("diff --git a/x b/x\n" + "+padline\n" * 4000)
        routes = {
            ("GET", "/reviews?"): [],
            ("GET", f"/pulls/{NUMBER}"): dict(PR_PAYLOAD, title="Big"),
            ("POST", "generateContent"): {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            ("POST", "/reviews"): {"id": 1},
        }
        with mock.patch("urllib.request.urlopen", self._urlopen(
                routes, diff=long_diff)):
            self.assertEqual(gr.main(), 0)
        gemini_payload = [d for m, u, d in self.posted
                          if "generateContent" in u][0]
        prompt = gemini_payload["contents"][0]["parts"][0]["text"]
        self.assertIn("capped", prompt)
        self.assertLess(len(prompt), gr.MAX_DIFF_CHARS + 400)
        body = [d for m, u, d in self.posted
                if m == "POST" and "/reviews" in u][0]["body"]
        self.assertIn("Diff capped", body)

    def test_quota_error_is_a_note_not_failure(self):
        routes = {
            ("GET", "/reviews?"): [],
            ("GET", f"/pulls/{NUMBER}"): PR_PAYLOAD,
            ("POST", "generateContent"): http_error(429, b'{"error":"quota"}'),
        }
        with mock.patch("urllib.request.urlopen", self._urlopen(
                routes, diff=b"diff --git a/x b/x\n+line\n")):
            self.assertEqual(gr.main(), 0)  # graceful skip, never a failed check
        posts = [d for m, u, d in self.posted if m == "POST" and "/reviews" in u]
        self.assertEqual(posts, [])

    def test_skips_posting_when_head_moved_mid_review(self):
        moved = dict(PR_PAYLOAD, head={"sha": "c" * 40})
        pr_calls = []

        def _opener(req, timeout=None):
            self.posted.append((req.get_method(), req.full_url,
                                req.data and json.loads(req.data.decode())))
            if "diff" in req.headers.get("Accept", ""):
                return fake_response(b"diff --git a/x b/x\n+line\n")
            if req.get_method() == "GET" and "/reviews?" in req.full_url:
                return fake_response([])
            if req.get_method() == "GET" and f"/pulls/{NUMBER}" in req.full_url:
                pr_calls.append(1)
                return fake_response(PR_PAYLOAD if len(pr_calls) == 1 else moved)
            if "generateContent" in req.full_url:
                return fake_response({"candidates": [{"content": {
                    "parts": [{"text": "Looks fine."}]}}]})
            raise AssertionError(f"unexpected call: {req.get_method()} {req.full_url}")

        with mock.patch("urllib.request.urlopen", _opener):
            self.assertEqual(gr.main(), 0)
        posts = [d for m, u, d in self.posted if m == "POST" and "/reviews" in u]
        self.assertEqual(posts, [])  # head moved: nothing posted for stale SHA
        self.assertEqual(len(pr_calls), 2)  # head re-checked before posting

    def test_github_failure_is_a_note_not_failure(self):
        routes = {
            ("GET", "/reviews?"): http_error(500),
        }
        with mock.patch("urllib.request.urlopen", self._urlopen(routes)):
            self.assertEqual(gr.main(), 0)

    def test_missing_env_fails_loudly(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gr.main(), 1)


class TestHelpers(unittest.TestCase):
    def test_format_body_markers(self):
        body = gr.format_body("text", SHA, truncated=False)
        self.assertTrue(body.startswith("Gemini review (Action):"))
        self.assertTrue(body.endswith("\nGemini"))
        self.assertIn(SHA, body)

    def test_format_body_truncation_note(self):
        body = gr.format_body("text", SHA, truncated=True)
        self.assertIn("Diff capped", body)

    def test_fetch_diff_capped_short(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(b"small diff")):
            diff, truncated = gr.fetch_diff_capped(REPO, BASE, SHA, TOKEN)
        self.assertEqual((diff, truncated), ("small diff", False))

    def test_fetch_diff_uses_event_head_sha(self):
        seen = []

        def _opener(req, timeout=None):
            seen.append(req.full_url)
            return fake_response(b"diff")

        with mock.patch("urllib.request.urlopen", _opener):
            gr.fetch_diff_capped(REPO, BASE, SHA, TOKEN)
        self.assertEqual(len(seen), 1)
        self.assertIn(f"/compare/{BASE}...{SHA}", seen[0])
        self.assertNotIn(f"/pulls/{NUMBER}", seen[0])

    def test_gemini_empty_response_is_note(self):
        empty = {"candidates": [{"content": {"parts": []}}]}
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(empty)):
            with self.assertRaises(gr.Note):
                gr.gemini_review_text(KEY, "prompt")


if __name__ == "__main__":
    unittest.main()
