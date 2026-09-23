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

配置文件：<项目工作空间>/.agents/.env（KEY=VALUE）：
    ZENTAO_BASE_URL=http://host:port
    ZENTAO_ACCOUNT=xxx
    ZENTAO_PASSWORD=xxx

子命令（一次调用完成尽量多的事情）：
    config-status [--project DIR]                 检查配置，输出 JSON
    save-config KEY=VALUE... [--project DIR]      保存/合并写入 .env
    get-bug <bugId> [--project DIR]               拉取禅道 bug（详情+评论+截图）
    worktree <bugId> [baseBranch] [--project DIR] [--reuse]
                                                  创建 bugfix worktree + 同步远端最新
                                                  基准分支（fetch+merge 进 bugfix 分支）
                                                  + 拷贝资料；该 bugId 已有 worktree/
                                                  修复分支时停止（返回码 4），--reuse
                                                  显式复用继续（复用时不同步远端）
    prepare <bugId> [baseBranch] [--project DIR] [--reuse] [--force]
                                                  一次完成：防重检查 + get-bug +
                                                  worktree（含远端同步）+ 生成
                                                  analysis.md 分析骨架
    report <bugId> [--project DIR] [--force]      生成 fix-report.md（含未提交
                                                  变更清单）+ 输出汇报摘要；自动定位
                                                  该 bugId 既有 worktree（跨日期）；
                                                  校验 analysis.md 完成度并输出
                                                  ANALYSIS_INCOMPLETE 字段
    download-image <url> <dest> [--cookie SID]    内部使用：下载附件图片

关键策略：
    - 所有 git 操作通过 subprocess 调用系统 git；
    - worktree 的 git 元数据改写为相对路径，WSL git 与 Windows git 均可识别；
    - 全程不做 git commit（保留工作区改动等待人工 review）；
    - 分析先行：analysis.md（完整分析报告）必须在实施任何代码修复之前由 AI 补全；
      prepare 的 NEXT 提示与 report 的 ANALYSIS_INCOMPLETE 字段（no=已完整 /
      yes=仍有（待填写）章节 / missing=文件不存在）负责校验提醒，不硬失败，
      保持流程可恢复。
    - 幂等防重：同一 bugId 重复 prepare/worktree 时，检测到已有 worktree/修复
      分支（不限日期）即停止并输出 EXISTS 摘要（返回码 4）；--reuse 可显式复用
      既有 worktree 继续处理；report 自动定位既有 worktree。
    - 远端同步：**新建** worktree 后自动 fetch 远端基准分支并合并进 bugfix 分支
      （git fetch <remote> <基准> + git merge <remote>/<基准>，在 worktree 内执行）；
      仓库无远程 / fetch 失败 / 基准非分支 → 警告降级用本地快照并在输出标注
      SYNCED=no；合并冲突 → 自动 git merge --abort 保持 worktree 干净后停止
      （返回码 5，输出 SYNC_CONFLICT 块，人工决策）；不更新本地基准分支引用、
      不碰主工作空间；--reuse 复用时不同步。

返回码：0 成功；2 配置/参数错误；3 bug 获取或 worktree 创建失败；
       4 该 bugId 已存在 worktree/修复分支（防重复处理，需人工决策）；
       5 远端基准分支合并失败/冲突（已自动 git merge --abort，worktree 保持
       干净，人工决策后续）。
