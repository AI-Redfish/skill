#!/usr/bin/env python3
"""ensure_dependency.py — 检查/安装/更新 anthropics skill-creator（本 skill 的运行依赖）。

每次 skill-creator-plus 触发时都必须先运行本脚本（见 SKILL.md §0）。

行为：
1. 按候选顺序搜索已安装的 skill-creator（项目级 .agents/.claude 优先，再用户级）；
2. 未找到则自动安装到 <workdir>/.agents/skills/skill-creator：
   a) git clone --depth 1（首选，可精确控制安装位置）
   b) stdlib urllib 下载 GitHub tarball（无 git 时）
   c) npx -y skills add（最后手段，装到 .agents/ 后再复制到目标位置）
   安装时写入管理标记 .scp-install.json（来源/commit/安装时间），供后续更新判断；
3. 更新策略（只更新带管理标记的副本，外部副本一律不动）：
   - 默认：本地副本龄期 ≥ --max-age-days（默认 14 天）→ 自动静默更新；
     离线/失败不阻断，沿用旧版并在结果中标注 update_failed
   - --update：立即强制更新
   - --no-auto-update：本次跳过自动更新（结果仍报告 stale）
4. 探测该版本的能力表（新旧版本脚本名不同，按"能力"而非"文件名"适配）。

用法：
  python ensure_dependency.py [--workdir DIR] [--ref BRANCH] [--repo URL]
                              [--update | --no-auto-update] [--max-age-days N]
                              [--reinstall] [--json OUT]

输出：JSON 到 stdout（status: ok | installed | error；capabilities 能力表；
version 版本信息；updated/update_failed 更新结果；hint 引导）。
退出码：0 = ok/installed（含"沿用旧版"的降级场景）；1 = 安装失败；2 = 参数/输入错误。
纯标准库，Python 3.9+；uv run 与 python 直跑均可。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

REPO_URL = "https://github.com/anthropics/skills"
DEFAULT_REF = "main"
SUBDIR = "skills/skill-creator"  # 仓库内相对路径
MARKER_NAME = ".scp-install.json"  # 管理标记：本 skill 安装的副本才带
MANAGED_BY = "skill-creator-plus"
DEFAULT_MAX_AGE_DAYS = 14

# 能力名 -> 相对路径（相对 skill-creator 根）。value 为 None 表示该版本未提供。
CAPABILITY_FILES = {
    "validate": "scripts/quick_validate.py",        # 新版：SKILL.md 快速校验
    "init": "scripts/init_skill.py",                 # 旧版：骨架生成（新版已移除）
    "package": "scripts/package_skill.py",           # 打包 .zip/.skill
    "check_artifacts": "scripts/check_artifacts.py", # 旧版：产物校验
    "eval": "scripts/run_eval.py",                   # 触发评估（需 claude CLI）
    "improve": "scripts/improve_description.py",     # 描述优化（需 claude CLI）
    "loop": "scripts/run_loop.py",                   # eval+improve 循环
    "loop_report": "scripts/generate_report.py",     # run_loop 输出转 HTML
    "benchmark": "scripts/aggregate_benchmark.py",   # 汇总 grading.json 基准
    "viewer": "eval-viewer/generate_review.py",      # 评审页（支持 --static）
    "agents": "agents",                              # 评审助手（grader/analyzer/comparator）
}


def log(msg: str) -> None:
    print(f"[ensure_dependency] {msg}", file=sys.stderr)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def is_valid_skill_creator(path: Path) -> bool:
    """目录存在 SKILL.md 且 frontmatter name 为 skill-creator。"""
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        return False
    try:
        text = skill_md.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    m = re.search(r"^name:\s*['\"]?skill-creator['\"]?\s*$", text, re.MULTILINE)
    return m is not None


def candidate_paths(workdir: Path) -> list[Path]:
    """搜索顺序：环境变量指定 > 项目级 > 用户级。"""
    cands: list[Path] = []
    env_path = os.environ.get("SKILL_CREATOR_PLUS_DEP_PATH", "").strip()
    if env_path:
        cands.append(Path(env_path).expanduser())
    home = Path.home()
    for base in (
        workdir / ".agents" / "skills",   # 安装点；亦为 npx skills 的 universal 位置
        workdir / ".claude" / "skills",
        home / ".claude" / "skills",
        home / ".agents" / "skills",
    ):
        cands.append(Path(base / "skill-creator"))
    return cands


def locate(workdir: Path) -> tuple[Path, str] | None:
    """返回 (已安装路径, source 描述)；未找到返回 None。"""
    for cand in candidate_paths(workdir):
        if is_valid_skill_creator(cand):
            source = "env" if str(cand) == os.environ.get("SKILL_CREATOR_PLUS_DEP_PATH", "").strip() else "existing"
            return cand.resolve(), source
    return None


def capability_map(dep_root: Path) -> dict:
    """按能力探测脚本是否存在（兼容新旧版本）。"""
    caps = {}
    for cap, rel in CAPABILITY_FILES.items():
        if cap == "agents":
            caps[cap] = (dep_root / rel).is_dir()
        else:
            caps[cap] = (dep_root / rel).is_file()
    return caps


# ---------- 管理标记 ----------

def read_marker(dep: Path) -> dict:
    p = dep / MARKER_NAME
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_marker(dep: Path, repo: str, ref: str, method: str, commit: str | None) -> dict:
    info = {"managed_by": MANAGED_BY, "repo": repo, "ref": ref,
            "method": method, "commit": commit, "installed_at": now_iso()}
    (dep / MARKER_NAME).write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    return info


def marker_age_days(marker: dict) -> int | None:
    """副本安装至今的天数；无法解析返回 None。"""
    ts = marker.get("installed_at")
    if not ts:
        return None
    try:
        t = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - t).days


# ---------- 安装 ----------

def _copy_skill_creator(src_repo: Path, dest: Path) -> None:
    src = src_repo / SUBDIR
    if not src.is_dir():
        raise RuntimeError(f"仓库内未找到 {SUBDIR}（仓库结构可能已变更）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src, dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )


def install_via_git(dest: Path, ref: str, repo_url: str) -> str | None:
    """git 安装；返回 commit SHA（取不到返回 None）。"""
    tmp = Path(tempfile.mkdtemp(prefix="scp-git-"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(tmp / "repo")],
            check=True, capture_output=True, text=True, timeout=300,
        )
        commit = None
        proc = subprocess.run(["git", "-C", str(tmp / "repo"), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            commit = proc.stdout.strip() or None
        _copy_skill_creator(tmp / "repo", dest)
        return commit
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_via_tarball(dest: Path, ref: str, repo_url: str) -> None:
    """无 git 时的纯标准库下载方案（仅支持 GitHub codeload 布局）。"""
    url = f"https://codeload.github.com/anthropics/skills/tar.gz/refs/heads/{ref}"
    if repo_url != REPO_URL:
        raise RuntimeError(f"tarball 降级仅支持官方仓库（--repo={repo_url} 请用 git 方式）")
    req = Request(url, headers={"User-Agent": MANAGED_BY})
    tmp = Path(tempfile.mkdtemp(prefix="scp-tgz-"))
    try:
        with urlopen(req, timeout=180) as resp, open(tmp / "repo.tgz", "wb") as fh:
            shutil.copyfileobj(resp, fh)
        with tarfile.open(tmp / "repo.tgz") as tar:
            tar.extractall(tmp / "repo")  # noqa: S202 — 只解包 GitHub 官方 tarball
        repo_dir = next((tmp / "repo").iterdir())  # skills-<ref>/
        _copy_skill_creator(repo_dir, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_via_skills_cli(dest: Path, workdir: Path, repo_url: str) -> None:
    """最后手段：npx skills add 直装到项目 .agents/（即目标位置；目标不同才复制）。"""
    subprocess.run(
        ["npx", "-y", "skills", "add", repo_url, "--skill", "skill-creator", "-y"],
        check=True, capture_output=True, text=True, timeout=600,
    )
    installed = workdir / ".agents" / "skills" / "skill-creator"
    if not is_valid_skill_creator(installed):
        raise RuntimeError("npx skills add 后未在 .agents/skills/ 下发现 skill-creator")
    if dest.resolve() != installed.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(  # npx 直装目录无仓库布局，直接整目录复制
            installed, dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )


def install(workdir: Path, ref: str, repo_url: str,
            reinstall: bool = False) -> tuple[Path, str, str | None, dict]:
    """安装/重装到 <workdir>/.agents/skills/skill-creator。

    返回 (路径, 方式, commit, 管理标记)。"""
    dest = workdir / ".agents" / "skills" / "skill-creator"
    if dest.exists() and not reinstall:
        if is_valid_skill_creator(dest):
            marker = read_marker(dest) or write_marker(dest, repo_url, ref, "existing", None)
            return dest, "existing", marker.get("commit"), marker
        shutil.rmtree(dest)

    errors = []
    for name, fn in (
        ("git", lambda: install_via_git(dest, ref, repo_url)),
        ("tarball", lambda: install_via_tarball(dest, ref, repo_url)),
        ("skills-cli", lambda: install_via_skills_cli(dest, workdir, repo_url)),
    ):
        try:
            commit = fn()
            if is_valid_skill_creator(dest):
                marker = write_marker(dest, repo_url, ref, name, commit)
                return dest, name, commit, marker
            errors.append(f"{name}: 安装后校验失败")
        except Exception as exc:  # noqa: BLE001 — 逐个降级，需捕获全部异常
            errors.append(f"{name}: {exc}")
    raise RuntimeError("；".join(errors))


def version_info(dep: Path, marker: dict, max_age_days: int) -> dict:
    age = marker_age_days(marker)
    return {
        "managed": marker.get("managed_by") == MANAGED_BY,
        "method": marker.get("method"),
        "commit": marker.get("commit"),
        "installed_at": marker.get("installed_at"),
        "age_days": age,
        "stale": age is not None and age >= max_age_days,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查/安装/更新 anthropics skill-creator 依赖")
    parser.add_argument("--workdir", default=".", help="用户工作目录（默认当前目录）")
    parser.add_argument("--ref", default=DEFAULT_REF, help=f"安装分支/标签（默认 {DEFAULT_REF}）")
    parser.add_argument("--repo", default=None,
                        help="仓库地址（默认官方；可用环境变量 SKILL_CREATOR_PLUS_REPO_URL 指定镜像）")
    parser.add_argument("--update", action="store_true", help="立即强制更新到 --ref 最新")
    parser.add_argument("--no-auto-update", dest="no_auto_update", action="store_true",
                        help="本次跳过自动更新（结果仍报告 stale）")
    parser.add_argument("--max-age-days", dest="max_age_days", type=int,
                        default=DEFAULT_MAX_AGE_DAYS,
                        help=f"自动更新的龄期阈值（默认 {DEFAULT_MAX_AGE_DAYS} 天）")
    parser.add_argument("--reinstall", action="store_true",
                        help="副本已损坏时强制重装（等同修复模式）")
    parser.add_argument("--json", dest="json_out", default=None, help="结果同时写入该 JSON 文件")
    args = parser.parse_args()

    repo_url = args.repo or os.environ.get("SKILL_CREATOR_PLUS_REPO_URL", "").strip() or REPO_URL
    workdir = Path(args.workdir).expanduser().resolve()
    if not workdir.is_dir():
        print(json.dumps({
            "status": "error",
            "error": {"code": "WORKDIR_NOT_FOUND",
                      "message": f"工作目录不存在：{workdir}",
                      "hint": "请用 --workdir 指定有效目录"},
        }, ensure_ascii=False))
        return 2

    result: dict
    code = 0
    try:
        if args.reinstall:
            found = None
        else:
            found = locate(workdir)

        if found:
            dep_root, source = found
            marker = read_marker(dep_root)
            vinfo = version_info(dep_root, marker, args.max_age_days)
            our_install_point = dep_root == (workdir / ".agents" / "skills" / "skill-creator").resolve()
            owned = vinfo["managed"] and our_install_point
            want_update = args.update or (vinfo["stale"] and not args.no_auto_update)

            updated, update_note = False, None
            if want_update:
                if not vinfo["managed"]:
                    update_note = ("非本 skill 管理的副本（无管理标记），已跳过更新；"
                                   "如需接管可删除该副本后重跑本脚本")
                else:
                    try:
                        log("副本过期/强制更新，正在拉取最新版 ...")
                        dep_root, method, commit, marker = install(
                            workdir, args.ref, repo_url, reinstall=True)
                        vinfo = version_info(dep_root, marker, args.max_age_days)
                        updated = True
                    except Exception as exc:  # noqa: BLE001 — 离线/网络失败沿用旧版
                        update_note = f"更新失败（{exc}），沿用旧版继续"
            result = {"status": "ok",
                      "source": "update" if updated else source,
                      "path": str(dep_root)}
            result["version"] = vinfo
            if updated:
                result["updated"] = True
            if update_note:
                result["update_skipped" if "跳过" in update_note else "update_failed"] = update_note
        else:
            log(f"未找到 skill-creator，开始安装到 {workdir}/.agents/skills/ ...")
            dep_root, method, commit, marker = install(workdir, args.ref, repo_url)
            result = {"status": "installed", "source": method, "path": str(dep_root),
                      "installed_at": marker.get("installed_at")}
            result["version"] = version_info(dep_root, marker, args.max_age_days)

        result["capabilities"] = capability_map(Path(result["path"]))
        missing = [cap for cap, ok in result["capabilities"].items() if not ok]
        result["missing_capabilities"] = missing
        result["hint"] = ("能力表缺失项按 references/dependency.md 的降级方案处理"
                          if missing else "官方脚本能力齐全")
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "error": {
                "code": "INSTALL_FAILED",
                "message": f"安装 skill-creator 失败：{exc}",
                "hint": ("检查网络/代理后重试；受限网络可用镜像或代理。"
                         "也可手动把 skill-creator 副本放到任意目录，"
                         "设 SKILL_CREATOR_PLUS_DEP_PATH=<该目录> 后重跑本脚本"),
            },
        }
        code = 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
