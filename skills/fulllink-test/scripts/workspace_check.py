#!/usr/bin/env python3
"""workspace_check.py — 校验测试工作空间的结构完整性与密钥卫生。

用途: init 模式第 5 步自检；测试模式进入前建议先跑（error 项必须修复）。
依赖: Python 3.9+ 纯标准库。
用法:
  python3 workspace_check.py --workspace /path/to/space [--out report.json]
检查项:
  W1 workspace.yaml 存在且含顶层键 project/kind 及 repo|repos 之一 (error)
  W2 docs/ 知识层结构（模块地图/模块目录/环境台账）存在    (error/warning)
  W3 assets/common/env.json 存在、合法 JSON 且含 activeEnv+envs (error)
  W4 明文密钥扫描（yaml/json/docs 中 password 等赋实值）       (error)
  W5 env.secret.json 的 gitignore 提醒                         (warning)
  W6 repos/ 及空间根的 git 仓库目录未登记到 workspace.yaml     (warning)
  W7 assets/probes 探针目录与 docs/02-modules 模块目录未对齐 (warning)
退出码: 0=无 error（warning 需逐条确认） 1=存在 error 2=参数错误
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys

SECRET_KEYS = re.compile(r"(password|passwd|pwd|secret|token)\"?\s*[:=]\s*\"?", re.I)
# 允许的"非明文"值：变量引用、占位符、空值
SAFE_VALUE = re.compile(r'^(\s*$|\$\{[^}]*\}|<[^>]*>|"?\$\{[^}]*\}"?|""|\'\'|null|none|changeme(?:\.example)?|example)$', re.I)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        log(f"读取失败 {path}: {e}")
        return None


def top_yaml_keys(text: str) -> set:
    """宽松提取顶层键（本工具不做完整 YAML 解析）。"""
    found = set()
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:", line)
        if m:
            found.add(m.group(1))
    return found


def check_yaml_top_keys(text: str, required=("project", "kind", "repo")) -> list[str]:
    """校验必需顶层键存在；多仓库登记表 repos 可替代单 repo 键。"""
    found = top_yaml_keys(text)
    missing = [k for k in required if k not in found]
    if "repo" in missing and "repos" in found:
        missing.remove("repo")
    return missing


def scan_plaintext_secrets(path: str, text: str) -> list[str]:
    """扫描 key: value 形式的疑似明文密钥，返回问题描述列表。"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.split("#", 1)[0]
        m = SECRET_KEYS.search(stripped)
        if not m:
            continue
        rest = stripped[m.end():].lstrip()
        if rest.startswith("${"):
            end = rest.find("}")
            value = rest[:end + 1] if end > 0 else rest
        else:
            # 值结束于引号/空白/逗号/右花括号（兼容 JSON 尾部结构与 YAML 裸值）
            value = re.split(r"[\"'\s,}]", rest, 1)[0] if rest else ""
        if SAFE_VALUE.match(value):
            continue
        hits.append(f"{path}:{i} 疑似明文密钥（{m.group(1)}=<{value[:2]}***，长度{len(value)}>）")
    return hits


