#!/usr/bin/env python3
"""resolve_workspace.py — 项目测试工作空间定位/创建（多仓库模型）。

模型: 一个项目一个工作空间；一个空间可含 1~N 个 git 代码仓库
      （前后端分离/前端微应用等多仓库项目）。仓库/黑盒组件可位于空间内或
      用户提供的外部路径；登记 path，不强制 clone，组件原目录始终只读。

用法:
  # 定位：代码目录 → 所属空间（向上找 workspace.yaml）
  python3 resolve_workspace.py --repo-dir <空间内仓库目录>
  # 识别：空间外的 git 仓库 → 输出仓库名与登记建议（init 引导用）
  python3 resolve_workspace.py --repo-dir <外部代码目录>
  # 创建：项目空间（项目名经用户确认后传入）
  python3 resolve_workspace.py --project <项目名> [--workdir .] [--root <根>]
                               [--save-root] [--create]
  --workdir 用于查找/写入 .agents/.env 中的 FULLLINK_TESTSPACES_ROOT
退出码: 0=ok 1=错误(三要素信息) 2=参数错误 3=need_root(根目录未配置待用户确认)
根目录优先级: --root > .agents/.env 的 FULLLINK_TESTSPACES_ROOT > 询问用户
              （未配置时返回 need_root 与 recommended_root 推荐值，
               用户确认后 --save-root 持久化）
"""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
import json
import os
import re
import subprocess
import sys

_paths_spec = importlib.util.spec_from_file_location("worktree_paths", Path(__file__).with_name("worktree_paths.py"))
_paths = importlib.util.module_from_spec(_paths_spec)
_paths_spec.loader.exec_module(_paths)

# 推荐逻辑：扫描各盘/家目录下的常见开发子目录，命中即推荐 <开发目录>/testspaces
_DEV_SUBDIRS = ("develop", "dev", "workspace", "workspaces", "projects")
ENV_KEY = "FULLLINK_TESTSPACES_ROOT"
WORKSPACE_MARK = "workspace.yaml"
MAX_UP = 4  # 向上查找所属空间的最大层级
REPOS_DIR = "repos"
RESERVED_ROOT_ENTRIES = {"docs", "assets", "runs", "repos", ".git", "node_modules"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def fail(message: str, hint: str, action: str) -> int:
    print(json.dumps({
        "status": "error",
        "error": {"message": message, "reason": hint, "action": action},
    }, ensure_ascii=False, indent=2))
    return 1


def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        log(f"读取失败 {path}: {e}")
        return None


def load_env_file_value(workdir: str, key: str) -> str | None:
    """解析 <workdir>/.agents/.env（UTF-8，键=值，# 注释，值可带成对双引号）。"""
    path = os.path.join(workdir, ".agents", ".env")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] == '"':
                        v = v[1:-1]
                    return v
    except OSError as e:
        log(f"读取 {path} 失败（忽略，走默认）: {e}")
    return None


def save_env_file_value(workdir: str, key: str, value: str) -> str:
    """把 key="value" 写入/更新 <workdir>/.agents/.env（保留其他行，幂等），返回文件路径。"""
    env_dir = os.path.join(workdir, ".agents")
    path = os.path.join(env_dir, ".env")
    os.makedirs(env_dir, exist_ok=True)
    lines: list[str] = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    replaced = False
    for i, line in enumerate(lines):
        k, sep, _ = line.strip().partition("=")
        if sep and k.strip() == key:
            lines[i] = f'{key}="{value}"\n'
            replaced = True
            break
    if not replaced:
        lines.append(f'{key}="{value}"\n')
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return path


def resolve_root(arg_root: str | None, workdir: str):
    """根目录解析：--root > .agents/.env 的 FULLLINK_TESTSPACES_ROOT > None（需询问用户）。"""
    if arg_root:
        return os.path.abspath(arg_root), "arg"
    env_val = load_env_file_value(workdir, ENV_KEY)
    if env_val:
        return env_val, "env-file"
    return None


