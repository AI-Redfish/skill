#!/usr/bin/env python3
"""run_tests.py — skill-creator-plus 自身脚本的回归测试（纯标准库 unittest）。

用法：python tests/run_tests.py [-v]      # 或 uv run tests/run_tests.py
覆盖：ensure_dependency 定位、gate 门禁生命周期、review_checklist 正反例、
env_utils 读写与 gitignore、gen_test_report（有依赖副本时才跑，否则 skip）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"
PY = sys.executable


def run_script(name: str, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, str(SCRIPTS / name), *args],
                          capture_output=True, text=True, timeout=120, env=env)


def as_json(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout)


def make_dep_stub(root: Path) -> Path:
    """构造最小 skill-creator 存根（用于 locate/报告测试，不打网络）。"""
    dep = root / "stub" / "skill-creator"
    (dep / "scripts").mkdir(parents=True)
    (dep / "eval-viewer").mkdir()
    (dep / "agents").mkdir()
    (dep / "SKILL.md").write_text("---\nname: skill-creator\ndescription: stub\n---\n# x\n",
                                  encoding="utf-8")
    for rel in ("scripts/aggregate_benchmark.py", "eval-viewer/generate_review.py"):
        (dep / rel).write_text("# stub\n", encoding="utf-8")
    return dep


class FakeRepo:
    """本地 git 仓库夹具：模拟 anthropics/skills 的 skills/skill-creator 布局。"""

    def __init__(self, root: Path):
        self.repo = root / "fake-skills-repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("checkout", "-q", "-b", "main")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=str(self.repo), check=True,
                       capture_output=True, text=True, timeout=60)

    def commit_version(self, version: int) -> None:
        dep = self.repo / "skills" / "skill-creator"
        dep.mkdir(parents=True, exist_ok=True)
        (dep / "scripts").mkdir(exist_ok=True)
        (dep / "SKILL.md").write_text(
            f"---\nname: skill-creator\ndescription: v{version}\n---\n# v{version}\n",
            encoding="utf-8")
        (dep / "scripts" / "package_skill.py").write_text("# stub\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", f"v{version}")

    @property
    def url(self) -> str:
        return str(self.repo)


class TestEnsureDependency(unittest.TestCase):
    def test_locate_via_env_var(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dep = make_dep_stub(root)
            proj = root / "proj"
            proj.mkdir()
            proc = run_script("ensure_dependency.py", "--workdir", str(proj),
                              env_extra={"SKILL_CREATOR_PLUS_DEP_PATH": str(dep)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = as_json(proc)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["source"], "env")
            self.assertTrue(data["capabilities"]["benchmark"])
            self.assertFalse(data["capabilities"]["init"])  # 存根无 init（新版语义）

    def test_workdir_missing(self):
        proc = run_script("ensure_dependency.py", "--workdir", "/nonexistent/xyz")
        self.assertEqual(proc.returncode, 2)


class TestUpdateMechanism(unittest.TestCase):
    """安装标记、龄期自动更新、强制更新、外部副本不劫持。"""

    def _install(self, proj: Path, repo: FakeRepo, *extra: str) -> dict:
        r = run_script("ensure_dependency.py", "--workdir", str(proj),
                       "--repo", repo.url, *extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return as_json(r)

    def test_install_marker_and_forced_update(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = FakeRepo(root)
            repo.commit_version(1)
            proj = root / "proj"
            proj.mkdir()
            data = self._install(proj, repo)
            self.assertEqual(data["status"], "installed")
            self.assertTrue(data["version"]["managed"])
            self.assertTrue(data["version"]["commit"])
            dep = proj / ".agents" / "skills" / "skill-creator"
            self.assertIn("v1", (dep / "SKILL.md").read_text(encoding="utf-8"))
            self.assertTrue((dep / ".scp-install.json").is_file())
            # 上游出新版 → --update 强制更新
            repo.commit_version(2)
            data = self._install(proj, repo, "--update")
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data.get("updated"))
            self.assertEqual(data["source"], "update")
            self.assertIn("v2", (dep / "SKILL.md").read_text(encoding="utf-8"))

    def test_staleness_triggers_auto_update(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = FakeRepo(root)
            repo.commit_version(1)
            proj = root / "proj"
            proj.mkdir()
            self._install(proj, repo)
            repo.commit_version(2)
            # 龄期阈值 0 → 副本立即视为过期 → 自动静默更新
            data = self._install(proj, repo, "--max-age-days", "0")
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data.get("updated"))
            dep = proj / ".agents" / "skills" / "skill-creator"
            self.assertIn("v2", (dep / "SKILL.md").read_text(encoding="utf-8"))

    def test_no_auto_update_keeps_old(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = FakeRepo(root)
            repo.commit_version(1)
            proj = root / "proj"
            proj.mkdir()
            self._install(proj, repo)
            repo.commit_version(2)
            data = self._install(proj, repo, "--max-age-days", "0", "--no-auto-update")
            self.assertEqual(data["status"], "ok")
            self.assertNotIn("updated", data)
            self.assertTrue(data["version"]["stale"])  # 仍会报告过期
            dep = proj / ".agents" / "skills" / "skill-creator"
            self.assertIn("v1", (dep / "SKILL.md").read_text(encoding="utf-8"))

    def test_foreign_copy_never_touched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dep = make_dep_stub(root)  # 无管理标记的外部副本
            proj = root / "proj"
            proj.mkdir()
            for extra in ([], ["--update"], ["--max-age-days", "0"]):
                r = run_script("ensure_dependency.py", "--workdir", str(proj),
                               "--repo", str(root), *extra,
                               env_extra={"SKILL_CREATOR_PLUS_DEP_PATH": str(dep)})
                self.assertEqual(r.returncode, 0, r.stdout)
                data = as_json(r)
                self.assertEqual(data["status"], "ok")
                self.assertFalse(data["version"]["managed"])
                self.assertNotIn("updated", data)
            self.assertNotIn(("v"), (dep / "SKILL.md").read_text(encoding="utf-8"))
            self.assertFalse((proj / ".agents").exists())  # 不另行安装


class TestGate(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name) / "ws"
        (self.ws / "skill-x").mkdir(parents=True)
        self.checklist = self.ws / "cl.json"

    def tearDown(self):
        self._td.cleanup()

    def _gate(self, *args):
        return run_script("gate.py", *args)

    def test_full_lifecycle_with_guards(self):
        r = self._gate("init", "--skill", str(self.ws / "skill-x"), "--workspace", str(self.ws))
        self.assertEqual(r.returncode, 0)
        # 理解闭环未过：低信心拒绝
        r = self._gate("clarify-pass", "--workspace", str(self.ws), "--confidence", "80")
        self.assertEqual(r.returncode, 2)
        # 理解闭环未过：不得评审（phase=clarify 拒绝 review-pass）
        self.checklist.write_text('{"status":"pass","summary":{"failed":0}}', encoding="utf-8")
        r = self._gate("review-pass", "--workspace", str(self.ws),
                       "--confidence", "96", "--checklist", str(self.checklist))
        self.assertEqual(r.returncode, 2)
        # 理解闭环通过 → 进入编写
        r = self._gate("clarify-pass", "--workspace", str(self.ws), "--confidence", "95",
                       "--notes", "复述：…；关键假设：…")
        self.assertEqual(r.returncode, 0)
        # 低置信度拒绝
        self.checklist.write_text('{"status":"pass","summary":{"failed":0}}', encoding="utf-8")
        r = self._gate("review-pass", "--workspace", str(self.ws),
                       "--confidence", "80", "--checklist", str(self.checklist))
        self.assertEqual(r.returncode, 2)
        # checklist 未通过拒绝
        self.checklist.write_text('{"status":"fail"}', encoding="utf-8")
        r = self._gate("review-pass", "--workspace", str(self.ws),
                       "--confidence", "96", "--checklist", str(self.checklist))
        self.assertEqual(r.returncode, 2)
        # 测试未评审先跑 → 拒绝
        r = self._gate("test-pass", "--workspace", str(self.ws))
        self.assertEqual(r.returncode, 2)
        # 合法评审通过
        self.checklist.write_text('{"status":"pass","summary":{"failed":0,"warned":0}}',
                                  encoding="utf-8")
        r = self._gate("review-pass", "--workspace", str(self.ws),
                       "--confidence", "95", "--checklist", str(self.checklist))
        self.assertEqual(r.returncode, 0)
        # 测试失败 → 退回 writing 且作废评审
        r = self._gate("test-fail", "--workspace", str(self.ws))
        self.assertEqual(r.returncode, 0)
        st = as_json(self._gate("show", "--workspace", str(self.ws)))["state"]
        self.assertEqual(st["phase"], "writing")
        self.assertFalse(st["review"]["passed"])
        # 未经重新评审直接 test-pass → 拒绝
        r = self._gate("test-pass", "--workspace", str(self.ws))
        self.assertEqual(r.returncode, 2)
        # 重评 → 测试过 → 报告缺失文件拒绝 → 补齐后完成
        self._gate("review-pass", "--workspace", str(self.ws),
                   "--confidence", "96", "--checklist", str(self.checklist))
        self._gate("test-pass", "--workspace", str(self.ws))
        r = self._gate("report-done", "--workspace", str(self.ws),
                       "--report", str(self.ws / "nope.md"))
        self.assertEqual(r.returncode, 2)
        report = self.ws / "report.md"
        report.write_text("# 报告", encoding="utf-8")
        r = self._gate("report-done", "--workspace", str(self.ws), "--report", str(report))
        self.assertEqual(r.returncode, 0)
        st = as_json(self._gate("show", "--workspace", str(self.ws)))["state"]
        self.assertEqual(st["phase"], "done")
        self.assertEqual(st["review"]["rounds"], 2)
        self.assertEqual(st["test"]["rounds"], 2)  # 1 轮失败 + 1 轮通过

    def test_requirement_change_reclarify_from_writing(self):
        """需求变更：从 writing 阶段重新走理解闭环（scope-change 路径）。"""
        self._gate("init", "--skill", str(self.ws / "skill-x"), "--workspace", str(self.ws))
        self._gate("clarify-pass", "--workspace", str(self.ws), "--confidence", "95")
        # 用户改需求 → 回到理解闭环 → 重新通过
        r = self._gate("clarify-fail", "--workspace", str(self.ws), "--notes", "新增导出格式")
        self.assertEqual(r.returncode, 0)
        st = as_json(self._gate("show", "--workspace", str(self.ws)))["state"]
        self.assertEqual(st["phase"], "clarify")
        r = self._gate("clarify-pass", "--workspace", str(self.ws), "--confidence", "96")
        self.assertEqual(r.returncode, 0)
        st = as_json(self._gate("show", "--workspace", str(self.ws)))["state"]
        self.assertEqual(st["phase"], "writing")
        self.assertTrue(st["clarify"]["passed"])


GOOD_SKILL_MD = """---
name: demo-skill
description: 演示用 skill。当用户想演示时使用，处理 xxx 文件并输出 yyy。
metadata:
  author: t
  version: "1.0"
