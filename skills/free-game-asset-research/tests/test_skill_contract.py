"""Static contract checks for free-game-asset-research; stdlib only."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.evals = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))

    def test_frontmatter_name_matches_directory(self):
        self.assertIn("name: free-game-asset-research", self.text.split("---", 2)[1])
        self.assertEqual(ROOT.name, "free-game-asset-research")

    def test_credentials_never_requested_or_bypassed(self):
        self.assertRegex(self.text, r"不索取用户密码")
        self.assertRegex(self.text, r"不绕过登录墙")

    def test_project_write_requires_explicit_request(self):
        self.assertRegex(self.text, r"只有用户明确要求接入时")

    def test_eval_suite_has_positive_and_negative_cases(self):
        self.assertEqual(len(self.evals["evals"]), 8)
        prompts = [x["prompt"] for x in self.evals["evals"]]
        self.assertTrue(any("找一个免费的" in p for p in prompts))
        self.assertTrue(any("不搜索素材" in p for p in prompts))
        self.assertTrue(any("绕过付费" in p for p in prompts))

    def test_no_placeholder_or_secret_patterns(self):
        self.assertFalse(re.search(r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,}", self.text))

if __name__ == "__main__":
    unittest.main()