def recommend_root() -> str:
    """按当前系统目录推荐工作空间根目录（仅作默认值，最终由用户确认）。

    优先 Windows 各盘/WSL 挂载盘下的常见开发目录，其次家目录下开发目录，
    兜底 ~/testspaces。
    """
    home = os.path.expanduser("~")
    bases: list[str] = []
    if os.name == "nt":
        bases += [f"{letter}:" for letter in "DEFG"]
    else:
        bases += [f"/mnt/{letter}" for letter in "defg" if os.path.isdir(f"/mnt/{letter}")]
    bases.append(home)
    for base in bases:
        for sub in _DEV_SUBDIRS:
            if os.path.isdir(os.path.join(base, sub)):
                return os.path.join(base, sub, "testspaces")
    return os.path.join(home, "testspaces")


def find_workspace_up(repo_dir: str, max_up: int = MAX_UP) -> str | None:
    """从 repo_dir 逐级向上找含 workspace.yaml 的目录（含 repo_dir 自身）。

    返回工作空间绝对路径；找不到返回 None（外部仓库）。
    """
    d = os.path.abspath(repo_dir)
    for _ in range(max_up + 1):
        if os.path.isfile(os.path.join(d, WORKSPACE_MARK)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def repo_name_under(repo_dir: str, ws: str) -> str | None:
    """从空间内路径提取仓库名：repos/<仓库> 优先；兼容仓库直接放空间根的旧布局。"""
    rel = os.path.relpath(repo_dir, ws)
    if rel == ".":
        return None
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in (".", "")]
    if not parts:
        return None
    if parts[0] == REPOS_DIR and len(parts) >= 2:
        return parts[1]
    if (len(parts) == 1 and parts[0] not in RESERVED_ROOT_ENTRIES
            and not parts[0].endswith((".yaml", ".json", ".md"))):
        return parts[0]
    return None


