#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
zentao-bugfix skill 唯一脚本入口 —— 把所有确定性步骤脚本化，减少 AI 调用次数。

推荐用 uv 隔离运行（零第三方依赖，uv 只做环境隔离）：
    uv run --no-project scripts/bugfix.py <子命令>
无 uv 时可直接：
    python3 scripts/bugfix.py <子命令>

配置文件：<项目工作空间>/.agents/zentao-bugfix/routes.json 的 config 对象（字符串值）：
    ZENTAO_BASE_URL=http://host:port
    ZENTAO_ACCOUNT=xxx
    ZENTAO_PASSWORD=xxx
    FRONTEND_WORKSPACES=D:/path/to/frontend,...
                                                  前端只读分析工作区（可选，逗号分隔）
                                                  仅用于判定前端/后端问题归属，不是修复目标
    WT_INIT_SKILL_ZIP_URL / WT_INIT_SKILLS /
    WT_INIT_PROMPT_REPO / WT_INIT_PROMPT_DIR
                                                  新建 worktree 的 AI 环境初始化来源
                                                  （可选，均有内置默认值，见下方说明）

子命令（一次调用完成尽量多的事情）：
    config-status [--project DIR]                 检查配置，输出 JSON
    save-config KEY=VALUE... [--project DIR]      保存/合并写入 routes.json
    get-bug <bugId> [--project DIR]               拉取禅道 bug（详情+评论+截图）
    worktree <bugId> [baseBranch] [--project DIR] [--reuse]
                                                  创建 bugfix worktree + 同步远端最新
                                                  基准分支（fetch+merge 进 bugfix 分支）
                                                  + 拷贝资料；该 bugId 已有 worktree/
                                                  修复分支时停止（返回码 4），--reuse
                                                  显式复用继续（复用时不同步远端）。
                                                  注意：不查询禅道、不校验 resolution，
                                                  正常流程一律用 prepare
    prepare <bugId> [baseBranch] [--project DIR] [--reuse] [--force]
                                                  查询禅道 + routes.json 分流 +
                                                  绑定工作区加锁或新建 worktree + 生成
                                                  analysis.md / solution.md 骨架
                                                  （报告目录 .agents/zentao-bugfix/
                                                  <bugId>/）
    render-html <bugId> [--project DIR] [--analysis-only]
                                                  从完整 MD 生成/更新同目录 HTML
    ready <bugId> [--project DIR]                绑定模式修复前生成 HTML 并封存分析/方案
    finish <bugId> --check-command CMD --files PATH... [--project DIR]
                                                  验证并独立提交当前 Bug，成功释放锁
    report <bugId> [--project DIR] [--force]      生成 fix-report.md（含未提交
                                                  变更清单）+ 输出汇报摘要；自动定位
                                                  该 bugId 既有 worktree（跨日期）；
                                                  校验 analysis.md / solution.md 完成
                                                  度并输出 ANALYSIS_INCOMPLETE /
                                                  SOLUTION_INCOMPLETE 字段
    download-image <url> <dest> [--cookie SID]    内部使用：下载附件图片

关键策略：
    - 所有 git 操作通过 subprocess 调用系统 git；
    - worktree 的 git 元数据改写为相对路径，WSL git 与 Windows git 均可识别；
    - 绑定模式通过 finish 验证并单 Bug 提交；新 worktree 默认不提交；均不 push；
    - 匹配支持 Bug ID 和标题包含，工作区异常输出并打开 HTML，失败保留现场与锁；
    - 分析先行：analysis.md（完整分析报告）与 solution.md（解决方案）必须在
      实施任何代码修复之前由 AI 补全（prepare 在 <worktree>/.agents/
      zentao-bugfix/<bugId>/ 下生成两份骨架，保证文档目录一定存在）；
      prepare 的 NEXT 提示与 report 的 ANALYSIS_INCOMPLETE / SOLUTION_INCOMPLETE
      字段（no=已完整 / yes=仍有（待填写）章节 / missing=文件不存在）负责校验
      提醒，不硬失败，保持流程可恢复。
    - 幂等防重：同一 bugId 重复 prepare/worktree 时，检测到已有 worktree/修复
      分支（不限日期）即停止并输出 EXISTS 摘要（返回码 4）；--reuse 可显式复用
      既有 worktree 继续处理；report 自动定位既有 worktree。
    - 远端同步：**新建** worktree 后自动 fetch 远端基准分支并合并进 bugfix 分支
      （git fetch <remote> <基准> + git merge <remote>/<基准>，在 worktree 内执行）；
      仓库无远程 / fetch 失败 / 基准非分支 → 警告降级用本地快照并在输出标注
      SYNCED=no；合并冲突 → 自动 git merge --abort 保持 worktree 干净后停止
      （返回码 5，输出 SYNC_CONFLICT 块，人工决策）；不更新本地基准分支引用、
      不碰主工作空间；--reuse 复用时不同步。
    - worktree 环境初始化：**新建** worktree 后自动安装 AI 工作环境再交给修复
      会话——从 GitHub（codeload zip / API + raw）安装指定 skill 到
      <worktree>/.agents/skills/，安装系统提示词模板（AGENTS.md → worktree 根、
      .agents/ 模板 → worktree/.agents/ 合并覆盖）；下载缓存在
      <项目>/.agents/zentao-bugfix/cache/（TTL 24 小时）；任一子步骤失败不阻断
      修复，输出并标注 INIT_STATUS=degraded，报告说明降级原因；--reuse 复用、
      绑定（inplace）模式不初始化。

返回码：0 成功；2 配置/参数错误；3 bug 获取或 worktree 创建失败；
       4 该 bugId 已存在 worktree/修复分支（防重复处理，需人工决策）；
       5 远端基准分支合并失败/冲突（已自动 git merge --abort，worktree 保持
       干净，人工决策后续）；6 分支/工作区占用等待；7 工作区异常 HTML；
       8 分析封存、验证或提交失败，保留锁暂停。