"""
import argparse
import html as html_mod
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

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
    )
    if check and proc.returncode != 0:
        raise RuntimeError("git %s 失败(%d): %s" % (
            args[:3], proc.returncode, (proc.stderr or "").strip()[:300]))
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ---------------------------------------------------------------- 配置

def load_env(project_dir):
    env_path = os.path.join(os.path.abspath(project_dir), ".agents", ".env")
    cfg = {}
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return env_path, cfg


def save_env(env_path, updates):
    existing_lines = []
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8-sig") as f:
            existing_lines = f.read().splitlines()
    replaced = set()
    out = []
    for line in existing_lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                out.append("%s=%s" % (k, updates[k]))
                replaced.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in replaced:
            out.append("%s=%s" % (k, v))
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")


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
    if bug.get("resolvedBy"):
        lines.append("- **解决人**: %s    **解决方案**: %s    **解决时间**: %s"
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


def fetch_bug_full(project_dir, bug_id, out_dir=None):
    """拉取禅道 bug 全量数据，返回 (bug, actions, images, work_dir, base_url, md_text)。"""
    env_path, cfg = load_env(project_dir)
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        log("ERROR: 配置不完整，缺少 %s，请先补充保存到 %s" % (", ".join(missing), env_path))
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
    date = subprocess.run(["date", "+%Y%m%d"], text=True, stdout=subprocess.PIPE).stdout.strip()
    branch = "bugfix/%s_%s" % (bug_id, date)
    dir_name = branch.replace("/", "_")
    wt_path = os.path.join(parent_dir, dir_name)
    return {
        "repo_root": repo_root, "parent_dir": parent_dir, "base_branch": base_branch,
        "cur_branch": cur_branch, "head_short": head_short, "date": date,
        "branch": branch, "dir_name": dir_name, "wt_path": wt_path,
        "report_dir": os.path.join(wt_path, ".agents", "bugfix", str(bug_id)),
    }


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
            print("EXISTING_REPORT_DIR=%s" % os.path.join(wt_path, ".agents", "bugfix", str(bug_id)))
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
            log("查看既有结果: %s 下的 analysis.md / fix-report.md" % os.path.join(
                worktrees[-1][0], ".agents", "bugfix", str(bug_id)))
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
                              stdout=subprocess.PIPE).stdout.strip()
    report_dir = os.path.join(wt_path, ".agents", "bugfix", str(bug_id))
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

        # 相对路径改写：WSL git / Windows git 双环境兼容
        repo_name = os.path.basename(repo_root)
        admin_dir = os.path.join(repo_root, ".git", "worktrees", info["dir_name"])
        if os.path.isdir(os.path.join(repo_root, ".git")) and os.path.isdir(admin_dir):
            with open(os.path.join(wt_path, ".git"), "w", encoding="utf-8") as f:
                f.write("gitdir: ../%s/.git/worktrees/%s\n" % (repo_name, info["dir_name"]))
            with open(os.path.join(admin_dir, "gitdir"), "w", encoding="utf-8") as f:
                f.write("../../../../%s/.git\n" % info["dir_name"])
        else:
            log("[warn] 非标准 .git 布局，跳过相对路径改写")

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
        for k in ("synced", "sync_reason", "sync_remote_branch"):
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
    lines.append("- **禅道链接**: %s/bug-view-%s.html" % (base_url, bug_id))
    lines.append("")
    lines.append("> **流程要求（分析先行）**：本报告必须在实施任何代码修复**之前**补全——"
                 "先针对 bug 与代码理解输出完整分析报告，再按第 5 节修复方案改代码。")
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
    sections = [
        "关键信息提取（业务场景 / 涉及接口 / 日志报错 / 环境）",
        "代码定位过程",
        "根因分析（确认的根因 / 排除的猜测 / 存疑待验证）",
        "修复方案设计（方案对比与取舍 / 影响面评估）",
        "遗留问题 / 待确认",
    ]
    for i, title in enumerate(sections, start=2):
        lines.append("## %d. %s" % (i, title))
        lines.append("")
        lines.append("（待填写）")
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
    lines.append("- **变更状态**: **未提交**——改动保留在 worktree 工作区，等待人工 review 后由人工提交")
    lines.append("")
    lines.append("## 1. 修复内容")
    lines.append("")
    lines.append("（待填写：修复思路，对应 analysis.md 中的根因与方案）")
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
    lines.append("（待填写：编译命令与结果 / 静态走查结论；Maven 项目在 worktree 下编译需加 "
                 "`-Dmaven.gitcommitid.skip=true`）")
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
    lines.append("- 问题分析报告: `.agents/bugfix/%s/analysis.md`" % bug_id)
    lines.append("- 禅道 bug 快照: `.agents/bugfix/%s/bug.md`（含截图）" % bug_id)
    lines.append("- worktree: `%s`" % wt_win_path(info["wt_path"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------- 子命令

def cmd_config_status(args):
    env_path, cfg = load_env(args.project)
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    print(json.dumps({"env_path": env_path, "missing": missing,
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
        if k not in REQUIRED_KEYS:
            log("ERROR: 未知配置项 %s（允许: %s）" % (k, ", ".join(REQUIRED_KEYS)))
            return 2
        updates[k] = v.strip()
    env_path, _ = load_env(args.project)
    save_env(env_path, updates)
    log("[ok] 已保存到 %s" % env_path)
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
    """一次调用：防重检查 + 拉取 bug + 建 worktree + 生成 analysis.md 骨架。"""
    require_bug_id(args.bug_id)
    reuse_target = check_existing(args.project, args.bug_id, reuse=args.reuse)
    bug, actions, images, work_dir, base_url, md = fetch_bug_full(args.project, args.bug_id)
    info = setup_worktree(args.project, args.bug_id, args.base_branch, reuse_target=reuse_target)
    info["project"] = args.project
    analysis_path = scaffold_analysis(bug, actions, images, info, base_url, args.bug_id,
                                      force=args.force)
    print(md)
    print("")
    print_kv(info, extra=[
        "BUG_TITLE=%s" % (bug.get("title") or ""),
        "ANALYSIS_MD=%s" % analysis_path,
        "NEXT=先在 WORKTREE 中只读分析代码并补全 analysis.md（输出完整分析报告，"
        "此阶段不改任何代码），再按报告实施修复；完成后运行: report %s" % args.bug_id,
    ])
    log("")
    log("[ok] bug 资料与 analysis.md 骨架已就绪: %s" % info["report_dir"])
    return 0


def analysis_complete_status(report_dir):
    """校验 analysis.md 完成度（分析先行流程）。

    返回 "no"=已完整（无（待填写）标记）；"yes"=仍有（待填写）章节；
    "missing"=analysis.md 不存在。
    """
    path = os.path.join(report_dir, "analysis.md")
    if not os.path.isfile(path):
        return "missing"
    with open(path, encoding="utf-8", errors="replace") as f:
        return "yes" if "（待填写" in f.read() else "no"


def cmd_report(args):
    """生成 fix-report.md（自动含未提交变更清单）并输出汇报摘要。"""
    require_bug_id(args.bug_id)
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
    print("ANALYSIS_MD=%s" % os.path.join(info["report_dir"], "analysis.md"))
    if astat == "no":
        print("ANALYSIS_INCOMPLETE=no（分析报告已完整，符合分析先行要求）")
    elif astat == "yes":
        print("ANALYSIS_INCOMPLETE=yes（analysis.md 仍有（待填写）章节——流程要求分析报告"
              "先于修复完成，请立即补全 analysis.md，再补全 fix-report.md，并在汇报中说明偏离）")
    else:
        print("ANALYSIS_INCOMPLETE=missing（analysis.md 不存在，请立即补建并补全，"
              "并在汇报中说明偏离）")
    print("CHANGED_FILES=%d" % len(files))
    print("COMMITTED=no（改动保留在工作区，等待人工 review，不要自动 commit）")
    if per_file:
        print("---- 变更明细 ----")
        print(per_file)
    next_hint = "NEXT=补全 fix-report.md 中（待填写）章节后向用户汇报"
    if astat != "no":
        next_hint += "；⚠ 先补全 analysis.md（分析先行偏离：%s）" % astat
    print(next_hint)
    return 0


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
    ap = argparse.ArgumentParser(description="zentao-bugfix skill 脚本（禅道 bug 自动修复流程）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("config-status", help="检查 .agents/.env 配置")
    p.add_argument("--project", default=".")
    p.set_defaults(func=cmd_config_status)

    p = sub.add_parser("save-config", help="保存配置到 .agents/.env")
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

    p = sub.add_parser("prepare", help="防重检查 + get-bug + worktree + analysis.md 骨架（推荐入口）")
    p.add_argument("bug_id")
    p.add_argument("base_branch", nargs="?", default=None)
    p.add_argument("--project", default=".")
    p.add_argument("--reuse", action="store_true", help="复用该 bugId 已存在的 worktree 继续处理")
    p.add_argument("--force", action="store_true", help="重新生成 analysis.md")
    p.set_defaults(func=cmd_prepare)

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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
