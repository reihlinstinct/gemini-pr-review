"""Regression checks for public reporting and contribution instructions."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectDocumentationTests(unittest.TestCase):
    def test_security_reporting_targets_this_repository(self):
        text = (ROOT / 'SECURITY.md').read_text(encoding='utf-8')
        urls = re.findall(r'https://github\.com/[^\s)]+/security/advisories/new', text)
        self.assertEqual(urls, ['https://github.com/reihlinstinct/gemini-pr-review/security/advisories/new'])
        self.assertNotIn('dependency manifests only', text)

    def test_contribution_instructions_cover_process_and_tests(self):
        text = (ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
        for expected in ('pull request', 'regression test', 'new functionality',
                         'python3 -m unittest discover -s tests -v', 'independent review'):
            self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()