---
# demo-skill
## 双闭环流程（最高优先级）
### 第一闭环：理解闭环
回答前先提问，每次只问一个问题，围绕真实目标/背景/约束等追问，
对用户真正想要什么有 95% 信心前只提问澄清，不给最终方案。
### 第二闭环：输出审查闭环
形成答案后不直接输出，先自查再修正再审查，直到 95% 准确性信心。
### 最终输出要求
先一句话复述需求，再给可执行方案，说明关键假设与剩余不确定性。
## 功能说明
做演示。
## 操作步骤
1. 步骤一
## 示例
- 演示一下
## 错误处理
见退出码表。
## 不适用场景
- 非演示任务
"""


class TestReviewChecklist(unittest.TestCase):
    def _make(self, root: Path, skill_md: str, script: str | None = None) -> Path:
        sk = root / "demo-skill"
        (sk / "scripts").mkdir(parents=True, exist_ok=True)
        (sk / "SKILL.md").write_text(skill_md, encoding="utf-8")
        if script:
            (sk / "scripts" / "s.py").write_text(script, encoding="utf-8")
        return sk

    def test_good_skill_passes(self):
        with tempfile.TemporaryDirectory() as td:
            sk = self._make(Path(td), GOOD_SKILL_MD,
                            '#!/usr/bin/env python3\n"""doc"""\nimport json\nprint(json.dumps({}))\n')
            r = run_script("review_checklist.py", "--skill", str(sk), "--workdir", td)
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_bad_skill_fails(self):
        with tempfile.TemporaryDirectory() as td:
            # 检测用假密钥拼接书写，避免本文件自身命中密钥扫描
            bad = GOOD_SKILL_MD.replace("name: demo-skill", "name: DemoSkill")
            sk = self._make(Path(td), bad,
                            'import requests\nAPI_KEY = "' + "sk-" + 'abcdefgh12345678"\n')
            out = Path(td) / "cl.json"
            r = run_script("review_checklist.py", "--skill", str(sk), "--workdir", td,
                           "--json", str(out))
            self.assertEqual(r.returncode, 1)
            data = json.loads(out.read_text(encoding="utf-8"))
            ids = {c["id"] for c in data["checks"] if c["status"] == "fail"}
            self.assertIn("frontmatter.name", ids)
            self.assertIn("frontmatter.name_dir_match", ids)
            self.assertIn("scripts.pep723.s.py", ids)
            self.assertIn("security.secrets", ids)

    def test_missing_double_loop_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            # 整段删除双闭环内容（只删标题不够，正文要素仍会被检测到）
            start = GOOD_SKILL_MD.index("## 双闭环流程")
            end = GOOD_SKILL_MD.index("## 功能说明")
            bad = GOOD_SKILL_MD[:start] + GOOD_SKILL_MD[end:]
            sk = self._make(Path(td), bad)
            r = run_script("review_checklist.py", "--skill", str(sk), "--workdir", td)
            self.assertEqual(r.returncode, 1)
            ids = {c["id"] for c in json.loads(
                r.stdout[r.stdout.index("{"):])["checks"] if c["status"] == "fail"}
            self.assertIn("body.loop_understanding", ids)
            self.assertIn("body.loop_output_review", ids)

    def test_env_inside_skill_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            sk = self._make(Path(td), GOOD_SKILL_MD)
            (sk / ".agents").mkdir()
            (sk / ".agents" / ".env").write_text("A=1\n", encoding="utf-8")
            r = run_script("review_checklist.py", "--skill", str(sk), "--workdir", td)
            self.assertEqual(r.returncode, 1)
            self.assertIn("security.env_location", r.stdout)


class TestEnvUtils(unittest.TestCase):
    def test_roundtrip_and_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "proj"
            proj.mkdir()
            subprocess.run(["git", "init", "-q", str(proj)], check=True,
                           capture_output=True)  # noqa
            r = run_script("env_utils.py", "missing", "--keys", "K1,K2",
                           "--workdir", str(proj))
            self.assertEqual(as_json(r)["missing"], ["K1", "K2"])
            run_script("env_utils.py", "set", "K1=value1", "K2=v2", "--workdir", str(proj))
            r = run_script("env_utils.py", "get", "K1", "--workdir", str(proj))
            self.assertEqual(as_json(r)["value"], "value1")
            # 脱敏：len>4 保留前 2 位
            r = run_script("env_utils.py", "list", "--workdir", str(proj))
            self.assertEqual(as_json(r)["keys"]["K1"], "va***")
            # gitignore
            r = run_script("env_utils.py", "ensure-gitignore", "--workdir", str(proj))
            self.assertEqual(as_json(r)["action"], "added")
            r = run_script("env_utils.py", "ensure-gitignore", "--workdir", str(proj))
            self.assertEqual(as_json(r)["action"], "exists")
            gi = (proj / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".agents/.env", gi)
            # 幂等更新不堆空行
            run_script("env_utils.py", "set", "K1=v1b", "--workdir", str(proj))
            text = (proj / ".agents" / ".env").read_text(encoding="utf-8")
            self.assertEqual([l for l in text.splitlines() if l], ["K1=v1b", "K2=v2"])

class TestGenTestReport(unittest.TestCase):
    def test_report_with_stub_dep(self):
        sys.path.insert(0, str(SCRIPTS))
        from ensure_dependency import locate  # noqa: E402
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stub = make_dep_stub(root)
            # 官方脚本是存根 → 期望整体 degraded 但报告仍生成
            ws = root / "ws"
            it = ws / "iteration-1" / "eval-1-demo" / "with_skill"
            (it / "outputs").mkdir(parents=True)
            (it / "run-1").mkdir()
            (it / "run-1" / "grading.json").write_text(json.dumps({
                "summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1},
                "expectations": [{"text": "t", "passed": True, "evidence": "e"}]}),
                encoding="utf-8")
            r = run_script("gen_test_report.py", "--workspace", str(ws),
                           "--skill-name", "demo", "--dep", str(stub))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            data = as_json(r)
            self.assertTrue(data["degraded"])  # 存根脚本必然失败 → 降级记录
            self.assertTrue((ws / "reports" / "test-report.md").is_file())
        _ = locate  # 避免未使用告警

    def test_missing_workspace(self):
        r = run_script("gen_test_report.py", "--workspace", "/nonexistent/xyz",
                       "--skill-name", "x")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