"""
import argparse
import html as html_mod
import datetime
import importlib.util
from pathlib import Path
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import base64
import hashlib
import io
import shutil
import time
import zipfile

_paths_spec = importlib.util.spec_from_file_location("worktree_paths", Path(__file__).with_name("worktree_paths.py"))
_paths = importlib.util.module_from_spec(_paths_spec)
_paths_spec.loader.exec_module(_paths)
_routes_spec = importlib.util.spec_from_file_location("bugfix_routes", Path(__file__).with_name("bugfix_routes.py"))
_routes = importlib.util.module_from_spec(_routes_spec)
_routes_spec.loader.exec_module(_routes)

REQUIRED_KEYS = ["ZENTAO_BASE_URL", "ZENTAO_ACCOUNT", "ZENTAO_PASSWORD"]
TIMEOUT = 30


def log(msg):
    print(msg, file=sys.stderr)


def run_git(args, cwd, check=True, capture=True):
    """执行 git 命令，返回 (rc, stdout, stderr)。"""
    proc = subprocess.run(
        ["git"] + args, cwd=cwd, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        creationflags=0x08000000 if os.name == "nt" else 0,   # CREATE_NO_WINDOW：不弹黑窗
    )
    if check and proc.returncode != 0:
        raise RuntimeError("git %s 失败(%d): %s" % (
            args[:3], proc.returncode, (proc.stderr or "").strip()[:300]))
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ---------------------------------------------------------------- 配置

def load_config(project_dir):
    path = _routes.config_path(project_dir)
    return str(path), _routes.load_config(path)


def save_config(path, updates):
    _routes.save_config(path, updates)


FRONTEND_KEY = "FRONTEND_WORKSPACES"


def frontend_workspaces(cfg, project):
    """前端只读分析工作区（config 的 FRONTEND_WORKSPACES，逗号分隔）。

    仅用于只读定位「前端问题还是后端问题」；不是修复目标，不写入、不暂存、
    不提交、不切分支。路径支持绝对路径、项目相对路径和 Windows/WSL 互转。
    """
    raw = cfg.get(FRONTEND_KEY, "") if isinstance(cfg, dict) else ""
    if not isinstance(raw, str) or not raw.strip():
        return []
    result = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(str(_routes.workspace_path(item, project)))
        except (ValueError, OSError):
            result.append(item)
    return result


# ---------------------------------------------------------------- HTTP / 禅道

def normalize_base_url(url):
    url = url.strip().rstrip("/")
    m = re.match(r"^(https?://[^/]+)", url)
    return m.group(1) if m else url


def build_opener(with_cookie=False):
    if with_cookie:
        cj = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return urllib.request.build_opener()


def http_request(opener, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with opener.open(req, timeout=TIMEOUT) as resp:
        return resp.read()


def http_json(opener, url, data=None, headers=None):
    return json.loads(http_request(opener, url, data, headers).decode("utf-8", "replace"))


def html_to_text(html_str):
    if not html_str:
        return ""
    s = re.sub(r"<img[^>]*src=[\"']([^\"']+)[\"'][^>]*>", r"\n[图片: \1]\n", html_str)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def zentao_token(base_url, account, password):
    payload = json.dumps({"account": account, "password": password}).encode("utf-8")
    data = http_json(build_opener(), base_url + "/api.php/v1/tokens", data=payload,
                     headers={"Content-Type": "application/json"})
    token = data.get("token")
    if not token:
        raise RuntimeError("token 接口未返回 token: %s" % json.dumps(data, ensure_ascii=False)[:300])
    return token


def zentao_session(opener, base_url, account, password):
    d = http_json(opener, base_url + "/api-getsessionid.json")
    sid = None
    if isinstance(d, dict) and d.get("data"):
        raw = d["data"]
        sid = json.loads(raw).get("sessionID") if isinstance(raw, str) else raw.get("sessionID")
    if not sid:
        raise RuntimeError("获取 sessionID 失败")
    form = urllib.parse.urlencode({"account": account, "password": password}).encode("utf-8")
    login = http_json(opener, "%s/user-login.json?zentaosid=%s" % (base_url, sid), data=form)
    if login.get("status") != "success":
        raise RuntimeError("登录失败: %s" % json.dumps(login, ensure_ascii=False)[:300])


def fetch_bug_v1(base_url, account, password, bug_id):
    token = zentao_token(base_url, account, password)
    return http_json(build_opener(), "%s/api.php/v1/bugs/%s" % (base_url, bug_id),
                     headers={"Token": token})


def fetch_bug_classic(opener, base_url, bug_id):
    d = http_json(opener, "%s/bug-view-%s.json" % (base_url, bug_id))
    if d.get("status") != "success":
        return None
    data = d.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    return data


def extract_image_urls(*html_chunks):
    urls, seen = [], set()
    for chunk in html_chunks:
        if not chunk:
            continue
        for m in re.finditer(r"<img[^>]*src=[\"']([^\"']+)[\"']", chunk):
            u = m.group(1)
            if "file-read-" in u and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def download_images(opener, base_url, rel_urls, dest_dir):
    saved = []
    os.makedirs(dest_dir, exist_ok=True)
    for rel in rel_urls:
        base = rel.strip("/").rsplit("/", 1)[-1]
        fname = base if re.match(r"^file-read-\d+\.\w+$", base) else rel.strip("/").replace("/", "_")
        try:
            body = http_request(opener, urllib.parse.urljoin(base_url, rel))
            if (not body[:8].startswith(b"\x89PNG") and body[:3] != b"\xff\xd8\xff"
                    and body[:6] not in (b"GIF87a", b"GIF89a")):
                continue
            with open(os.path.join(dest_dir, fname), "wb") as f:
                f.write(body)
            saved.append((rel, fname))
        except Exception as e:  # noqa: BLE001
            log("[warn] 图片下载失败 %s: %s" % (rel, e))
    return saved


def user_name(u):
    if isinstance(u, dict):
        return u.get("realname") or u.get("account") or "-"
    return str(u or "-")


def render_bug_md(bug, actions, images, base_url, bug_id):
    lines = []
    lines.append("# 禅道 BUG #%s" % bug_id)
    lines.append("")
    lines.append("- **标题**: %s" % (bug.get("title") or "-"))
    lines.append("- **状态**: %s    **严重程度**: %s    **优先级**: %s    **类型**: %s"
                 % (bug.get("status") or "-", bug.get("severity") or "-",
                    bug.get("pri") or "-", bug.get("type") or "-"))
    lines.append("- **创建人**: %s    **创建时间**: %s" % (user_name(bug.get("openedBy")), bug.get("openedDate") or "-"))
    lines.append("- **指派给**: %s    **指派时间**: %s" % (user_name(bug.get("assignedTo")), bug.get("assignedDate") or "-"))
    if bug.get("resolvedBy") or bug.get("resolution"):
        lines.append("- **解决人**: %s    **解决方案（Resolution）**: %s    **解决时间**: %s"
                     % (user_name(bug.get("resolvedBy")), bug.get("resolution") or "-", bug.get("resolvedDate") or "-"))
    lines.append("- **所属产品ID**: %s    **所属项目ID**: %s    **模块ID**: %s"
                 % (bug.get("product") or "-", bug.get("project") or "-", bug.get("module") or "-"))
    lines.append("- **Bug 链接**: %s/bug-view-%s.html" % (base_url, bug_id))
    lines.append("")
    lines.append("## 重现步骤")
    lines.append("")
    steps = html_to_text(bug.get("steps") or "")
    lines.append(steps if steps else "（无）")
    lines.append("")
    if actions:
        lines.append("## 评论 / 操作历史")
        lines.append("")
        for a in actions:
            comment = html_to_text(a.get("comment") or "")
            if comment:
                lines.append("**%s（%s，%s）**：" % (user_name(a.get("actor")), a.get("action") or "", a.get("date") or ""))
                lines.append("")
                lines.append(comment)
                lines.append("")
    if images:
        lines.append("## 附件图片")
        lines.append("")
        for rel, fname in images:
            lines.append("- `%s`（原始地址: %s）" % (fname, urllib.parse.urljoin(base_url, rel)))
        lines.append("")
    return "\n".join(lines)


def resolution_state(bug):
    """禅道 resolution（解决方案）状态：unset=可处理；set=已有解决方案；unknown=失败关闭。

    空字符串和 null 表示未设置；字段缺失或类型异常一律视为 unknown，不放行。
    """
    if not isinstance(bug, dict) or "resolution" not in bug:
        return "unknown"
    value = bug.get("resolution")
    if value is None:
        return "unset"
    if isinstance(value, str):
        return "set" if value.strip() else "unset"
    if type(value) is int and value == 0:
        return "unset"
    return "unknown"


class ResolutionStop(RuntimeError):
    def __init__(self, state):
        super().__init__("Bug 已有解决方案（Resolution 有值）" if state == "set"
                         else "resolution 字段缺失或类型未知")
        self.state = state


def fetch_bug_full(project_dir, bug_id, out_dir=None, skip_resolved=False):
    """拉取禅道 bug 全量数据，返回 (bug, actions, images, work_dir, base_url, md_text)。"""
    config_path, cfg = load_config(project_dir)
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        log("ERROR: 配置不完整，缺少 %s，请先补充保存到 %s" % (", ".join(missing), config_path))
        sys.exit(2)
    base_url = normalize_base_url(cfg["ZENTAO_BASE_URL"])
    account, password = cfg["ZENTAO_ACCOUNT"], cfg["ZENTAO_PASSWORD"]

    bug = None
    try:
        bug = fetch_bug_v1(base_url, account, password, bug_id)
    except Exception as e:  # noqa: BLE001
        log("[warn] REST v1 获取失败，降级经典 API: %s" % e)

    opener = build_opener(with_cookie=True)
    actions, classic = [], None
    try:
        zentao_session(opener, base_url, account, password)
        classic = fetch_bug_classic(opener, base_url, bug_id)
    except Exception as e:  # noqa: BLE001
        log("[warn] 经典 API（评论/操作历史）获取失败: %s" % e)

    if bug is None:
        if classic and classic.get("bug"):
            bug = classic["bug"]
        else:
            log("ERROR: 无法获取 bug #%s（v1 与经典 API 均失败）" % bug_id)
            sys.exit(3)
    if bug.get("id") in (None, ""):
        bug["id"] = bug_id
    if classic:
        acts = classic.get("actions") or []
        if isinstance(acts, dict):
            acts = [v for k, v in sorted(acts.items()) if k.isdigit()]
        actions = [a for a in acts if isinstance(a, dict)]
        actions.sort(key=lambda a: str(a.get("date") or ""))

    if skip_resolved:
        state = resolution_state(bug)
        if state != "unset":
            raise ResolutionStop(state)
    html_chunks = [bug.get("steps") or ""] + [a.get("comment") or "" for a in actions]
    rel_urls = extract_image_urls(*html_chunks)
    work_dir = os.path.abspath(out_dir or os.path.join(project_dir, ".agents", "bugfix-work", bug_id))
    images = []
    if rel_urls:
        if not classic:
            try:
                zentao_session(opener, base_url, account, password)
            except Exception as e:  # noqa: BLE001
                log("[warn] 建立图片下载会话失败: %s" % e)
        images = download_images(opener, base_url, rel_urls, work_dir)

    os.makedirs(work_dir, exist_ok=True)
    with open(os.path.join(work_dir, "bug-raw.json"), "w", encoding="utf-8") as f:
        json.dump({"bug": bug, "actions": actions,
                   "images": [{"url": u, "file": fn} for u, fn in images]}, f, ensure_ascii=False, indent=2)
    md = render_bug_md(bug, actions, images, base_url, bug_id)
    with open(os.path.join(work_dir, "bug.md"), "w", encoding="utf-8") as f:
        f.write(md)
    return bug, actions, images, work_dir, base_url, md


# ---------------------------------------------------------------- worktree

def resolve_repo(project_dir):
    rc, out, err = run_git(["rev-parse", "--show-toplevel"], project_dir, check=False)
    if rc != 0:
        log("ERROR: %s 不是 git 仓库" % project_dir)
        sys.exit(2)
    return out.strip()


def require_bug_id(bug_id):
    """bugId 必须为纯数字，防止误建 worktree/分支。"""
    if not re.fullmatch(r"\d+", str(bug_id)):
        log("ERROR: bugId 必须为数字，收到: '%s'" % bug_id)
        sys.exit(2)


def worktree_info(project_dir, bug_id, base_branch_arg=None):
    """计算 worktree 相关路径/分支信息，不执行创建。"""
    require_bug_id(bug_id)
    repo_root = resolve_repo(project_dir)
    parent_dir = os.path.dirname(repo_root)
    cur_branch = ""
    rc, out, _ = run_git(["branch", "--show-current"], repo_root, check=False)
    cur_branch = out.strip()
    base_branch = base_branch_arg or cur_branch or "HEAD"
    rc, _, _ = run_git(["rev-parse", "--verify", "--quiet", "%s^{commit}" % base_branch],
                       repo_root, check=False)
    if rc != 0:
        log("ERROR: 基准分支不存在: %s" % base_branch)
        sys.exit(2)
    rc, out, _ = run_git(["rev-parse", "--short", "HEAD"], repo_root, check=False)
    head_short = out.strip()
    date = datetime.date.today().strftime("%Y%m%d")
    branch = "bugfix/%s_%s" % (bug_id, date)
    dir_name = branch.replace("/", "_")
    wt_path = os.path.join(parent_dir, dir_name)
    return {
        "repo_root": repo_root, "parent_dir": parent_dir, "base_branch": base_branch,
        "cur_branch": cur_branch, "head_short": head_short, "date": date,
        "branch": branch, "dir_name": dir_name, "wt_path": wt_path,
        "report_dir": report_dir_for(wt_path, bug_id),
    }


def report_dir_for(wt_path, bug_id):
    """报告目录：<worktree>/.agents/zentao-bugfix/<bugId>/（v1.6+ 布局）。"""
    return os.path.join(wt_path, ".agents", "zentao-bugfix", str(bug_id))


def resolve_report_dir(wt_path, bug_id):
    """读取/复用时的报告目录：新版 zentao-bugfix 目录；旧 worktree 回退 .agents/bugfix/<id>。"""
    new = report_dir_for(wt_path, bug_id)
    legacy = os.path.join(wt_path, ".agents", "bugfix", str(bug_id))
    if os.path.isdir(new) or not os.path.isdir(legacy):
        return new
    return legacy


def find_existing_worktrees(project_dir, bug_id):
    """扫描该 bugId 已有的 worktree / 遗留目录 / 遗留分支（跨日期，任意 bugfix/<id>_*）。

    返回 {"repo_root", "worktrees": [(path, branch)], "dirs": [path], "branches": [branch]}：
    - worktrees：git 已注册、目录名匹配 bugfix_<id>[_YYYYMMDD] 的 worktree；
    - dirs：仓库同级目录下匹配命名但未注册为 worktree 的残留目录；
    - branches：匹配 bugfix/<id>[_YYYYMMDD] 但没有对应 worktree 的遗留分支。
    """
    require_bug_id(bug_id)
    repo_root = resolve_repo(project_dir)
    id_s = str(bug_id)
    dir_pat = re.compile(r"^bugfix_%s(_\d{8})?$" % re.escape(id_s))
    branch_pat = re.compile(r"^bugfix/%s(_\d{8})?$" % re.escape(id_s))

    worktrees, wt_branches = [], set()

    def _take(path, branch):
        if dir_pat.match(os.path.basename(path.rstrip("/"))) and path.rstrip("/") != repo_root:
            worktrees.append((path.rstrip("/"), branch))
            if branch:
                wt_branches.add(branch)

    _, porcelain, _ = run_git(["worktree", "list", "--porcelain"], repo_root)
    cur_path, cur_branch = None, ""
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            if cur_path:
                _take(cur_path, cur_branch)
            cur_path = line.split(None, 1)[1].strip()
            cur_branch = ""
        elif line.startswith("branch ") and cur_path:
            ref = line.split(None, 1)[1].strip()
            cur_branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ""
    if cur_path:
        _take(cur_path, cur_branch)

    branches = []
    rc, out, _ = run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads/"],
                         repo_root, check=False)
    if rc == 0:
        for b in out.splitlines():
            b = b.strip()
            if b and branch_pat.match(b) and b not in wt_branches:
                branches.append(b)

    dirs = []
    parent_dir = os.path.dirname(repo_root)
    known = {os.path.abspath(p) for p, _ in worktrees}
    if os.path.isdir(parent_dir):
        for name in sorted(os.listdir(parent_dir)):
            full = os.path.join(parent_dir, name)
            if dir_pat.match(name) and os.path.isdir(full) and os.path.abspath(full) not in known:
                dirs.append(full)
    return {"repo_root": repo_root, "worktrees": worktrees, "dirs": dirs, "branches": branches}


def check_existing(project_dir, bug_id, reuse=False):
    """幂等防重检查：该 bugId 已有 worktree/遗留目录/遗留分支时停止执行（返回码 4）。

    - 未指定 reuse：stdout 输出 EXISTS 摘要块后 exit(4)——说明该 bug 已创建过
      修复工作区（可能已修复待人工 review，或仍在处理中），不应重复处理；
    - 指定 reuse 且存在可用 worktree：返回 (path, branch) 供复用继续处理；
    - 无任何遗留：返回 None。
    """
    found = find_existing_worktrees(project_dir, bug_id)
    worktrees = sorted(found["worktrees"], key=lambda wb: os.path.basename(wb[0]))
    dirs, branches = sorted(found["dirs"]), sorted(found["branches"])
    if not worktrees and not dirs and not branches:
        return None

    def summary():
        print("EXISTS")
        print("BUG_ID=%s" % bug_id)
        if worktrees:
            wt_path, wt_branch = worktrees[-1]
            print("EXISTING_WORKTREE=%s" % wt_path)
            print("EXISTING_WORKTREE_WIN=%s" % wt_win_path(wt_path))
            if wt_branch:
                print("EXISTING_BRANCH=%s" % wt_branch)
            print("EXISTING_REPORT_DIR=%s" % resolve_report_dir(wt_path, bug_id))
        for wt, _ in worktrees[:-1]:
            print("EXTRA_WORKTREE=%s" % wt)
        for d in dirs:
            print("EXTRA_DIR=%s" % d)
        for b in branches:
            print("EXTRA_BRANCH=%s" % b)
        print("ACTION=stop（该 bugId 已有修复工作区，不重复处理）")

    if not reuse:
        summary()
        log("")
        if worktrees:
            log("ERROR: bug #%s 已存在修复 worktree: %s" % (bug_id, worktrees[-1][0]))
            log("该 bug 已创建过修复工作区——可能已修复待人工 review，或仍在处理中；为避免重复处理，停止执行。")
            log("查看既有结果: %s 下的 analysis.md / solution.md / fix-report.md"
                % resolve_report_dir(worktrees[-1][0], bug_id))
            log("继续该工作区: 加 --reuse 重新运行；彻底重来: 先人工清理"
                "（git worktree remove <path>，必要时 git branch -D <分支>）后重试。")
        else:
            log("ERROR: bug #%s 存在遗留修复痕迹（无可用 worktree），请先人工清理后重试:" % bug_id)
            for d in dirs:
                log("  残留目录: %s（未注册为 worktree）" % d)
            for b in branches:
                log("  遗留分支: %s（删除: git branch -D %s）" % (b, b))
        sys.exit(4)

    if not worktrees:
        summary()
        log("")
        log("ERROR: bug #%s 仅有遗留目录/分支、无已注册 worktree，无法复用；请人工清理后重试。" % bug_id)
        sys.exit(4)
    for d in dirs:
        log("[warn] 忽略未注册残留目录: %s" % d)
    for b in branches:
        log("[warn] 忽略遗留分支: %s" % b)
    for wt, _ in worktrees[:-1]:
        log("[warn] 忽略多余 worktree: %s（请人工确认清理）" % wt)
    return worktrees[-1]


def load_meta(report_dir):
    """读取 worktree 创建时写入的 meta.json（分支/基准分支/日期）。"""
    p = os.path.join(report_dir, "meta.json")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict):
                return m
        except (OSError, ValueError):
            pass
    return None


def info_from_worktree(project_dir, bug_id, wt_path, wt_branch=""):
    """基于已存在的 worktree 重建 info dict（日期/分支取实际值，基准分支优先读 meta.json）。"""
    repo_root = resolve_repo(project_dir)
    wt_path = wt_path.rstrip("/")
    branch = wt_branch or ""
    if not branch:
        rc, out, _ = run_git(["branch", "--show-current"], wt_path, check=False)
        if rc == 0:
            branch = out.strip()
    dir_name = os.path.basename(wt_path)
    date = ""
    m = re.search(r"_(\d{8})$", branch) or re.search(r"_(\d{8})$", dir_name)
    if m:
        date = m.group(1)
    if not date:
        date = subprocess.run(["date", "+%Y%m%d"], text=True,
                              stdout=subprocess.PIPE,
                              creationflags=0x08000000 if os.name == "nt" else 0).stdout.strip()
    report_dir = resolve_report_dir(wt_path, bug_id)
    base_branch = ""
    meta = load_meta(report_dir)
    if meta:
        base_branch = meta.get("base_branch") or ""
    if not base_branch:  # 兼容旧版未写 meta 的 worktree：从 analysis.md 解析分析基线
        am = os.path.join(report_dir, "analysis.md")
        if os.path.isfile(am):
            try:
                with open(am, encoding="utf-8") as f:
                    mm = re.search(r"分析基线\**: 分支 `([^`]+)`", f.read())
                if mm:
                    base_branch = mm.group(1).strip()
            except OSError:
                pass
    if not base_branch:
        rc, out, _ = run_git(["branch", "--show-current"], repo_root, check=False)
        base_branch = out.strip() or "HEAD"
    head_short = ""
    rc, out, _ = run_git(["rev-parse", "--short", "%s^{commit}" % base_branch],
                         repo_root, check=False)
    if rc == 0:
        head_short = out.strip()
    result = {
        "repo_root": repo_root, "parent_dir": os.path.dirname(repo_root),
        "base_branch": base_branch, "cur_branch": "", "head_short": head_short,
        "date": date, "branch": branch, "dir_name": dir_name,
        "wt_path": wt_path, "report_dir": report_dir, "reused": True,
    }
    # 还原创建时的远端同步状态（旧版 meta 无此字段则缺省，报告标注未记录）
    if meta:
        for k in ("synced", "sync_reason", "sync_remote_branch"):
            if meta.get(k) is not None:
                result[k] = meta[k]
    return result


def pick_remote(repo_root):
    """返回优先使用的远程名：优先 origin，否则第一个已配置远程；无远程返回 None。"""
    _, out, _ = run_git(["remote"], repo_root, check=False)
    remotes = [l.strip() for l in out.splitlines() if l.strip()]
    if not remotes:
        return None
    return "origin" if "origin" in remotes else remotes[0]


def sync_base_branch(info, bug_id):
    """新建 worktree 后同步远端最新基准分支：fetch 远端基准并合并进 bugfix 分支。

    策略（与 SKILL.md 约定一致）：
    - 基准非分支（detached HEAD）、仓库无远程、fetch 失败、远端无该分支 →
      警告降级：基于本地快照继续，返回 synced=False（输出标注 SYNCED=no）；
    - 合并失败/冲突 → 自动 git merge --abort 保持 worktree 干净，
      输出 SYNC_CONFLICT 块后 sys.exit(5)，由人工决策后续；
    - 成功（含 Already up to date）→ synced=True，返回合并后 HEAD 短 hash；
    - 只在 worktree 分支上合并，不更新本地基准分支引用、不碰主工作空间。

    返回 {"synced", "sync_reason", "sync_remote_branch", "base_commit"}。
    """
    repo_root, wt_path = info["repo_root"], info["wt_path"]
    base = info["base_branch"]

    def _result(synced, reason, remote_branch="", commit=""):
        return {"synced": synced, "sync_reason": reason,
                "sync_remote_branch": remote_branch, "base_commit": commit}

    def _degrade(reason, remote_branch=""):
        log("[warn] 未同步远端: %s" % reason)
        return _result(False, reason, remote_branch)

    if base == "HEAD":
        return _degrade("基准不是分支（detached HEAD/无当前分支），跳过远端同步")

    remote = pick_remote(repo_root)
    if not remote:
        return _degrade("仓库未配置远程（git remote 为空）")

    # 基准本身是远程跟踪形式（如 origin/dev）时直接使用，否则拼 <remote>/<基准>
    if "/" in base and base.split("/", 1)[0] == remote:
        remote_branch = base
        fetch_branch = base.split("/", 1)[1]
    else:
        remote_branch = "%s/%s" % (remote, base)
        fetch_branch = base

    rc, _, err = run_git(["fetch", remote, fetch_branch], repo_root, check=False)
    if rc != 0:
        first = (err.strip().splitlines() or [""])[0][:120]
        return _degrade("fetch %s %s 失败（%s），远端无该分支或网络不通" % (
            remote, fetch_branch, first), remote_branch)

    rc, _, _ = run_git(["rev-parse", "--verify", "--quiet",
                        "refs/remotes/%s" % remote_branch], repo_root, check=False)
    if rc != 0:
        return _degrade("未找到远端跟踪分支 %s（fetch 未更新该引用）" % remote_branch,
                        remote_branch)

    # 在 worktree 内合并远端基准；失败（含冲突）→ 安全中止并停止（返回码 5）
    rc, out, err = run_git(["merge", remote_branch], wt_path, check=False)
    if rc != 0:
        abort_rc, _, _ = run_git(["merge", "--abort"], wt_path, check=False)
        detail = ((err or "").strip() or (out or "").strip()).splitlines()
        detail = detail[0][:200] if detail else "未知原因"
        print("SYNC_CONFLICT")
        print("BUG_ID=%s" % bug_id)
        print("BRANCH=%s" % info["branch"])
        print("WORKTREE=%s" % wt_path)
        print("WORKTREE_WIN=%s" % wt_win_path(wt_path))
        print("REMOTE_BRANCH=%s" % remote_branch)
        print("MERGE_ABORTED=%s" % ("yes" if abort_rc == 0 else "no"))
        print("ACTION=stop（合并失败已自动 git merge --abort，worktree 保持干净；人工决策后继续）")
        log("")
        log("ERROR: 同步远端基准分支失败——合并 %s 到 %s 报错: %s" % (
            remote_branch, info["branch"], detail))
        log("原因: 远端基准分支与本地基准分支存在分叉，无法自动合并。")
        log("后续二选一:")
        log("  1. 手动解决: cd %s && git merge %s，解决冲突后继续修复流程（report %s）" % (
            wt_path, remote_branch, bug_id))
        log("  2. 清理重建: git worktree remove %s && git branch -D %s，"
            "先在本地基准分支手动同步远端后重新 prepare" % (wt_path, info["branch"]))
        sys.exit(5)

    _, head, _ = run_git(["rev-parse", "--short", "HEAD"], wt_path, check=False)
    head = head.strip()
    if "Already up to date" in (out or ""):
        reason = "本地基准已含远端最新代码（%s 无新提交）" % remote_branch
    else:
        reason = "已合并 %s 到 %s（HEAD=%s）" % (remote_branch, info["branch"], head)
    log("[ok] 远端同步: %s" % reason)
    return _result(True, reason, remote_branch, head)


# ---------------------------------------------------------------- worktree 环境初始化

WT_INIT_DEFAULTS = {
    "SKILL_ZIP_URL": "https://codeload.github.com/AI-Redfish/skill/zip/refs/heads/main",
    "SKILLS": "skill-creator-plus",
    "PROMPT_REPO": "AI-Redfish/Agent",
    "PROMPT_DIR": "04.Agent开发/04.记忆与自进化/02.提示词案例",
}
WT_INIT_CACHE_TTL = 24 * 3600
WT_INIT_HTTP_TIMEOUT = 60
WT_INIT_ZIP_TIMEOUT = 600


def _wt_init_cfg(cfg, key):
    value = (cfg or {}).get("WT_INIT_" + key) or WT_INIT_DEFAULTS[key]
    return str(value).strip()


def _wt_init_cache_path(project_dir, name):
    d = os.path.join(os.path.abspath(project_dir), ".agents", "zentao-bugfix",
                     "cache", "wt-init")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def _wt_init_fetch(url, timeout):
    # 绕过系统代理直连（本机代理对 GitHub 不可用时 urllib 会逐请求挂到超时）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        url, headers={"User-Agent": "zentao-bugfix-worktree-init/1.0"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def _wt_init_cached_bytes(project_dir, key, url, ttl, timeout):
    """带 TTL 的下载缓存：命中且校验责任在调用方（zip 由调用方再验证）。"""
    path = _wt_init_cache_path(project_dir, key)
    if os.path.isfile(path) and time.time() - os.path.getmtime(path) < ttl:
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            pass
    data = _wt_init_fetch(url, timeout)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return data


def _wt_init_skill_zip_bytes(project_dir, zip_url):
    """取 skill 仓库 zip 字节：缓存 24h；缓存损坏时删除后强制重下一次。"""
    for attempt in range(2):
        data = _wt_init_cached_bytes(project_dir, "skill-main.zip", zip_url,
                                     WT_INIT_CACHE_TTL, WT_INIT_ZIP_TIMEOUT)
        try:
            zipfile.ZipFile(io.BytesIO(data))
            return data
        except Exception:
            if attempt:
                raise
            path = _wt_init_cache_path(project_dir, "skill-main.zip")
            if os.path.isfile(path):
                os.remove(path)
            log("[wt-init] 缓存 zip 无效，已删除并重新下载")
    raise RuntimeError("skill 仓库 zip 下载失败")


def _wt_init_extract_skills(zip_bytes, wt_path, skills):
    """从仓库 zip 解出指定 skill 目录到 <worktree>/.agents/skills/（覆盖安装）。"""
    installed, failed = [], []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("skill 仓库 zip 为空")
        prefix_root = names[0].split("/")[0] + "/skills/"
        for name in skills:
            members = [n for n in names
                       if n.startswith(prefix_root + name + "/") and not n.endswith("/")]
            if not members:
                failed.append("%s(zip中不存在)" % name)
                continue
            target = os.path.join(wt_path, ".agents", "skills", name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            base_len = len(prefix_root + name + "/")
            for m in members:
                dest = os.path.join(target, *m[base_len:].split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(m) as src:
                    with open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
            installed.append(name)
    return installed, failed


def _wt_init_walk_prompts(project_dir, repo, root_dir):
    """递归列出提示词案例目录条目（[{path,dir}...]），整树结果缓存 24h。"""
    tree_path = _wt_init_cache_path(project_dir, "prompt-tree.json")
    if os.path.isfile(tree_path) and time.time() - os.path.getmtime(tree_path) < WT_INIT_CACHE_TTL:
        try:
            with open(tree_path, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("root") == root_dir:
                return cached["entries"]
        except (OSError, ValueError):
            pass
    entries, queue = [], [root_dir]
    while queue:
        current = queue.pop(0)
        url = "https://api.github.com/repos/%s/contents/%s?ref=main" % (
            repo, urllib.parse.quote(current, safe="/"))
        items = json.loads(_wt_init_fetch(url, WT_INIT_HTTP_TIMEOUT).decode("utf-8"))
        if not isinstance(items, list):
            raise ValueError("GitHub API 返回异常: %s" % str(items)[:120])
        for item in items:
            is_dir = item.get("type") == "dir"
            if is_dir:
                queue.append(item["path"])
            entries.append({"path": item["path"], "dir": is_dir})
    tmp = tree_path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"root": root_dir, "entries": entries}, f, ensure_ascii=False)
    os.replace(tmp, tree_path)
    return entries


def _wt_init_install_prompts(project_dir, wt_path, repo, root_dir):
    """安装提示词模板：AGENTS.md → worktree 根；其余按相对路径并入 worktree
    （即 .agents/ 模板进入 worktree/.agents/）。同名文件覆盖，已有其他内容保留。"""
    raw_base = "https://raw.githubusercontent.com/%s/main/" % repo
    installed, failed = [], []
    for entry in _wt_init_walk_prompts(project_dir, repo, root_dir):
        path = entry["path"]
        if entry["dir"] or not path.startswith(root_dir + "/"):
            continue
        rel = path[len(root_dir) + 1:].replace("\\", "/")
        key = hashlib.sha1(rel.encode("utf-8")).hexdigest() + ".bin"
        try:
            data = _wt_init_cached_bytes(
                project_dir, key, raw_base + urllib.parse.quote(path, safe="/"),
                WT_INIT_CACHE_TTL, WT_INIT_HTTP_TIMEOUT)
        except Exception as raw_exc:
            # raw 域名 DNS 抖动/污染时回退 GitHub API（base64 内容）
            try:
                url = "https://api.github.com/repos/%s/contents/%s?ref=main" % (
                    repo, urllib.parse.quote(path, safe="/"))
                payload = json.loads(
                    _wt_init_fetch(url, WT_INIT_HTTP_TIMEOUT).decode("utf-8"))
                data = base64.b64decode(payload.get("content") or "")
            except Exception as api_exc:
                failed.append("%s(%s / api:%s)"
                              % (rel, str(raw_exc)[:60], str(api_exc)[:60]))
                continue
            try:  # 回退成功的结果同样写入缓存，后续运行免网络
                cached = _wt_init_cache_path(project_dir, key)
                tmp = cached + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, cached)
            except OSError:
                pass
        dest = os.path.join(wt_path, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        installed.append(rel)
    return installed, failed


def init_worktree_env(wt_path, project_dir):
    """新建 worktree 后初始化 AI 工作环境（skill + 系统提示词模板）。

    任一子步骤失败不阻断修复（降级继续），错误汇总进返回值，由调用方
    写入输出与报告；全失败/部分失败 status 均为 degraded。
    """
    result = {"status": "ok", "skills": [], "skills_failed": [],
              "prompt_files": 0, "prompt_failed": [], "errors": []}
    try:
        _, cfg = load_config(project_dir)
    except Exception:
        cfg = {}
    try:
        skills = [s.strip() for s in _wt_init_cfg(cfg, "SKILLS").split(",") if s.strip()]
        zip_bytes = _wt_init_skill_zip_bytes(project_dir, _wt_init_cfg(cfg, "SKILL_ZIP_URL"))
        result["skills"], result["skills_failed"] = _wt_init_extract_skills(
            zip_bytes, wt_path, skills)
    except Exception as exc:
        result["errors"].append("skills: %s" % str(exc)[:160])
    try:
        installed, failed = _wt_init_install_prompts(
            project_dir, wt_path, _wt_init_cfg(cfg, "PROMPT_REPO"),
            _wt_init_cfg(cfg, "PROMPT_DIR"))
        result["prompt_files"] = len(installed)
        result["prompt_failed"] = failed
    except Exception as exc:
        result["errors"].append("prompts: %s" % str(exc)[:160])
    if result["errors"] or result["skills_failed"] or result["prompt_failed"]:
        result["status"] = "degraded"
    return result


def setup_worktree(project_dir, bug_id, base_branch_arg=None, reuse_target=None):
    """创建/复用 worktree，返回 info dict。

    - reuse_target（由 check_existing 在 --reuse 时返回）：复用指定 worktree，
      不创建、不改写 git 元数据、不同步远端（保持原样继续）；
    - 否则新建今日 worktree（目录/分支冲突已由 check_existing 前置拦截），
      并在创建后同步远端最新基准分支（fetch + merge，见 sync_base_branch）。
    """
    if reuse_target:
        info = info_from_worktree(project_dir, bug_id, reuse_target[0], reuse_target[1])
        log("[info] 复用已存在 worktree: %s" % info["wt_path"])
    else:
        info = worktree_info(project_dir, bug_id, base_branch_arg)
        repo_root, wt_path = info["repo_root"], info["wt_path"]
        os.makedirs(info["parent_dir"], exist_ok=True)
        try:
            run_git(["worktree", "add", "-b", info["branch"], wt_path, info["base_branch"]],
                    repo_root, capture=False)
        except RuntimeError as e:
            log("ERROR: 创建 worktree 失败: %s" % e)
            sys.exit(3)

        # 查询真实管理目录，兼容嵌套worktree和Git自动追加的管理目录后缀。
        try:
            info["compatibility"] = _paths.repair_worktree(wt_path)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            log("ERROR: worktree跨平台验证失败，保留工作区和分支: %s" % exc)
            sys.exit(3)

    if reuse_target:
        # 复用只验证，不自动改写用户已有worktree元数据。
        try:
            info["compatibility"] = _paths.check_worktree(info["wt_path"])
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            log("ERROR: 复用worktree跨平台验证失败，请显式修复: %s" % exc)
            sys.exit(3)

    rc, _, _ = run_git(["rev-parse", "--git-dir"], info["wt_path"], check=False)
    if rc != 0:
        log("ERROR: worktree 不可用: %s（请人工修复或删除后重试）" % info["wt_path"])
        sys.exit(3)

    # 同步远端最新基准分支（仅新建时执行；--reuse 复用不改动代码）
    if not reuse_target:
        sync = sync_base_branch(info, bug_id)
        info["synced"] = sync["synced"]
        info["sync_reason"] = sync["sync_reason"]
        info["sync_remote_branch"] = sync["sync_remote_branch"]
        if sync.get("base_commit"):
            info["head_short"] = sync["base_commit"]

        # 初始化 worktree AI 环境（skill + 系统提示词模板）；失败降级继续，报告标注
        init = init_worktree_env(info["wt_path"], project_dir)
        info["wt_init"] = init
        if init["status"] == "ok":
            log("[wt-init] 环境初始化完成: skills=%s 提示词文件=%d"
                % (",".join(init["skills"]), init["prompt_files"]))
        else:
            log("[wt-init][warn] 环境初始化降级（不阻断修复，报告需标注）: %s"
                % json.dumps({k: init[k] for k in
                              ("skills_failed", "prompt_failed", "errors")},
                             ensure_ascii=False))

    # 拷贝 bug 资料
    report_dir = info["report_dir"]
    os.makedirs(report_dir, exist_ok=True)
    src_dir = os.path.join(os.path.abspath(project_dir), ".agents", "bugfix-work", str(bug_id))
    if os.path.isdir(src_dir):
        for name in os.listdir(src_dir):
            src = os.path.join(src_dir, name)
            if os.path.isfile(src):
                try:
                    with open(src, "rb") as f:
                        data = f.read()
                    with open(os.path.join(report_dir, name), "wb") as f:
                        f.write(data)
                except OSError as e:
                    log("[warn] 拷贝 %s 失败: %s" % (name, e))

    # 记录创建元数据（report 与后续复用据此还原实际分支/基准/日期/同步状态）
    meta_path = os.path.join(report_dir, "meta.json")
    if not os.path.isfile(meta_path):
        meta = {"bug_id": str(bug_id), "branch": info["branch"],
                "base_branch": info["base_branch"], "date": info["date"],
                "wt_path": info["wt_path"], "repo_root": info["repo_root"]}
        for k in ("synced", "sync_reason", "sync_remote_branch", "compatibility",
                  "wt_init"):
            if k in info:
                meta[k] = info[k]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    return info


def wt_win_path(path):
    try:
        out = subprocess.run(["wslpath", "-w", path], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except FileNotFoundError:
        pass
    return path


def sync_status_text(info):
    """渲染分析基线的远端同步状态说明（analysis/fix-report/汇报共用）。"""
    if info.get("synced") is True:
        return "已同步远端 `%s`（基线提交 `%s`）" % (
            info.get("sync_remote_branch") or "-", info.get("head_short") or "HEAD")
    if info.get("synced") is False:
        return "未同步远端（%s），基于本地快照分析" % (info.get("sync_reason") or "原因未记录")
    return "未记录（旧版 worktree 或 --reuse 复用，未记录同步信息）"


def print_kv(info, extra=None):
    lines = ["OK",
             "PROJECT=%s" % os.path.abspath(info.get("project", ".")),
             "REPO=%s" % info["repo_root"],
             "BASE_BRANCH=%s" % info["base_branch"],
             "BASE_COMMIT=%s" % (info.get("head_short") or ""),
             "BRANCH=%s" % info["branch"],
             "WORKTREE=%s" % info["wt_path"],
             "WORKTREE_WIN=%s" % wt_win_path(info["wt_path"]),
             "REPORT_DIR=%s" % info["report_dir"]]
    if "synced" in info and not info.get("reused"):   # 复用时不输出，避免误读为“刚同步”
        lines.append("SYNCED=%s" % ("yes" if info["synced"] else "no"))
        if info.get("sync_remote_branch"):
            lines.append("SYNC_REMOTE_BRANCH=%s" % info["sync_remote_branch"])
        if info.get("synced") is False and info.get("sync_reason"):
            lines.append("SYNC_REASON=%s" % info["sync_reason"])
    if info.get("reused"):
        lines.append("REUSED=yes")
    if info.get("wt_init"):
        init = info["wt_init"]
        lines.append("INIT_STATUS=%s" % init["status"])
        if init.get("skills"):
            lines.append("INIT_SKILLS=%s" % ",".join(init["skills"]))
        if init.get("skills_failed"):
            lines.append("INIT_SKILLS_FAILED=%s" % ",".join(init["skills_failed"]))
        lines.append("INIT_PROMPT_FILES=%d" % init.get("prompt_files", 0))
        if init.get("prompt_failed"):
            lines.append("INIT_PROMPT_FAILED=%s" % ",".join(init["prompt_failed"]))
        if init.get("errors"):
            lines.append("INIT_ERRORS=%s" % "; ".join(init["errors"])[:300])
    if info.get("frontend_workspaces"):
        lines.append("FRONTEND_WORKSPACES=%s" % ",".join(info["frontend_workspaces"]))
    if extra:
        lines.extend(extra)
    for l in lines:
        print(l)


# ---------------------------------------------------------------- 报告骨架

def scaffold_analysis(bug, actions, images, info, base_url, bug_id, force=False):
    """生成 analysis.md 骨架：机械字段自动填好，分析性章节留待填写。存在即跳过。"""
    path = os.path.join(info["report_dir"], "analysis.md")
    if os.path.exists(path) and not force:
        log("[info] analysis.md 已存在，不覆盖: %s" % path)
        return path
    lines = []
    lines.append("# BUG #%s 问题分析报告" % bug_id)
    lines.append("")
    lines.append("- **Bug 标题**: %s" % (bug.get("title") or "-"))
    lines.append("- **分析日期**: %s" % info["date"][:4] + "-" + info["date"][4:6] + "-" + info["date"][6:])
    lines.append("- **分析基线**: 分支 `%s` @ `%s`" % (info["base_branch"], info["head_short"] or "HEAD"))
    lines.append("- **远端同步**: %s" % sync_status_text(info))
    if info.get("wt_init"):
        init = info["wt_init"]
        if init.get("status") == "ok":
            lines.append("- **环境初始化**: 已安装 skill（%s）与系统提示词模板（%d 个文件）"
                         % (",".join(init.get("skills") or ["-"]) or "-",
                            init.get("prompt_files", 0)))
        else:
            issues = (init.get("errors") or []) + (init.get("skills_failed") or []) \
                     + (init.get("prompt_failed") or [])
            lines.append("- **环境初始化**: 降级（%s）；worktree 可能缺少部分 skill/提示词模板，"
                         "需在报告中说明影响" % ("; ".join(issues)[:200] or "部分失败"))
    lines.append("- **禅道链接**: %s/bug-view-%s.html" % (base_url, bug_id))
    lines.append("")
    lines.append("> **流程要求（分析先行）**：本报告与 `solution.md`（解决方案）必须在"
                 "实施任何代码修复**之前**补全——先输出完整分析报告与解决方案，"
                 "再按 solution.md 改代码。")
    lines.append("")
    lines.append("## 1. 问题描述")
    lines.append("")
    lines.append("- **状态**: %s    **严重程度**: %s    **优先级**: %s    **类型**: %s"
                 % (bug.get("status") or "-", bug.get("severity") or "-",
                    bug.get("pri") or "-", bug.get("type") or "-"))
    lines.append("- **创建人**: %s    **指派给**: %s"
                 % (user_name(bug.get("openedBy")), user_name(bug.get("assignedTo"))))
    lines.append("")
    steps = html_to_text(bug.get("steps") or "") or "（见 bug.md）"
    lines.append(steps)
    if actions:
        lines.append("")
        lines.append("评论/操作历史要点（完整内容见 bug.md）：")
        for a in actions:
            c = html_to_text(a.get("comment") or "")
            if c:
                lines.append("- **%s（%s）**：%s" % (user_name(a.get("actor")), a.get("action") or "",
                                                   c.replace("\n", " ")[:120]))
    if images:
        lines.append("")
        lines.append("附件截图: %s" % "、".join("`%s`" % fn for _, fn in images))
    lines.append("")
    frontend = info.get("frontend_workspaces") or []
    lines.append("## 2. 问题归属（前端问题 / 后端问题 / 前后端 / 待确认）")
    lines.append("")
    lines.append("（待填写）")
    lines.append("")
    lines.append("> 填写要求：结论行必须写成 `**结论**: <结论词>`，结论词只能是 "
                 "前端问题 / 后端问题 / 前后端 / 待确认，其后写明判定依据与置信度（高/中/低）。")
    lines.append("> 判定依据至少覆盖：涉及页面/路由/组件 → 调用的接口 → 后端服务方法/字段 的对应链，"
                 "并用 `文件:行号` 给出证据；无法用本地代码确认时写 待确认 并列出所需证据。")
    lines.append("> 根因待确认时，再写 `**排查状态**: 等待用户补充`；排查前端/后端及操作、配置、数据、环境原因，"
                 "列已确认事实、候选原因、证据缺口与按优先级排列的只读检查步骤、预期结果、判定依据。")
    lines.append("> 列用户需补充的最小数据与环境信息，说明必需/可选、用途、采集位置/方式、时间范围和脱敏要求；"
                 "不索取密码、Token、Cookie、完整生产配置或数据库备份。报告和对话均说明等待补充、未修复及恢复条件。")
    lines.append("> 待确认时暂停代码/配置/数据修改，不调用 ready/finish（含 --no-change），不释放锁；"
                 "用 render-html 更新报告。补充证据足够后先更新分析/方案，将排查状态改为已确认，再继续正常流程。")
    lines.append("> 改动范围：再写一行 `**改动范围**: 仅当前工作空间` 或 "
                 "`**改动范围**: 需要其他工作空间（本次不修改）`。")
    lines.append("> 默认只修改当前工作空间。若根因在其他工作空间（前端工作区、其他服务仓库等），"
                 "结论写「需要其他工作空间」，只出报告，并给出该工作空间路径与所需改动；不得修改其他工作空间代码。")
    lines.append("> 如果本次既需要本地修复、又要记录跨工作空间根因，则写「仅当前工作空间」，"
                 "并在「遗留问题」中单独说明跨工作空间结论与所需配合。")
    lines.append("> 前端工作区（只读分析，不是修复目标）：%s"
                 % ("、".join("`%s`" % p for p in frontend) if frontend
                    else "未配置（config 的 `FRONTEND_WORKSPACES` 为空，前端归属无法用本地代码验证）"))
    lines.append("> 后端修复工作区：`%s`" % info["wt_path"])
    lines.append("")
    sections = [
        "关键信息提取（业务场景 / 涉及页面或接口 / 日志报错 / 环境）",
        "代码定位过程（后端工作区与前端工作区分别列出检索关键字与命中文件）",
        "根因分析（确认的根因 / 推断（注明置信度）/ 排除的猜测 / 存疑待验证）",
        "遗留问题 / 待确认（解决方案见 solution.md）",
    ]
    for i, title in enumerate(sections, start=3):
        lines.append("## %d. %s" % (i, title))
        lines.append("")
        lines.append("（待填写）")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def scaffold_solution(bug, info, bug_id, force=False):
    """生成 solution.md（解决方案）骨架：机械字段自动填好，方案章节留待填写。

    与 analysis.md 同批生成、同属“分析先行”硬性约束：两者均完整落盘
    （无（待填写）残留）之前禁止修改任何代码。存在即跳过（--force 覆盖）。
    """
    path = os.path.join(info["report_dir"], "solution.md")
    if os.path.exists(path) and not force:
        log("[info] solution.md 已存在，不覆盖: %s" % path)
        return path
    lines = []
    lines.append("# BUG #%s 解决方案" % bug_id)
    lines.append("")
    lines.append("- **Bug 标题**: %s" % (bug.get("title") or "-"))
    lines.append("- **方案日期**: %s-%s-%s" % (info["date"][:4], info["date"][4:6], info["date"][6:]))
    lines.append("- **修复分支**: `%s`（基于 `%s`，%s）" % (
        info["branch"], info["base_branch"], sync_status_text(info)))
    lines.append("- **关联分析**: analysis.md（根因结论以其为准，方案逐条对应根因）")
    lines.append("")
    lines.append("> **流程要求（分析先行）**：analysis.md 与本方案均补全（无（待填写）残留）"
                 "**之前**，禁止修改任何代码；修复实施严格按本方案执行。")
    lines.append("> **根因待确认**：写明暂停代码修改、等待用户补充证据；只给排查步骤、资料清单、恢复条件与验证计划，"
                 "不虚构代码修复方案。操作/配置/数据/环境原因尚未排除时，不调用 ready/finish，也不擅自改现场。")
    lines.append("")
    sections = [
        ("方案对比与取舍（至少考虑两种候选方案：改动面 / 风险 / 可维护性）", None),
        ("最终方案设计（改动点与涉及文件，逐条对应根因）",
         "> 与 analysis.md 的「问题归属」「改动范围」保持一致：只写当前工作空间内的改动；"
         "改动范围=需要其他工作空间时，不写本地代码改动，只写所需配合与验证方式。"),
        ("影响面评估（受影响功能 / 接口 / 配置 / 数据）", None),
        ("风险与回滚（风险等级与理由；未提交状态回滚方式）", None),
        ("验证计划（编译 / 静态走查 / 自测用例）", None),
    ]
    for i, (title, note) in enumerate(sections, start=1):
        lines.append("## %d. %s" % (i, title))
        lines.append("")
        lines.append("（待填写）")
        lines.append("")
        if note:
            lines.append(note)
            lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def collect_diff(wt_path):
    """收集 worktree 未提交变更（含未跟踪文件）。

    注：WSL 挂载 Windows 盘（DrvFs）时 git 扫描较慢，本函数只做 2 次 git
    调用（status + diff --numstat），汇总统计由脚本合成，避免多次扫描。
    """
    _, status, _ = run_git(["status", "--porcelain"], wt_path)
    _, numstat, _ = run_git(["diff", "--numstat"], wt_path)
    files = []
    for l in numstat.splitlines():
        parts = l.split("\t")
        if len(parts) == 3:
            add, dele, path = parts
            files.append({"path": path, "add": add, "del": dele, "untracked": False})
    for l in status.splitlines():
        if l.startswith("?? "):
            files.append({"path": l[3:].strip(), "add": "-", "del": "-", "untracked": True})
    mod = [f for f in files if not f["untracked"]]
    new = [f for f in files if f["untracked"]]
    add_total = sum(int(f["add"]) for f in mod if str(f["add"]).isdigit())
    del_total = sum(int(f["del"]) for f in mod if str(f["del"]).isdigit())
    per_file = "\n".join("%s | +%s / -%s" % (f["path"], f["add"], f["del"]) for f in mod)
    if new:
        per_file = (per_file + "\n" if per_file else "") + "\n".join(
            "%s | 新增未跟踪文件" % f["path"] for f in new)
    diffstat = "%d 个文件修改(+%d/-%d)%s" % (
        len(mod), add_total, del_total, "；%d 个新增未跟踪文件" % len(new) if new else "")
    return files, diffstat, per_file


def scaffold_fix_report(info, bug_id, title, diff_data, force=False):
    """生成 fix-report.md（自动含未提交变更清单），存在即跳过（--force 覆盖）。"""
    path = os.path.join(info["report_dir"], "fix-report.md")
    if os.path.exists(path) and not force:
        log("[info] fix-report.md 已存在，不覆盖（--force 可重新生成）: %s" % path)
        return path
    files, diffstat, per_file = diff_data
    d = info["date"]
    lines = []
    lines.append("# BUG #%s 修复报告" % bug_id)
    lines.append("")
    lines.append("- **Bug 标题**: %s" % (title or "-"))
    base_note = "基于 `%s`" % info["base_branch"]
    if info.get("synced") is True:
        base_note += "，已同步远端 `%s`" % (info.get("sync_remote_branch") or "-")
    elif info.get("synced") is False:
        base_note += "，未同步远端（%s）" % (info.get("sync_reason") or "原因未记录")
    lines.append("- **修复分支**: `%s`（%s）" % (info["branch"], base_note))
    lines.append("- **修复日期**: %s-%s-%s" % (d[:4], d[4:6], d[6:]))
    lines.append("- **修复状态**: 已修复，待人工 review")
    lines.append("- **变更状态**: 待 finish 验证并独立提交，禁止开始下一 Bug" if info.get("mode") == "inplace" else
                 "- **变更状态**: **未提交**——改动保留在 worktree 工作区，等待人工 review 后由人工提交")
    lines.append("")
    lines.append("## 1. 修复内容")
    lines.append("")
    lines.append("（待填写：修复思路，对应 analysis.md 中的根因与 solution.md 中的方案）")
    lines.append("")
    lines.append("## 2. 代码变更清单")
    lines.append("")
    if files:
        lines.append("| # | 文件 | 变更 |")
        lines.append("|---|------|------|")
        for i, fitem in enumerate(files, 1):
            mark = "新增未跟踪" if fitem["untracked"] else "+%s / -%s" % (fitem["add"], fitem["del"])
            lines.append("| %d | `%s` | %s |" % (i, fitem["path"], mark))
        lines.append("")
        lines.append("（%s）" % diffstat)
    else:
        lines.append("**（未检测到代码改动**——若确已修改，请确认保存在 worktree：%s）" % info["wt_path"])
    lines.append("")
    lines.append("## 3. 修复验证")
    lines.append("")
    lines.append("（待填写：实际编译/测试命令与结果、未覆盖项；Maven 插件问题先查 Git 指针，仅证实不兼容且项目允许时跳过插件）")
    lines.append("")
    lines.append("## 4. 测试建议（给 QA）")
    lines.append("")
    lines.append("（待填写）")
    lines.append("")
    lines.append("## 5. 风险与回滚")
    lines.append("")
    lines.append("（待填写：风险等级与理由；未提交状态下回滚即 `git checkout -- <文件>` / 删除未跟踪文件）")
    lines.append("")
    lines.append("## 6. 产物位置")
    lines.append("")
    def _rel(name):
        return os.path.relpath(os.path.join(info["report_dir"], name), info["wt_path"])
    lines.append("- 问题分析报告: `%s`" % _rel("analysis.md"))
    lines.append("- 解决方案: `%s`" % _rel("solution.md"))
    lines.append("- 禅道 bug 快照: `%s`（含截图）" % _rel("bug.md"))
    lines.append("- worktree: `%s`" % wt_win_path(info["wt_path"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------- 子命令

def cmd_config_status(args):
    config_path, cfg = load_config(args.project)
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    print(json.dumps({"config_path": config_path, "missing": missing,
                      "complete": not missing}, ensure_ascii=False, indent=2))
    return 0 if not missing else 2


def cmd_save_config(args):
    if not args.pairs:
        log("ERROR: 至少提供一个 KEY=VALUE")
        return 2
    updates = {}
    for p in args.pairs:
        if "=" not in p:
            log("ERROR: 参数格式错误（应为 KEY=VALUE）: %s" % p)
            return 2
        k, v = p.split("=", 1)
        if k not in REQUIRED_KEYS + ["BUGFIX_BASE_BRANCH", FRONTEND_KEY]:
            log("ERROR: 未知配置项 %s（允许: %s）" % (k, ", ".join(REQUIRED_KEYS + ["BUGFIX_BASE_BRANCH", FRONTEND_KEY])))
            return 2
        updates[k] = v.strip()
    config_path, _ = load_config(args.project)
    save_config(config_path, updates)
    log("[ok] 已保存到 %s" % config_path)
    return 0


def cmd_get_bug(args):
    require_bug_id(args.bug_id)
    bug, actions, images, work_dir, base_url, md = fetch_bug_full(args.project, args.bug_id, args.out)
    print(md)
    log("")
    log("[ok] 已保存: %s" % os.path.join(work_dir, "bug.md"))
    log("[ok] 工作目录: %s" % work_dir)
    return 0


def cmd_worktree(args):
    require_bug_id(args.bug_id)
    reuse_target = check_existing(args.project, args.bug_id, reuse=args.reuse)
    info = setup_worktree(args.project, args.bug_id, args.base_branch, reuse_target=reuse_target)
    info["project"] = args.project
    print_kv(info)
    return 0


def cmd_prepare(args):
    """Fetch once, route deterministically, reserve the workspace before exposing it."""
    require_bug_id(args.bug_id)
    current = getattr(args, "current_workspace", None) or args.project
    previous = _routes.load_record(args.project, args.bug_id)
    if previous and (previous.get("locks") or previous.get("status") not in ("workspace_error", "waiting")):
        if previous.get("status") in ("committed", "no_change"):
            _routes.release(previous)
        if not args.reuse or previous.get("status") in ("committed", "no_change"):
            print("EXISTS\nEXISTING_REPORT_DIR=%s" % previous.get("report_dir", ""))
            return 4
    if not getattr(args, "allow_resolved", False):
        try:
            bug, actions, images, work_dir, base_url, md = fetch_bug_full(
                args.project, args.bug_id, skip_resolved=True)
        except ResolutionStop as exc:
            print("RESOLUTION_STOP=%s" % (exc.state or "unknown"))
            return 9 if exc.state == "set" else 10
    else:
        bug, actions, images, work_dir, base_url, md = fetch_bug_full(args.project, args.bug_id)
    try:
        route = _routes.select(args.project, args.bug_id, bug.get("title") or "")
    except (ValueError, OSError, _routes.RouteError) as exc:
        log("ERROR: 分流配置无效: %s" % exc)
        return 2
    if route["mode"] == "inplace":
        try:
            # Resuming must never redirect an unfinished repair to another target.
            if previous and previous.get("mode") == "inplace" and previous.get("locks"):
                if route["workspace"] != previous["route"]["workspace"] or route["branch"] != previous["route"]["branch"]:
                    raise _routes.RouteError("未完成修复的目标发生变化，请恢复原规则并处理已有现场")
            target_meta = Path(report_dir_for(route["workspace"], args.bug_id)) / "meta.json"
            if target_meta.is_file() and not (previous and previous.get("run_id")):
                print("EXISTS\nEXISTING_REPORT_DIR=%s" % target_meta.parent)
                return 4
            token, locks = _routes.reserve(args.project, args.bug_id, route, args.reuse)
        except _routes.Busy as exc:
            print("WAITING=%s" % exc)
            return 6
        except (_routes.RouteError, OSError) as exc:
            result = _routes.error_report(current, args.bug_id, bug.get("title", ""), route, str(exc), base_url)
            # Keep the original reservation when a previously prepared run fails validation.
            if previous and previous.get("locks"):
                original = dict(previous)
                original.update(result)
                original["route"] = previous["route"]
                result = original
            _routes.save(_routes.record_path(args.project, args.bug_id), result)
            print("HTML_REPORT=%s\nBROWSER_OPENED=%s\nERROR=%s" % (result["html_report"], result["browser_opened"], exc))
            if result.get("browser_error"):
                print("BROWSER_ERROR=" + result["browser_error"])
            return 7
        workspace = route["workspace"]
        report_dir = report_dir_for(workspace, args.bug_id)
        os.makedirs(report_dir, exist_ok=True)
        run = previous if previous and previous.get("run_id") == token else {
            "bug_id": str(args.bug_id), "run_id": token}
        run.update(mode="inplace", status="prepared", locks=locks, route=route,
                   workspace=workspace, branch=route["branch"], report_dir=report_dir,
                   title=bug.get("title", ""), project=os.path.abspath(args.project))
        _routes.save(_routes.record_path(args.project, args.bug_id), run)
        if "snapshot" not in run:
            try:
                run["snapshot"] = _routes.snapshot(workspace)
                _routes.save(_routes.record_path(args.project, args.bug_id), run)
            except (OSError, _routes.RouteError) as exc:
                run.update(status="blocked", error=str(exc))
                _routes.save(_routes.record_path(args.project, args.bug_id), run)
                log("ERROR: 无法保存修复前快照；保留锁等待恢复: %s" % exc)
                return 8
        import shutil
        for src in Path(work_dir).iterdir():
            if src.is_file():
                shutil.copy2(src, Path(report_dir) / src.name)
        info = {"repo_root": workspace, "wt_path": workspace, "report_dir": report_dir,
                "branch": route["branch"], "base_branch": route["branch"],
                "head_short": run["snapshot"]["head"], "date": datetime.date.today().strftime("%Y%m%d"),
                "mode": "inplace", "synced": False, "sync_reason": "复用开发工作区，不自动同步远端"}
        _routes.save(Path(report_dir) / "meta.json", dict(info, bug_id=str(args.bug_id), run_id=token,
                                                        status="prepared", route=route))
    else:
        # An in-flight bound run must not be silently abandoned by a config change.
        if previous and previous.get("locks") and previous.get("status") not in ("committed", "no_change"):
            log("ERROR: 已有绑定工作区修复未完成，请恢复规则并 --reuse；不创建新 worktree")
            return 6
        reuse_target = check_existing(args.project, args.bug_id, reuse=args.reuse)
        _, cfg = load_config(args.project)
        base = args.base_branch or cfg.get("BUGFIX_BASE_BRANCH")
        info = setup_worktree(args.project, args.bug_id, base, reuse_target=reuse_target)
        run = {"bug_id": str(args.bug_id), "run_id": __import__("uuid").uuid4().hex,
               "mode": "worktree", "status": "prepared", "route": route,
               "workspace": info["wt_path"], "report_dir": info["report_dir"], "branch": info["branch"]}
        _routes.save(_routes.record_path(args.project, args.bug_id), run)
        meta = _routes.read(Path(info["report_dir"]) / "meta.json")
        meta.update(mode="worktree", run_id=run["run_id"], route=route)
        _routes.save(Path(info["report_dir"]) / "meta.json", meta)
    info["project"] = args.project
    try:
        _, prepare_cfg = load_config(args.project)
    except (OSError, _routes.RouteError):
        prepare_cfg = {}
    info["frontend_workspaces"] = frontend_workspaces(prepare_cfg, args.project)
    print("MODE=%s\nRUN_ID=%s\nROUTE_REASON=%s" % (run["mode"], run["run_id"], route["reason"]))
    analysis_path = scaffold_analysis(bug, actions, images, info, base_url, args.bug_id,
                                      force=args.force)
    solution_path = scaffold_solution(bug, info, args.bug_id, force=args.force)
    print(md)
    print("")
    print_kv(info, extra=[
        "BUG_TITLE=%s" % (bug.get("title") or ""),
        "ANALYSIS_MD=%s" % analysis_path,
        "SOLUTION_MD=%s" % solution_path,
        "FRONTEND_MISSING=%s" % (",".join(p for p in info["frontend_workspaces"]
                                          if not os.path.isdir(p)) or "none"),
        "NEXT=先在 WORKTREE 中只读分析代码并补全 analysis.md 与 solution.md（输出"
        "完整分析报告与解决方案，此阶段不改任何代码），MODE=inplace 时先运行 ready；再按 solution.md 实施"
        "修复并 report/补全；绑定模式 finish 提交并更新 HTML，worktree 模式 render-html --analysis-only 在修复前生成"
        "分析/方案 HTML，全部报告补全后 render-html 更新三份最终 HTML，不提交。Bug=%s" % args.bug_id,
    ])
    log("")
    for name, target in _routes._reports.render_reports(info["report_dir"]).items():
        print("%s_HTML=%s" % (name.upper().replace("-", "_"), target))
    log("[ok] bug 资料与分析/方案的 MD 和 HTML 骨架已就绪: %s" % info["report_dir"])
    return 0


def doc_complete_status(report_dir, name):
    """校验单份报告完成度：no=已完整（无（待填写）标记）；yes=仍有待填写；missing=不存在。"""
    path = os.path.join(report_dir, name)
    if not os.path.isfile(path):
        return "missing"
    with open(path, encoding="utf-8", errors="replace") as f:
        return "yes" if "（待填写" in f.read() else "no"


def analysis_complete_status(report_dir):
    """校验 analysis.md（分析报告）完成度，返回值语义同 doc_complete_status。"""
    return doc_complete_status(report_dir, "analysis.md")


def solution_complete_status(report_dir):
    """校验 solution.md（解决方案）完成度，返回值语义同 doc_complete_status。"""
    return doc_complete_status(report_dir, "solution.md")


# 先匹配「前后端」——它包含「后端」子串，顺序不能调。
LAYER_CHOICES = ("前后端", "前端问题", "后端问题", "待确认")
# 「需要其他工作空间」比「仅当前工作空间」更具体，必须先行匹配。
SCOPE_CHOICES = ("需要其他工作空间", "仅当前工作空间")
LAYER_HEADING = re.compile(r"^##\s*\d+\.\s*问题归属[^\n]*\n(.*?)(?=^##\s|\Z)", re.S | re.M)
CONCLUSION_LINE = r"^\s*(?:>\s*)?(?:[-*+]\s*)?\*\*%s\*\*\s*[:：]\s*(.+)$"


def _analysis_conclusion(report_dir, label, choices):
    """只从 analysis.md「问题归属」章节的 `**<label>**:` 行提取结论。

    missing=文件不存在；unparsed=章节缺失或没有可识别结论；否则返回命中词。
    """
    path = os.path.join(report_dir, "analysis.md")
    if not os.path.isfile(path):
        return "missing"
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    section = LAYER_HEADING.search(text)
    if not section:
        return "unparsed"
    pattern = re.compile(CONCLUSION_LINE % re.escape(label), re.M)
    for match in pattern.finditer(section.group(1)):
        for choice in choices:
            if choice in match.group(1):
                return choice
        return "unparsed"
    return "unparsed"


def analysis_layer_attribution(report_dir):
    """提取前端/后端归属：前端问题 / 后端问题 / 前后端 / 待确认 / unparsed / missing。"""
    return _analysis_conclusion(report_dir, "结论", LAYER_CHOICES)


def analysis_change_scope(report_dir):
    """提取改动范围：仅当前工作空间 / 需要其他工作空间 / unparsed / missing。"""
    return _analysis_conclusion(report_dir, "改动范围", SCOPE_CHOICES)


def cmd_report(args):
    """生成 fix-report.md（自动含未提交变更清单）并输出汇报摘要。"""
    require_bug_id(args.bug_id)
    record = _routes.load_record(args.project, args.bug_id)
    if record and record.get("mode") == "inplace":
        _routes.validate_workspace(record["route"])
        info = _routes.read(Path(record["report_dir"]) / "meta.json")
        info["report_dir"] = record["report_dir"]
    else:
        found = find_existing_worktrees(args.project, args.bug_id)
        worktrees = sorted(found["worktrees"], key=lambda wb: os.path.basename(wb[0]))
        if not worktrees:
            log("ERROR: 未找到 bug #%s 的 worktree（先运行 prepare）" % args.bug_id)
            return 2
        info = info_from_worktree(args.project, args.bug_id, *worktrees[-1])
    rc, _, _ = run_git(["rev-parse", "--git-dir"], info["wt_path"], check=False)
    if rc != 0:
        log("ERROR: worktree 不可用: %s（请人工修复）" % info["wt_path"])
        return 3
    # 从报告目录读 bug 标题（资料由 prepare 拷贝）
    title = ""
    bug_md = os.path.join(info["report_dir"], "bug.md")
    if os.path.isfile(bug_md):
        with open(bug_md, encoding="utf-8") as f:
            m = re.search(r"\*\*标题\*\*: (.+)", f.read())
            if m:
                title = m.group(1).strip()
    # 变更采集只做一次（两处复用），降低慢盘上 git 扫描次数
    diff_data = collect_diff(info["wt_path"])
    if record and record.get("mode") == "inplace":
        current = _routes.snapshot(info["wt_path"])
        selected = set(_routes.changed(record["snapshot"], current))
        files = [f for f in diff_data[0] if f["path"] in selected]
        known = {f["path"] for f in files}
        files.extend({"path": p, "add": "-", "del": "-", "untracked": False} for p in sorted(selected - known))
        diff_data = (files, "%d 个本次变更文件；已有开发改动不计入" % len(files),
                     "\n".join("%s | +%s / -%s" % (f["path"], f["add"], f["del"]) for f in files))
    path = scaffold_fix_report(info, args.bug_id, title, diff_data, force=args.force)
    files, diffstat, per_file = diff_data
    print("SUMMARY")
    print("BUG_ID=%s" % args.bug_id)
    print("BUG_TITLE=%s" % title)
    print("BRANCH=%s" % info["branch"])
    print("BASE_BRANCH=%s" % info["base_branch"])
    if info.get("synced") is True:
        print("BASE_SYNCED=yes（%s）" % info.get("sync_reason", ""))
    elif info.get("synced") is False:
        print("BASE_SYNCED=no（%s）" % (info.get("sync_reason") or "原因未记录"))
    else:
        print("BASE_SYNCED=unknown（旧版 worktree 或 --reuse，未记录同步信息）")
    print("WORKTREE=%s" % info["wt_path"])
    print("WORKTREE_WIN=%s" % wt_win_path(info["wt_path"]))
    print("REPORT_DIR=%s" % info["report_dir"])
    print("FIX_REPORT=%s" % path)
    astat = analysis_complete_status(info["report_dir"])
    sstat = solution_complete_status(info["report_dir"])
    print("ANALYSIS_MD=%s" % os.path.join(info["report_dir"], "analysis.md"))
    print("SOLUTION_MD=%s" % os.path.join(info["report_dir"], "solution.md"))
    if sstat == "no":
        print("SOLUTION_INCOMPLETE=no（解决方案已完整，符合分析先行要求）")
    elif sstat == "yes":
        print("SOLUTION_INCOMPLETE=yes（solution.md 仍有（待填写）章节——请立即补全"
              "解决方案，再补全 fix-report.md，并在汇报中说明偏离）")
    else:
        print("SOLUTION_INCOMPLETE=missing（solution.md 不存在，请立即补建并补全，"
              "并在汇报中说明偏离）")
    if astat == "no":
        print("ANALYSIS_INCOMPLETE=no（分析报告已完整，符合分析先行要求）")
    elif astat == "yes":
        print("ANALYSIS_INCOMPLETE=yes（analysis.md 仍有（待填写）章节——流程要求分析报告"
              "先于修复完成，请立即补全 analysis.md，再补全 fix-report.md，并在汇报中说明偏离）")
    else:
        print("ANALYSIS_INCOMPLETE=missing（analysis.md 不存在，请立即补建并补全，"
              "并在汇报中说明偏离）")
    layer = analysis_layer_attribution(info["report_dir"])
    scope = analysis_change_scope(info["report_dir"])
    print("LAYER_ATTRIBUTION=%s" % layer)
    print("CHANGE_SCOPE=%s" % scope)
    if layer == "missing":
        print("LAYER_ATTRIBUTION_HINT=analysis.md 不存在，无法给出问题归属；请先补全 analysis.md")
    elif layer == "unparsed":
        print("LAYER_ATTRIBUTION_HINT=analysis.md 的「问题归属」章节缺少 `**结论**:` 行；"
              "必须写明 前端问题 / 后端问题 / 前后端 / 待确认 后才能汇报")
    if scope == "unparsed":
        print("CHANGE_SCOPE_HINT=analysis.md 的「问题归属」章节缺少 `**改动范围**:` 行；"
              "必须写明 仅当前工作空间 或 需要其他工作空间（本次不修改）")
    elif scope == "需要其他工作空间":
        print("CHANGE_SCOPE_HINT=已声明需要其他工作空间：本次不得提交本地代码改动，"
              "用 finish --no-change 收尾；如需本地修复请更正「改动范围」结论")
    print("CHANGED_FILES=%d" % len(files))
    print("COMMITTED=pending（绑定分支须 finish 验证并提交后才可开始下一 Bug）" if info.get("mode") == "inplace" else
          "COMMITTED=no（改动保留在工作区，等待人工 review，不要自动 commit）")
    if per_file:
        print("---- 变更明细 ----")
        print(per_file)
    for name, target in _routes._reports.render_reports(info["report_dir"]).items():
        print("%s_HTML=%s" % (name.upper().replace("-", "_"), target))
    next_hint = "NEXT=补全 fix-report.md；绑定模式 finish 会更新 HTML，worktree 模式运行 render-html 后再汇报"
    if astat != "no":
        next_hint += "；⚠ 先补全 analysis.md（分析先行偏离：%s）" % astat
    if sstat != "no":
        next_hint += "；⚠ 先补全 solution.md（方案偏离：%s）" % sstat
    print(next_hint)
    return 0


def cmd_render_html(args):
    require_bug_id(args.bug_id)
    record = _routes.load_record(args.project, args.bug_id)
    if record and record.get("report_dir"):
        directory = record["report_dir"]
    else:
        found = find_existing_worktrees(args.project, args.bug_id)
        worktrees = sorted(found["worktrees"], key=lambda wb: os.path.basename(wb[0]))
        if not worktrees:
            log("ERROR: 未找到报告目录，请先 prepare")
            return 2
        directory = resolve_report_dir(worktrees[-1][0], args.bug_id)
    names = ("analysis.md", "solution.md") if args.analysis_only else _routes._reports.REPORT_NAMES
    targets = _routes._reports.render_reports(directory, names=names, require_complete=True)
    if record:
        record.setdefault("html_reports", {}).update(targets)
        _routes.save(_routes.record_path(args.project, args.bug_id), record)
    print(json.dumps({"report_dir": directory, "html_reports": targets}, ensure_ascii=False, indent=2))
    return 0


def cmd_ready(args):
    try:
        result = _routes.ready(args.project, args.bug_id)
        print("ANALYSIS_SEALED=yes\nRUN_ID=" + result["run_id"])
        print(json.dumps({"html_reports": result["html_reports"]}, ensure_ascii=False))
        return 0
    except (_routes.RouteError, OSError, ValueError) as exc:
        log("ERROR: %s" % exc)
        return 8


def cmd_finish(args):
    record = _routes.load_record(args.project, args.bug_id)
    if record and not args.no_change and args.files:
        scope = analysis_change_scope(record.get("report_dir", ""))
        if scope == "需要其他工作空间":
            log("ERROR: analysis.md 已声明「需要其他工作空间（本次不修改）」，"
                "不能提交本次代码改动；如确需本地修复，请更正「改动范围」结论")
            return 8
    try:
        result = _routes.finish(args.project, args.bug_id, args.files, args.check_command, args.no_change)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (_routes.RouteError, OSError, ValueError) as exc:
        rec = _routes.load_record(args.project, args.bug_id)
        if rec:
            rec.update(status="blocked", ok=False, error=str(exc))
            _routes.save(_routes.record_path(args.project, args.bug_id), rec)
        log("ERROR: %s；保留现场与分支锁，后续 Bug 暂停" % exc)
        return 8


def cmd_download_image(args):
    opener = build_opener(with_cookie=True)
    base_url = normalize_base_url(args.url.split("/file-read-")[0] if "/file-read-" in args.url else args.url)
    if args.cookie:
        opener.addheaders.append(("Cookie", "zentaosid=%s" % args.cookie))
    dest = os.path.abspath(args.dest)
    saved = download_images(opener, base_url, [args.url], os.path.dirname(dest) or ".")
    if saved:
        src = os.path.join(os.path.dirname(dest), saved[0][1])
        if src != dest:
            os.replace(src, dest)
        log("[ok] saved -> %s" % dest)
        return 0
    log("ERROR: 下载失败或内容非图片")
    return 3


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="zentao-bugfix skill 脚本（禅道 bug 自动修复流程）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("config-status", help="检查 .agents/zentao-bugfix/routes.json 配置")
    p.add_argument("--project", default=".")
    p.set_defaults(func=cmd_config_status)

    p = sub.add_parser("save-config", help="保存配置到 .agents/zentao-bugfix/routes.json")
    p.add_argument("pairs", nargs="*", help="KEY=VALUE ...")
    p.add_argument("--project", default=".")
    p.set_defaults(func=cmd_save_config)

    p = sub.add_parser("get-bug", help="拉取 bug 详情/评论/图片")
    p.add_argument("bug_id")
    p.add_argument("--project", default=".")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_get_bug)

    p = sub.add_parser("worktree", help="创建 bugfix worktree（已存在则停止，返回码 4；--reuse 复用）")
    p.add_argument("bug_id")
    p.add_argument("base_branch", nargs="?", default=None)
    p.add_argument("--project", default=".")
    p.add_argument("--reuse", action="store_true", help="复用该 bugId 已存在的 worktree 继续处理")
    p.set_defaults(func=cmd_worktree)

    p = sub.add_parser("prepare", help="拉取 Bug + 路由匹配 + 绑定工作区或新 worktree + 分析骨架")
    p.add_argument("bug_id")
    p.add_argument("base_branch", nargs="?", default=None)
    p.add_argument("--project", default=".")
    p.add_argument("--reuse", action="store_true", help="复用该 bugId 已存在的 worktree 继续处理")
    p.add_argument("--force", action="store_true", help="重新生成 analysis.md")
    p.add_argument("--current-workspace", help="异常 HTML 报告所在的当前/监听启动工作区")
    p.add_argument("--skip-resolved", action="store_true",
                   help="兼容旧调用：默认即跳过已有解决方案的 Bug，无需显式传入")
    p.add_argument("--allow-resolved", action="store_true",
                   help="人工覆盖：允许处理已有解决方案（resolution 有值）的 Bug")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("render-html", help="从已补全的 MD 生成/更新对应离线 HTML（不打开浏览器）")
    p.add_argument("bug_id")
    p.add_argument("--project", default=".")
    p.add_argument("--analysis-only", action="store_true", help="修复前仅更新 analysis/solution HTML")
    p.set_defaults(func=cmd_render_html)

    p = sub.add_parser("ready", help="绑定工作区修改代码前校验分析先行并封存文档")
    p.add_argument("bug_id")
    p.add_argument("--project", default=".")
    p.set_defaults(func=cmd_ready)

    p = sub.add_parser("finish", help="验证并提交绑定分支的单个 Bug，成功后释放队列锁")
    p.add_argument("bug_id")
    p.add_argument("--project", default=".")
    p.add_argument("--files", nargs="*", default=[], help="本次修复的全部相对文件路径")
    p.add_argument("--check-command", required=True, help="验证命令，直接执行，不通过 shell")
    p.add_argument("--no-change", action="store_true", help="确认无需代码修改，不产生空提交")
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("report", help="生成 fix-report.md 并输出汇报摘要")
    p.add_argument("bug_id")
    p.add_argument("--project", default=".")
    p.add_argument("--force", action="store_true", help="覆盖已有 fix-report.md")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("download-image", help="下载附件图片")
    p.add_argument("url")
    p.add_argument("dest")
    p.add_argument("--cookie", default=None)
    p.set_defaults(func=cmd_download_image)

    args = ap.parse_args()
    try:
        return args.func(args)
    except (ValueError, _routes.RouteError) as exc:
        log("ERROR: 配置或流程错误: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
