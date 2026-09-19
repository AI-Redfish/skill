#!/usr/bin/env python3
"""review_checklist.py — 对被创建/修改的 skill 做机器评审（静态检查）。

评审门（SKILL.md §4.1）的第一步：结构、frontmatter、触发描述质量、正文预算、
脚本规范（PEP 723 / shebang / 无交互输入）、密钥硬编码扫描、.env 卫生、测试存在性。
本脚本不替代 AI 双评审，只拦截"机器可判定"的问题。

用法：
  python review_checklist.py --skill <target> [--workdir DIR] [--json OUT] [--compact]

输出：JSON 到 stdout（status: pass|fail；checks 明细，含 message/hint；summary 统计）。
退出码：0 = 无 error 级问题（warning 需人工确认）；1 = 存在 error；2 = 输入错误。
纯标准库，Python 3.9+（stdlib 识别在 3.10+ 用 sys.stdlib_module_names，低版本退化为内置清单）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# 常见标准库模块（Python 3.9 无 sys.stdlib_module_names 时的兜底清单）
FALLBACK_STDLIB = {
    "abc", "argparse", "ast", "asyncio", "base64", "binascii", "bisect", "collections",
    "concurrent", "configparser", "contextlib", "copy", "csv", "ctypes", "dataclasses",
    "datetime", "decimal", "difflib", "email", "enum", "fnmatch", "functools", "gc",
    "getpass", "getopt", "glob", "gzip", "hashlib", "heapq", "html", "http", "importlib",
    "inspect", "io", "itertools", "json", "logging", "math", "mimetypes", "multiprocessing",
    "operator", "os", "pathlib", "pickle", "platform", "pprint", "queue", "random", "re",
    "secrets", "select", "shlex", "shutil", "signal", "socket", "sqlite3", "ssl", "stat",
    "statistics", "string", "struct", "subprocess", "sys", "tarfile", "tempfile", "textwrap",
    "threading", "time", "token", "traceback", "typing", "unittest", "urllib", "uuid",
    "warnings", "weakref", "webbrowser", "xml", "zipfile", "zlib", "__future__",
}

SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
                r"client[_-]?secret|private[_-]?key)\b\s*[=:]\s*[\"'][^\"'${}<>]{6,}[\"']"),
     "疑似硬编码凭据（键名=字面值）"),
    (re.compile(r"(?i)\bauthorization\s*[:=]\s*[\"']?(bearer|basic)\s+[a-z0-9._\-]{8,}"),
     "疑似硬编码 Authorization 头"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "疑似 AWS Access Key"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "疑似 API 密钥（sk- 前缀）"),
    (re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), "疑似私钥内容"),
]
# 占位符豁免：这些不算真实密钥
PLACEHOLDER = re.compile(
    r"(?i)\$\{|<[^>]+>|your[_-]|xxx+|example|placeholder|change[_-]?me|dummy|sample|"
    r"replace[_-]?me|os\.environ|getenv|\$\{|%\s*\(|\{[a-z_]+\}|格式|示例|脱敏|\*\*\*")

MAX_BODY_LINES = 500          # error 上限
WARN_BODY_LINES = 400         # warn 阈值
LONG_BODY_NO_REF = 300        # 超过此行数且无 references/ 则 warn


def stdlib_names() -> frozenset:
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return frozenset(names)
    return frozenset(FALLBACK_STDLIB)


class Checker:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, cid: str, severity: str, ok: bool, message: str, hint: str = "") -> None:
        if "|" in message:  # 约定：message 为 "通过描述 | 失败描述"
            ok_part, _, fail_part = message.partition("|")
            message = (ok_part if ok else fail_part).strip()
        status = "pass" if ok else ("warn" if severity == "warn" else "fail")
        self.checks.append({"id": cid, "severity": severity, "status": status,
                            "message": message, "hint": hint if not ok else ""})

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c["status"] == "fail")

    @property
    def warned(self) -> int:
        return sum(1 for c in self.checks if c["status"] == "warn")


def parse_frontmatter(text: str) -> tuple[dict, str] | None:
    """极简 YAML frontmatter 解析（仅取顶层 key: value）。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end].strip("\n")
    body = text[end + 4:]
    meta: dict = {}
    current_nested = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line[:1] not in (" ", "\t") and ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            current_nested = key if not val else None
            meta[key] = val.strip("\"'")
        elif line[:1] in (" ", "\t") and current_nested:
            k, _, v = line.strip().partition(":")
            meta.setdefault("_nested_" + current_nested, {})[k.strip()] = v.strip().strip("\"'")
    return meta, body