def extract_project_name(remote_url: str) -> str:
    """从 remote url 提取仓库名：取最后一段路径，去 .git 后缀。

    支持 https://host/group/repo.git、git@host:group/repo.git、
    ssh://host/group/repo、本地路径 /x/y/repo。
    """
    name = remote_url.rstrip("/\\").replace("\\", "/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def sanitize_name(name: str) -> str:
    """名字只允许安全字符，防止路径穿越。"""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        raise RuntimeError(f"名字不安全，拒绝作为目录名：{name!r}")
    return name


def git_remote_url(repo_dir: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_dir, "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"目录不是 git 仓库或无 origin remote：{repo_dir}"
            f"（stderr: {proc.stderr.strip()[:200]}）")
    url = proc.stdout.strip()
    if not url:
        raise RuntimeError(f"git remote get-url origin 返回空：{repo_dir}")
    return url


def locate_repo(repo_dir_arg: str) -> int:
    """代码目录 → 所属空间（mode: located）或外部仓库识别（mode: external）。"""
    repo_dir = os.path.abspath(_paths.native_path(repo_dir_arg))
    if not os.path.isdir(repo_dir):
        return fail(f"代码目录不存在：{repo_dir}",
                    "路径错误或不可读",
                    "确认 --repo-dir 指向项目代码目录后重跑")

    compatibility = None
    if os.path.isfile(os.path.join(repo_dir, ".git")):
        try:
            compatibility = _paths.check_worktree(repo_dir)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return fail("worktree的Git路径不可用或跨平台不一致", str(exc),
                        "本命令只读；通过对话请用户处理 Git 路径问题，不自动修指针或强制 clone")
    ws = find_workspace_up(repo_dir)
    if ws:
        repo = repo_name_under(repo_dir, ws)
        registered = None
        if repo:
            t = read_text(os.path.join(ws, WORKSPACE_MARK))
            if t is not None:
                registered = repo in t  # 宽松核对；精确校验由 workspace_check W6 做
        print(json.dumps({"status": "ok", "data": {
            "mode": "located", "repo_dir": repo_dir, "workspace": ws,
            "repo": repo, "registered_in_yaml": registered,
            "worktree_compatibility": compatibility,
        }}, ensure_ascii=False, indent=2))
        return 0

    # 外部路径只读识别，origin 可选，不强制 clone/切换或修改仓库。
    try:
        top = subprocess.run(
            ["git", "--no-optional-locks", "-C", repo_dir, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15)
        if top.returncode != 0:
            raise RuntimeError(top.stderr.strip()[:200] or "不是可用 Git 仓库")
        repo_dir = os.path.abspath(_paths.native_path(top.stdout.strip()))
        if os.path.isfile(os.path.join(repo_dir, ".git")) and compatibility is None:
            compatibility = _paths.check_worktree(repo_dir)
        try:
            remote = git_remote_url(repo_dir)
        except RuntimeError:
            remote = None  # 本地仓库没有 origin 也能直接登记使用
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        return fail(f"目录不是可用 git 仓库：{repo_dir}", str(e),
                    "确认实际路径或通过对话请用户处理 Git 问题；黑盒目录直接登记 externalComponents.path")
    repo_name = extract_project_name(remote) if remote else os.path.basename(repo_dir)
    print(json.dumps({"status": "ok", "data": {
        "mode": "external", "repo_dir": repo_dir, "remote_url": remote,
        "repo_name": repo_name,
        "worktree_compatibility": compatibility,
        "hint": "外部仓库可直接使用：在已确认项目的 workspace.yaml 中登记 "
                "repos.<登记名>.path 为本次 repo_dir，remote_url 可选；无需 clone/移动，目录保持只读",
    }}, ensure_ascii=False, indent=2))
    return 0


def resolve_project(args) -> int:
    """创建/查询项目空间：<根目录>/<项目名>/（幂等）。"""
    try:
        project = sanitize_name(args.project.strip())
    except RuntimeError:
        return fail(f"项目名不安全：{args.project!r}",
                    "含路径分隔符或非法字符",
                    "项目名只用字母数字点横杠下划线")

    resolved = resolve_root(args.root, os.path.abspath(args.workdir))
    if resolved is None:
        print(json.dumps({
            "status": "need_root",
            "data": {
                "recommended_root": recommend_root(),
                "reason": "工作空间根目录未配置（无 --root，且 .agents/.env 无 FULLLINK_TESTSPACES_ROOT）",
                "action": "把 recommended_root 作为默认值询问用户确认或改填；"
                          "确认后带 --root <值> --save-root [--create] 重跑（--save-root 持久化到 .agents/.env）",
            },
        }, ensure_ascii=False, indent=2))
        return 3
    root, root_source = resolved
    if args.save_root:
        env_path = save_env_file_value(os.path.abspath(args.workdir), ENV_KEY, root)
        log(f"根目录已持久化到 {env_path}")

    ws = os.path.join(root, project)
    data = {"project": project, "root": root, "root_source": root_source,
            "workspace": ws, "repos_dir": os.path.join(ws, REPOS_DIR),
            "exists": os.path.isdir(ws), "created": False}
    if args.create:
        os.makedirs(os.path.join(ws, REPOS_DIR), exist_ok=True)  # 可选空间内仓库容器，允许为空
        if not data["exists"]:
            os.makedirs(ws, exist_ok=True)
            data["created"] = True
            log(f"已创建工作空间目录：{ws}（含 {REPOS_DIR}/）")
    print(json.dumps({"status": "ok", "data": data}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="项目测试工作空间定位/创建（一个项目一个空间，可含多个代码仓库）")
    ap.add_argument("--repo-dir", help="代码仓库目录：定位所属空间，或识别为外部仓库")
    ap.add_argument("--project", help="项目名（创建/查询空间目录；init 时经用户确认）")
    ap.add_argument("--workdir", default=".", help="查找/写入 .agents/.env 的工作目录")
    ap.add_argument("--root", help="显式指定工作空间根目录（最高优先级）")
    ap.add_argument("--save-root", action="store_true",
                    help="与 --root 连用：把根目录持久化到 <workdir>/.agents/.env")
    ap.add_argument("--create", action="store_true",
                    help="与 --project 连用：空间目录不存在则创建（幂等）")
    args = ap.parse_args()

    if not args.repo_dir and not args.project:
        ap.error("需要 --repo-dir（定位/识别）或 --project（创建/查询空间）")
    if args.repo_dir and args.project:
        ap.error("--repo-dir 与 --project 互斥：定位用 --repo-dir，建空间用 --project")

    if args.repo_dir:
        return locate_repo(args.repo_dir)
    return resolve_project(args)


if __name__ == "__main__":
    sys.exit(main())
