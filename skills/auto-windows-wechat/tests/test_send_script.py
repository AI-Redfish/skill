"""send_wechat_message.py 参数校验与入口单测（不真发消息）。

运行: uv run tests/test_send_script.py 或 python -m unittest tests/test_send_script.py
只测参数校验 / CLI 解析 / 输出结构 / 退出码映射逻辑，不触碰微信。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "send_wechat_message.py"
spec = importlib.util.spec_from_file_location("send_wechat_message", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ParamValidationTests(unittest.TestCase):
    """缺参 / 非法参数必须 ok:false 且不调用 send_message。"""

    def test_missing_message(self):
        result = mod.main({"inputs": {"target": "红色小鱼"}})
        self.assertFalse(result["output"]["ok"])
        self.assertIn("message", result["output"]["error"])

    def test_empty_message(self):
        result = mod.main({"inputs": {"message": "   "}})
        self.assertFalse(result["output"]["ok"])

    def test_empty_target(self):
        result = mod.main({"inputs": {"target": "  ", "message": "hi"}})
        self.assertFalse(result["output"]["ok"])
        self.assertNotIn("target", result["output"])

    def test_inputs_invalid_json_string(self):
        result = mod.main({"inputs": "{bad json"})
        self.assertFalse(result["output"]["ok"])
        self.assertIn("JSON", result["output"]["error"])

    def test_default_target_is_filehelper(self):
        """缺 target 时默认文件传输助手（校验 message 缺失时报错里带默认 target）。"""
        result = mod.main({"inputs": {}})
        self.assertEqual(result["output"]["target"], "文件传输助手")
        self.assertFalse(result["output"]["ok"])

    def test_filehelper_error_hint(self):
        """文件传输助手失败信息应包含置顶/可见提示。"""
        error = RuntimeError("未能确认微信已进入「文件传输助手」会话")
        # 直接测 _send 的提示注入逻辑：monkeypatch send_message 抛错
        orig = mod.send_message

        def fake(target, text, wait_idle=True, restart_wechat=False):
            raise error

        mod.send_message = fake
        try:
            result = mod._send("文件传输助手", "hi", wait_idle=False)
        finally:
            mod.send_message = orig
        self.assertFalse(result["ok"])
        self.assertIn("聊天列表可见", result["error"])

    def test_send_success_structure(self):
        orig = mod.send_message

        def fake(target, text, wait_idle=True, restart_wechat=False):
            pass

        mod.send_message = fake
        try:
            result = mod._send("红色小鱼", "hi", wait_idle=False)
        finally:
            mod.send_message = orig
        self.assertTrue(result["ok"])
        self.assertEqual(result["target"], "红色小鱼")
        self.assertNotIn("error", result)


class CliParsingTests(unittest.TestCase):
    """CLI 参数解析：位置参数 / -t -m / --no-wait。"""

    def test_positional_args(self):
        # 必须先 mock 再调用 CLI，测试绝不发送真实消息。
        orig = mod.send_message
        mod.send_message = lambda *a, **k: None
        try:
            result = mod._cli_result(["红色小鱼", "你好"])
        finally:
            mod.send_message = orig
        self.assertTrue(result["output"]["ok"])
        self.assertEqual(result["output"]["target"], "红色小鱼")

    def test_flags(self):
        orig = mod.send_message
        captured = {}

        def fake(target, text, wait_idle=True, restart_wechat=False):
            captured["target"] = target
            captured["wait_idle"] = wait_idle

        mod.send_message = fake
        try:
            mod._cli_result(["-t", "文件传输助手", "-m", "hi", "--no-wait"])
        finally:
            mod.send_message = orig
        self.assertEqual(captured["target"], "文件传输助手")
        self.assertFalse(captured["wait_idle"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