def run_checks(ws: str) -> list[dict]:
    checks: list[dict] = []

    def add(cid: str, level: str, ok: bool, detail_ok: str, detail_bad: str) -> None:
        checks.append({"id": cid, "level": level, "ok": ok,
                       "detail": detail_ok if ok else detail_bad})

    # W1 workspace.yaml
    yaml_path = os.path.join(ws, "workspace.yaml")
    yaml_text = read_text(yaml_path)
    if yaml_text is None:
        add("W1", "error", False, "", f"缺少 workspace.yaml（{yaml_path}）")
    else:
        missing = check_yaml_top_keys(yaml_text)
        add("W1", "error", not missing,
            "workspace.yaml 必需顶层键齐全",
            f"workspace.yaml 缺少顶层键：{missing}（project/kind 及 repo|repos）")

    # W2 docs 知识层结构
    docs = os.path.join(ws, "docs")
    if not os.path.isdir(docs):
        add("W2", "error", False, "", f"缺少 docs/ 目录（{docs}）")
    else:
        missing = []
        if not os.path.isfile(os.path.join(docs, "01-architecture", "module-map.md")):
            missing.append("01-architecture/module-map.md")
        if not os.path.isdir(os.path.join(docs, "02-modules")):
            missing.append("02-modules/")
        if not os.path.isfile(os.path.join(docs, "04-env-matrix.md")):
            missing.append("04-env-matrix.md")
        add("W2", "warning", not missing,
            "知识层结构齐全（模块地图/模块目录/环境台账）",
            f"docs/ 缺少：{missing}（init 未完成或被移动）")

    # W3 env.json
    env_path = os.path.join(ws, "assets", "common", "env.json")
    env_text = read_text(env_path)
    if env_text is None:
        add("W3", "error", False, "", f"缺少 assets/common/env.json（{env_path}）")
    else:
        try:
            cfg = json.loads(env_text)
            ok = isinstance(cfg.get("envs"), dict) and cfg.get("activeEnv") in cfg.get("envs", {})
            add("W3", "error", ok,
                "env.json 合法且 activeEnv 指向存在的环境",
                "env.json 缺少 activeEnv/envs 结构或 activeEnv 无对应环境")
        except json.JSONDecodeError as e:
            add("W3", "error", False, "", f"env.json 不是合法 JSON：{e}")

    # W4 明文密钥扫描（覆盖 yaml、env.json、docs；secret.json 本身不扫，它就该有密钥）
    secret_hits: list[str] = []
    scan_targets = []
    if yaml_text is not None:
        scan_targets.append((yaml_path, yaml_text))
    if env_text is not None:
        scan_targets.append((env_path, env_text))
    if os.path.isdir(docs):
        for root, _dirs, names in os.walk(docs):
            for name in sorted(names):
                if name.endswith(".md"):
                    t = read_text(os.path.join(root, name))
                    if t is not None:
                        scan_targets.append((os.path.join(root, name), t))
    for p, t in scan_targets:
        secret_hits.extend(scan_plaintext_secrets(p, t))
    add("W4", "error", not secret_hits,
        "未发现明文密钥",
        "发现疑似明文密钥，移到 env.secret.json：" + "；".join(secret_hits[:5]))

    # W5 secret 文件 gitignore 提醒
    secret_path = os.path.join(ws, "assets", "common", "env.secret.json")
    if os.path.isfile(secret_path):
        ignored = False
        for gi in (os.path.join(ws, ".gitignore"),
                   os.path.join(os.path.dirname(ws), ".gitignore")):
            if os.path.isfile(gi):
                t = read_text(gi)
                if t and "env.secret.json" in t:
                    ignored = True
                    break
        add("W5", "warning", ignored,
            "env.secret.json 已被 gitignore 覆盖",
            "存在 env.secret.json 但工作空间/根目录 .gitignore 未包含它，密钥可能被提交")
    else:
        add("W5", "warning", True, "未配置 env.secret.json（相关对账将降级）", "")

    # W6 代码仓库登记一致性：repos/ 下（含空间根兼容）的 git 仓库应在 workspace.yaml 登记
    git_repos: list[str] = []
    try:
        for base in (os.path.join(ws, "repos"), ws):
            if not os.path.isdir(base):
                continue
            for n in sorted(os.listdir(base)):
                if base == ws and n in ("docs", "assets", "runs", "repos"):
                    continue
                if os.path.isdir(os.path.join(base, n, ".git")):
                    git_repos.append(n)
    except OSError:
        pass
    unregistered = [n for n in git_repos if yaml_text is None or n not in yaml_text]
    if git_repos:
        add("W6", "warning", not unregistered,
            f"repos/ 下 {len(git_repos)} 个代码仓库均已登记",
            f"存在未在 workspace.yaml 登记的代码仓库目录：{unregistered}")
    else:
        add("W6", "warning", True, "空间内无代码仓库目录（可选，骨架期正常）", "")

    # W7 探针目录与模块知识目录同名对齐（对齐后双向索引才有效）
    probes_dir = os.path.join(ws, "assets", "probes")
    modules_dir = os.path.join(ws, "docs", "02-modules")
    probe_dirs: list[str] = []
    if os.path.isdir(probes_dir):
        try:
            probe_dirs = [n for n in sorted(os.listdir(probes_dir))
                          if os.path.isdir(os.path.join(probes_dir, n))]
        except OSError:
            pass
    unmatched = [n for n in probe_dirs
                 if not os.path.isdir(os.path.join(modules_dir, n))]
    if probe_dirs:
        add("W7", "warning", not unmatched,
            f"assets/probes/ 下 {len(probe_dirs)} 个探针目录均已对齐模块知识目录",
            f"探针目录无对应 docs/02-modules/<模块>：{unmatched}（对齐后互相索引才有效）")
    else:
        add("W7", "warning", True, "无沉淀探针（骨架期正常）", "")

    return checks


def main() -> int:
    ap = argparse.ArgumentParser(description="校验测试工作空间结构完整性与密钥卫生")
    ap.add_argument("--workspace", required=True, help="工作空间目录")
    ap.add_argument("--out", help="检查结果 JSON 落盘路径（可选，stdout 始终输出）")
    args = ap.parse_args()

    ws = os.path.abspath(args.workspace)
    if not os.path.isdir(ws):
        print(json.dumps({
            "status": "error",
            "error": {"message": f"工作空间目录不存在：{ws}",
                      "reason": "路径错误或 init 未执行",
                      "action": "先运行 resolve_workspace.py --create 并完成 init 模式"}
        }, ensure_ascii=False, indent=2))
        return 1

    checks = run_checks(ws)
    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warning"]
    result = {
        "status": "ok" if not errors else "fail",
        "summary": {"errors": len(errors), "warnings": len(warnings), "total": len(checks)},
        "checks": checks,
    }
    out = json.dumps(result, ensure_ascii=False, indent=2)
    print(out)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out + "\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