def third_party_imports(path: Path) -> list[str]:
    """返回文件中 import 的非标准库顶层模块名。解析失败返回 []（交给其他检查）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (SyntaxError, OSError):
        return []
    stdlib = stdlib_names()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    local = {p.stem for p in path.parent.glob("*.py")}
    return sorted(m for m in mods if m not in stdlib and m not in local and m != "__future__")


def iter_text_files(root: Path):
    skip_dirs = {"__pycache__", ".git", "node_modules", ".venv", "evals"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.suffix.lower() in (".md", ".py", ".sh", ".json", ".yaml", ".yml",
                                ".toml", ".txt", ".example", ".sample", ".template", ".env"):
            yield p


def check(skill: Path, workdir: Path) -> dict:
    c = Checker()

    # --- 结构与 frontmatter ---
    skill_md = skill / "SKILL.md"
    c.add("structure.skillmd", "error", skill_md.is_file(),
          f"SKILL.md 存在 | 缺少 SKILL.md：{skill_md}",
          "SKILL.md 是 skill 的唯一必需文件")

    meta, body = None, ""
    if skill_md.is_file():
        parsed = parse_frontmatter(skill_md.read_text(encoding="utf-8-sig", errors="replace"))
        c.add("frontmatter.parse", "error", parsed is not None,
              "frontmatter 可解析 | SKILL.md 缺少合法的 YAML frontmatter（--- 包裹的头部）",
              "格式：---\\nname: xxx\\ndescription: xxx\\n---")
        if parsed:
            meta, body = parsed

    if meta is not None:
        name = str(meta.get("name", ""))
        ok_name = bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)) and len(name) <= 64
        c.add("frontmatter.name", "error", ok_name,
              f"name 合法（{name}）| name 非法：{name!r}（只允许小写字母/数字/连字符，≤64 字符）",
              "只能小写字母/数字/连字符，不能以 - 开头结尾或连续 --")
        c.add("frontmatter.name_dir_match", "error", name == skill.name,
              f"name 与目录名一致 | name={name!r} 与目录名 {skill.name!r} 不一致",
              "name 必须与父目录名完全一致")
        desc = str(meta.get("description", ""))
        ok_desc = bool(desc.strip()) and len(desc) <= 1024
        c.add("frontmatter.description", "error", ok_desc,
              f"description 合法（{len(desc)} 字符）| description 为空或超过 1024 字符",
              "description 是触发唯一依据，须非空且 ≤1024 字符")
        has_when = re.search(
            r"(?i)(use when|when the user|当用户|时使用|适用|场景|触发|should (?:be )?use)", desc)
        c.add("frontmatter.description_trigger", "warn",
              len(desc) >= 30 and bool(has_when),
              "description 含功能+触发场景描述 | description 过短或缺少“什么时候用”的场景描述",
              "同时写清“做什么 + 什么时候用”，含用户会说的触发关键词")
        has_not = re.search(
            r"(?i)(不适用|when not|not for|don.t use|不要使用|不要直接套用|不适合|不应使用)", body)
        c.add("body.not_for", "warn", bool(has_not),
              "正文声明了不适用场景 | 正文未声明不适用场景，易被误触发",
              "加“不适用场景”小节，列出相邻领域与简单问答等负向场景")

    # --- 正文预算与组织 ---
    lines = body.count("\n") + 1 if body else 0
    c.add("body.length", "error", lines <= MAX_BODY_LINES,
          f"正文 {lines} 行（≤{MAX_BODY_LINES}）| 正文 {lines} 行，超过 {MAX_BODY_LINES} 行上限",
          "把详细资料外置到 references/，主文件只留流程")
    if lines > WARN_BODY_LINES:
        c.add("body.length_warn", "warn", False,
              f"正文 {lines} 行，逼近上限",
              "建议外置细节，控制在 400 行内")
    headings = re.findall(r"^#{1,3} ", body, re.MULTILINE)
    c.add("body.structure", "warn", len(headings) >= 3,
          f"正文有 {len(headings)} 个标题，结构清晰 | 标题过少（{len(headings)} 个）",
          "至少包含：功能说明/操作步骤/示例/错误处理等分节")
    has_example = re.search(r"(?i)(\bexample|示例|触发示例|用法示例)", body)
    c.add("body.examples", "warn", bool(has_example),
          "正文含示例 | 正文缺少示例（Few-shot 触发示例能显著提升稳定性）",
          "加“触发示例”小节：3~5 句用户真实说法")

    # --- 双闭环内嵌（强制：生成的 skill 执行时也须遵循双闭环） ---
    loop1 = ("理解闭环" in body) and ("95%" in body) and \
            bool(re.search(r"(一次|每次)只问一个", body))
    c.add("body.loop_understanding", "error", loop1,
          "理解闭环已内嵌 | 缺少理解闭环规则（先提问/每次只问一个/十要素/95% 信心门槛）",
          "按 references/authoring-standards.md 的双闭环模板整段写入 SKILL.md 正文靠前位置")
    loop2 = ("输出审查闭环" in body) and ("95%" in body) and \
            ("复述" in body) and ("假设" in body)
    c.add("body.loop_output_review", "error", loop2,
          "输出审查闭环已内嵌 | 缺少输出审查闭环规则（审查-修正循环/95%/复述+假设+不确定性标注）",
          "同上，整段写入双闭环模板（含最终输出要求）")
    has_ref_dir = (skill / "references").is_dir()
    if lines > LONG_BODY_NO_REF and not has_ref_dir:
        c.add("body.progressive_disclosure", "warn", False,
              f"正文 {lines} 行但无 references/ 目录",
              "渐进式披露：细节外置，按需加载")

    # --- 脚本规范 ---
    scripts_dir = skill / "scripts"
    py_files = sorted(scripts_dir.glob("*.py")) if scripts_dir.is_dir() else []
    for sf in py_files:
        text = sf.read_text(encoding="utf-8-sig", errors="replace")
        rel = f"scripts/{sf.name}"
        has_pep723 = "# /// script" in text
        non_std = third_party_imports(sf)
        if non_std:
            c.add(f"scripts.pep723.{sf.name}", "error", has_pep723,
                  f"{rel} 第三方依赖（{', '.join(non_std)}）已用 PEP 723 声明 | "
                  f"{rel} 使用第三方依赖 {non_std} 但缺少 PEP 723 内联声明，uv run 无法隔离安装",
                  "文件头加：# /// script\\n# dependencies = [\\\"包名\\\"]\\n# ///")
        else:
            c.add(f"scripts.pep723.{sf.name}", "error", True,
                  f"{rel} 仅用标准库（无需 PEP 723）")
        # 注：检测串拼接书写，避免本文件自身命中交互输入检查
        interactive_marker = "inp" + "ut("
        c.add(f"scripts.no_input.{sf.name}", "warn", interactive_marker not in text,
              f"{rel} 无交互式输入 | {rel} 含交互式输入函数 input，Agent 在非交互 shell 运行会卡死",
              "输入一律通过参数/环境变量/stdin 传入")
        has_doc = '"""' in text[:800] or "argparse" in text
        c.add(f"scripts.usable.{sf.name}", "warn", has_doc,
              f"{rel} 有用法说明 | {rel} 缺少头部 docstring 或 argparse（Agent 无法了解接口）",
              "加头部 docstring（用途/依赖/用法）并提供 --help")

    # --- 安全：密钥与 .env 卫生 ---
    hits = []
    for p in iter_text_files(skill):
        if p.name.endswith((".example", ".sample", ".template")):
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
                for pat, label in SECRET_PATTERNS:
                    m = pat.search(line)
                    if m and not PLACEHOLDER.search(m.group(0)):
                        hits.append(f"{p.relative_to(skill)}:{i} {label}")
                        break
        except OSError:
            continue
    c.add("security.secrets", "error", not hits,
          "未发现硬编码密钥 | 发现疑似硬编码密钥：" + "; ".join(hits[:5]),
          "密钥/账号放 <workdir>/.agents/.env（env_utils.py 管理），代码从环境读取")
    env_inside = [p for p in skill.rglob(".env")] + \
                 [p for p in skill.rglob(".agents") if p.is_dir()]
    c.add("security.env_location", "error", not env_inside,
          "skill 目录内无 .env/.agents | skill 目录内出现 " +
          ", ".join(str(p.relative_to(skill)) for p in env_inside),
          ".env 属于运行时工作目录（<workdir>/.agents/.env），不随 skill 分发")

    # --- 运行时 .env 的 gitignore 卫生（针对 workdir）---
    env_file = workdir / ".agents" / ".env"
    if env_file.is_file():
        git_root = workdir
        while not (git_root / ".git").exists() and git_root.parent != git_root:
            git_root = git_root.parent
        gi = git_root / ".gitignore"
        covered = False
        if gi.is_file():
            for line in gi.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                s = line.strip()
                if s in (".env", ".agents/.env", ".agents/", ".agents/*", ".env*"):
                    covered = True
                    break
        c.add("security.env_gitignored", "warn", covered,
              ".agents/.env 已被 .gitignore 覆盖 | <workdir>/.agents/.env 存在但未被 .gitignore 覆盖",
              "运行 env_utils.py ensure-gitignore（含密钥的文件不得入库）")
    else:
        c.add("security.env_gitignored", "warn", True, "运行时 .agents/.env 尚不存在（测试阶段收取）")

    # --- 测试与元数据 ---
    has_tests = (skill / "tests").is_dir() or (skill / "evals").is_dir()
    c.add("tests.present", "warn", has_tests,
          "存在 tests/ 或 evals/ | 未发现 tests/ 或 evals/ 目录",
          "门禁流程要求测试；至少准备 evals/evals.json 与脚本单测")
    has_version = meta is not None and (
        "_nested_metadata" in (meta or {}) and "version" in (meta or {}).get("_nested_metadata", {}))
    c.add("metadata.version", "warn", bool(has_version),
          "metadata.version 已声明 | frontmatter 未声明 metadata.version",
          "加 metadata.version（语义化版本），便于回溯与升级")

    failed, warned = c.failed, c.warned
    return {
        "status": "pass" if failed == 0 else "fail",
        "skill": str(skill),
        "checked_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {"total": len(c.checks), "passed": len(c.checks) - failed - warned,
                    "warned": warned, "failed": failed},
        "checks": c.checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="skill 机器评审清单")
    parser.add_argument("--skill", required=True, help="被检 skill 目录")
    parser.add_argument("--workdir", default=".", help="运行时工作目录（默认当前目录）")
    parser.add_argument("--json", dest="json_out", default=None, help="结果写入该 JSON 文件")
    parser.add_argument("--compact", action="store_true", help="只输出未通过的检查项")
    args = parser.parse_args()

    skill = Path(args.skill).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve()
    if not skill.is_dir():
        print(json.dumps({"status": "error",
                          "error": {"code": "SKILL_NOT_FOUND",
                                    "message": f"skill 目录不存在：{skill}",
                                    "hint": "检查 --skill 路径"}}, ensure_ascii=False))
        return 2

    result = check(skill, workdir)
    shown = dict(result)
    if args.compact:
        shown["checks"] = [x for x in result["checks"] if x["status"] != "pass"]
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    if result["summary"]["failed"]:
        print(f"[review_checklist] 未通过：{result['summary']['failed']} 个 error 级问题，"
              f"请按 checks[].hint 修复后重跑", file=sys.stderr)
        return 1
    if result["summary"]["warned"]:
        print(f"[review_checklist] 无 error，但有 {result['summary']['warned']} 个 warning，"
              f"需在 AI 评审中逐条确认", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
