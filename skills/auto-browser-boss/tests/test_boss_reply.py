# boss_reply.py 纯函数单测（不连 CDP）
# 运行：uv run tests/test_boss_reply.py
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

import boss_reply as br  # noqa: E402


def test_match_faq_hit():
    faqs = [{"kw": ["薪资", "工资"], "reply": "15-16K 可谈"},
            {"kw": ["到岗"], "reply": "两周内"}]
    assert br.match_faq("你好，请问薪资范围是多少", faqs)["reply"] == "15-16K 可谈"
    assert br.match_faq("多久能到岗", faqs)["reply"] == "两周内"


def test_match_faq_miss():
    faqs = [{"kw": ["薪资"], "reply": "x"}]
    assert br.match_faq("你们用什么技术栈", faqs) is None
    assert br.match_faq("", faqs) is None


def test_match_faq_empty():
    assert br.match_faq("任意", []) is None


def test_load_faq_real_file():
    faqs = br.load_faq()
    assert len(faqs) >= 1
    for f in faqs:
        assert f.get("kw") and f.get("reply")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
