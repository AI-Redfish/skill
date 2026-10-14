#!/usr/bin/env python3
"""Routing, persistent reservations and per-bug commits (standard library only)."""
from contextlib import contextmanager, ExitStack
import hashlib
import importlib.util
import html
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
import webbrowser
from datetime import datetime


_reports_spec = importlib.util.spec_from_file_location("report_html", Path(__file__).with_name("report_html.py"))
_reports = importlib.util.module_from_spec(_reports_spec)
_reports_spec.loader.exec_module(_reports)


class RouteError(RuntimeError):
    pass


class Busy(RouteError):
    pass


def git(repo, *args, env=None, input=None):
    p = subprocess.run(["git", *args], cwd=str(repo), env=env, input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RouteError(p.stderr.decode("utf-8", "replace").strip()[:1000])
    return p.stdout


def text(repo, *args):
    return git(repo, *args).decode("utf-8", "replace").strip()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def root(project):
    return Path(project).resolve() / ".agents" / "zentao-bugfix"


def record_path(project, bug_id):
    if not re.fullmatch(r"[0-9]+", str(bug_id)):
        raise RouteError("Bug ID 必须为数字")
    return root(project) / "runs" / (str(bug_id) + ".json")


def load_record(project, bug_id):
    p = record_path(project, bug_id)
    return read(p) if p.is_file() else None


def workspace_path(value, project):
    # Accept Windows routes from a WSL listener; relative paths anchor to project.
    value = value.replace("\\", "/")
    if os.name != "nt" and re.match(r"^[A-Za-z]:/", value):
        value = "/mnt/" + value[0].lower() + value[2:]
    p = Path(value)
    return (p if p.is_absolute() else Path(project) / p).resolve()


def config_path(project):
    return root(project) / "routes.json"


def load_document(path):
    path = Path(path)
    if not path.exists():
        return {"config": {}, "rules": []}
    data = read(path)
    if not isinstance(data, dict) or set(data) - {"config", "rules"}:
        raise RouteError("routes.json 顶层只支持 config 对象和 rules 数组")
    if not isinstance(data.get("config", {}), dict) or not isinstance(data.get("rules", []), list):
        raise RouteError("routes.json 的 config 必须为对象，rules 必须为数组")
    for key, value in data.get("config", {}).items():
        if not key.strip() or not isinstance(value, str):
            raise RouteError("routes.json config 中的键必须非空，值必须为字符串")
    return data


def load_config(path):
    return dict(load_document(path).get("config", {}))


def save_config(path, updates):
    data = load_document(path)
    cfg = dict(data.get("config", {}))
    if any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in updates.items()):
        raise RouteError("配置键必须非空，值必须为字符串")
    cfg.update(updates)
    data["config"] = cfg
    data.setdefault("rules", [])
    save(path, data)
    # The unified document can now contain credentials.
    if os.name != "nt":
        Path(path).chmod(0o600)


def select(project, bug_id, title):
    path = config_path(project)
    if not path.exists():
        return {"mode": "worktree", "reason": "未配置分流规则"}
    data = load_document(path)
    exact, fuzzy = [], []
    for rule in data.get("rules", []):
        if not isinstance(rule, dict) or set(rule) - {"name", "match", "workspace", "target_branch"}:
            raise RouteError("无效规则或未知配置字段")
        match = rule.get("match")
        if not isinstance(match, dict) or len(match) != 1 or next(iter(match)) not in ("bug_id", "title_contains"):
            raise RouteError("每条规则只能使用 bug_id 或 title_contains 其中一种条件")
        key, value = next(iter(match.items()))
        if not isinstance(value, str) or not value.strip():
            raise RouteError("匹配值必须为非空字符串")
        if key == "bug_id" and not re.fullmatch(r"[0-9]+", value):
            raise RouteError("规则 bug_id 必须为数字字符串")
        for field in ("workspace", "target_branch"):
            if not isinstance(rule.get(field), str) or not rule[field].strip():
                raise RouteError("规则缺少 " + field)
        if key == "bug_id" and value == str(bug_id):
            exact.append(rule)
        if key == "title_contains" and value.casefold() in str(title).casefold():
            fuzzy.append(rule)
    hits = exact or fuzzy
    if not hits:
        return {"mode": "worktree", "reason": "未命中任何规则"}
    targets = {(os.path.normcase(str(workspace_path(r["workspace"], project))), r["target_branch"]) for r in hits}
    if len(targets) != 1:
        return {"mode": "worktree", "reason": "同一优先级规则命中不同目标，回退独立 worktree", "rules": hits}
    return {"mode": "inplace", "workspace": str(workspace_path(hits[0]["workspace"], project)),
            "branch": hits[0]["target_branch"], "rules": hits,
            "reason": "bug_id 精确匹配" if exact else "标题包含关键字（忽略大小写）"}


def open_report(path):
    if os.name == "nt":
        os.startfile(str(path))
        return True
    if str(path).startswith("/mnt/") and shutil.which("powershell.exe"):
        win = subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
        # EncodedCommand avoids shell interpolation of the path.
        import base64
        script = "Start-Process -FilePath '" + win.replace("'", "''") + "'"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", encoded], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    return webbrowser.open(path.as_uri())


def error_report(current, bug_id, title, route, reason, base_url=""):
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    path = root(current) / str(bug_id) / "errors" / run_id / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    # URLs with credentials/query strings are never included in the report.
    from urllib.parse import urlsplit, urlunsplit
    u = urlsplit(base_url)
    host = u.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    try:
        if u.port:
            host += ":" + str(u.port)
    except ValueError:
        host = ""
    url = urlunsplit((u.scheme, host, u.path.rstrip("/") + "/bug-view-%s.html" % bug_id, "", "")) if u.scheme in ("http", "https") else ""
    rows = {"Bug ID": bug_id, "禅道标题": title, "匹配依据": route.get("reason", ""),
            "命中规则": json.dumps(route.get("rules", []), ensure_ascii=False),
            "目标工作区": route.get("workspace", ""), "目标分支": route.get("branch", ""),
            "异常原因": reason, "处理结果": "未开始修复；未创建 worktree；未提交代码。待重试。",
            "恢复方法": "修正 routes.json 或准备目标工作区及分支，然后执行 retry 或重新发送该 Bug 的通知。"}
    body = "".join("<tr><th>%s</th><td>%s</td></tr>" % (html.escape(str(k)), html.escape(str(v))) for k, v in rows.items())
    path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Bug #%s 工作区异常</title>'
                    '<style>body{font:16px sans-serif;max-width:1000px;margin:40px auto;padding:0 20px}table{border-collapse:collapse;width:100%%}th,td{border:1px solid #ddd;padding:12px;text-align:left;overflow-wrap:anywhere}th{width:140px}h1{color:#b42318}</style>'
                    '<h1>Bug #%s 工作区异常</h1><table>%s</table>%s</html>' %
                    (html.escape(str(bug_id)), html.escape(str(bug_id)), body,
                     '<p><a href="%s">查看禅道 Bug</a></p>' % html.escape(url, quote=True) if url else ''), encoding="utf-8")
    result = {"ok": False, "status": "workspace_error", "bug_id": str(bug_id), "html_report": str(path),
              "error": reason, "route": route}
    try:
        result["browser_opened"] = bool(open_report(path))
        if not result["browser_opened"]:
            result["browser_error"] = "默认浏览器未能打开报告"
    except Exception as exc:
        result.update(browser_opened=False, browser_error=str(exc)[:300])
    save(path.with_suffix(".json"), result)
    return result


def validate_workspace(route):
    p = Path(route["workspace"])
    if not p.is_dir():
        raise RouteError("指定工作区不存在或不是目录: " + str(p))
    top = Path(text(p, "rev-parse", "--show-toplevel")).resolve()
    if top != p:
        raise RouteError("指定路径不是 Git 工作区根目录")
    branch = text(p, "branch", "--show-current")
    if branch != route["branch"]:
        raise RouteError("当前分支 %s 与指定分支 %s 不一致" % (branch or "detached HEAD", route["branch"]))
    gd = Path(text(p, "rev-parse", "--absolute-git-dir"))
    if any((gd / n).exists() for n in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG")):
        raise RouteError("工作区正在合并、变基或其他 Git 操作中")
    return p


@contextmanager
def active_execution(record):
    """OS locks release on process death, while persistent reservations remain."""
    with ExitStack() as stack:
        for name in sorted(record.get("locks", [])):
            handle = stack.enter_context(Path(name + ".active").open("a+b"))
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    stack.callback(lambda h=handle: (h.seek(0), msvcrt.locking(h.fileno(), msvcrt.LK_UNLCK, 1)))
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    stack.callback(lambda h=handle: fcntl.flock(h.fileno(), fcntl.LOCK_UN))
            except OSError as exc:
                raise Busy("当前 Bug 的修复会话仍在运行，等待其结束") from exc
        yield


def reserve(project, bug_id, route, reuse=False):
    """Atomic persistent locks: retained on failure, released only after completion.

    Multi-key attempts never wait while holding a partial reservation.
    """
    p = validate_workspace(route)
    common = Path(text(p, "rev-parse", "--git-common-dir"))
    common = (p / common).resolve() if not common.is_absolute() else common.resolve()
    keys = ["branch:" + route["branch"], "workspace:" + os.path.normcase(str(p))]
    locks = [common / "zentao-bugfix-locks" / hashlib.sha256(k.encode()).hexdigest() for k in keys]
    record = load_record(project, bug_id)
    if reuse and record and record.get("locks"):
        with active_execution(record):
            pass
    token = record["run_id"] if reuse and record and record.get("mode") == "inplace" else uuid.uuid4().hex
    owner = {"bug_id": str(bug_id), "project": str(Path(project).resolve()), "run_id": token}
    created = []
    try:
        for lock in locks:
            lock.parent.mkdir(parents=True, exist_ok=True)
            try:
                lock.mkdir()
            except FileExistsError:
                try:
                    same = reuse and read(lock / "owner.json") == owner
                except (OSError, ValueError):
                    same = False
                if not same:
                    raise Busy("分支或工作区被占用，等待前一 Bug 完成: " + str(lock))
            else:
                created.append(lock)
                save(lock / "owner.json", owner)
        with active_execution({"locks": [str(lock) for lock in locks]}):
            pass
    except Exception:
        for lock in created:
            shutil.rmtree(lock)
        raise
    return token, [str(lock) for lock in locks]


def release(record):
    for name in record.get("locks", []):
        p = Path(name)
        if p.exists() and read(p / "owner.json").get("run_id") == record["run_id"]:
            shutil.rmtree(p)


def operational(path):
    return path == ".agents" or path.startswith(".agents/")


def snapshot(repo):
    # Include staged/unstaged bytes, untracked files, deletions and symlinks.
    names = set(os.fsdecode(n) for n in git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0") if n)
    names.update(os.fsdecode(n) for n in git(repo, "diff", "--name-only", "-z", "HEAD").split(b"\0") if n)
    index = {}
    for item in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
        if item:
            header, name = item.split(b"\t", 1)
            index.setdefault(os.fsdecode(name), []).append(header.decode("ascii"))
    entries = {}
    for name in sorted(names):
        if operational(name):
            continue
        p = Path(repo) / name
        if p.is_symlink():
            content = b"link:" + os.fsencode(os.readlink(p))
        elif p.is_file():
            content = p.read_bytes()
        elif not p.exists():
            content = b"deleted:"
        else:
            content = ("directory:" + repr(index.get(name))).encode()
        entries[name] = {"sha256": hashlib.sha256(content).hexdigest(),
                         "mode": p.lstat().st_mode if p.exists() or p.is_symlink() else 0,
                         "index": index.get(name, [])}
    dirty = set(os.fsdecode(n) for n in git(repo, "diff", "--cached", "--name-only", "-z").split(b"\0") if n)
    dirty.update(os.fsdecode(n) for n in git(repo, "diff", "--name-only", "-z").split(b"\0") if n)
    dirty.update(os.fsdecode(n) for n in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if n)
    return {"head": text(repo, "rev-parse", "HEAD"), "entries": entries,
            "dirty": sorted(n for n in dirty if not operational(n))}


def changed(before, after):
    return sorted(n for n in set(before["entries"]) | set(after["entries"])
                  if before["entries"].get(n) != after["entries"].get(n))


def ready(project, bug_id):
    rec = load_record(project, bug_id)
    if not rec or rec.get("mode") != "inplace":
        raise RouteError("ready 仅用于绑定工作区")
    p = validate_workspace(rec["route"])
    if rec.get("analysis_sealed"):
        rec["html_reports"] = _reports.render_reports(rec["report_dir"], names=("analysis.md", "solution.md"), require_complete=True)
        save(record_path(project, bug_id), rec)
        return rec
    if snapshot(p) != rec["snapshot"]:
        raise RouteError("分析文档完成前代码或暂存区已改变，禁止开始修复")
    docs = {}
    for name in ("analysis.md", "solution.md"):
        path = Path(rec["report_dir"]) / name
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not content.strip() or "（待填写" in content:
            raise RouteError(name + " 未完成")
        docs[name] = hashlib.sha256(content.encode()).hexdigest()
    html_reports = _reports.render_reports(rec["report_dir"], names=("analysis.md", "solution.md"), require_complete=True)
    rec.update(analysis_sealed=docs, status="repairing", html_reports=html_reports)
    save(record_path(project, bug_id), rec)
    return rec


def finish(project, bug_id, files, check_command, no_change=False):
    rec = load_record(project, bug_id)
    if not rec:
        raise RouteError("先执行 prepare")
    # Serialize even two accidental finish invocations for the same Bug.
    with active_execution({"locks": [name + ".finish" for name in rec.get("locks", [])]}):
        return _finish(project, bug_id, files, check_command, no_change)


def _finish(project, bug_id, files, check_command, no_change=False):
    rec = load_record(project, bug_id)
    if not rec or rec.get("mode") != "inplace":
        raise RouteError("finish 仅用于已 prepare 的绑定工作区")
    if rec.get("status") in ("committed", "no_change"):
        rec["html_reports"] = _reports.render_reports(rec["report_dir"], require_complete=True)
        save(record_path(project, bug_id), rec)
        release(rec)
        return rec
    if not rec.get("analysis_sealed"):
        raise RouteError("必须先执行 ready，证明分析与方案在代码修复之前完成")
    p = validate_workspace(rec["route"])
    for name in rec["locks"]:
        if read(Path(name) / "owner.json").get("run_id") != rec["run_id"]:
            raise RouteError("工作区锁不属于本次运行")
    report = Path(rec["report_dir"])
    for name in ("analysis.md", "solution.md", "fix-report.md"):
        doc = report / name
        if not doc.is_file() or not doc.read_text(encoding="utf-8").strip() or "（待填写" in doc.read_text(encoding="utf-8"):
            raise RouteError(name + " 尚未完整落盘")
    rec["html_reports"] = _reports.render_reports(report, require_complete=True)
    before = rec["snapshot"]
    for name, digest in rec["analysis_sealed"].items():
        if hashlib.sha256((report / name).read_text(encoding="utf-8").encode()).hexdigest() != digest:
            raise RouteError("分析/方案在 ready 后发生变化；请复核并保留现场，不自动提交")
    if not check_command:
        raise RouteError("必须提供 --check-command 验证命令；禁止绕过验证提交")
    # On Windows preserve backslashes in paths; remove only surrounding quotes.
    cmd = shlex.split(check_command, posix=os.name != "nt")
    if os.name == "nt":
        cmd = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'" else arg for arg in cmd]
    if not cmd:
        raise RouteError("验证命令不能为空")
    result = subprocess.run(cmd, cwd=str(p), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (report / "validation.log").write_bytes(result.stdout)
    rec["validation"] = {"command": cmd, "returncode": result.returncode}
    save(record_path(project, bug_id), rec)
    if result.returncode:
        raise RouteError("验证失败，分支队列暂停；详见 validation.log")
    after = snapshot(p)
    if after["head"] != before["head"]:
        raise RouteError("HEAD 已被外部修改，分支队列暂停")
    touched = changed(before, after)
    if set(touched) & set(before["dirty"]):
        raise RouteError("本次修改与已有开发改动混合，无法自动提交")
    files = list(dict.fromkeys(files))
    for name in files:
        if Path(name).is_absolute() or ".." in Path(name).parts or operational(name) or name.startswith("-") or "\\" in name:
            raise RouteError("提交路径必须为工作区内的相对代码路径: " + name)
    if no_change:
        if touched or files:
            raise RouteError("存在改动，不能声明无需代码修改")
        rec["status"] = "no_change"
    else:
        if not files or set(touched) != set(files):
            raise RouteError("--files 必须准确列出本次全部变更；禁止遗漏或夹带其他文件")
        env = os.environ.copy()
        index_fd, index_name = tempfile.mkstemp(prefix="zentao-index-", dir=str(Path(text(p, "rev-parse", "--absolute-git-dir"))))
        os.close(index_fd)
        os.unlink(index_name)
        env["GIT_INDEX_FILE"] = index_name
        try:
            git(p, "read-tree", "HEAD", env=env)
            git(p, "add", "--", *files, env=env)
            staged = {os.fsdecode(n) for n in git(p, "diff", "--cached", "--name-only", "-z", env=env).split(b"\0") if n}
            if staged != set(files):
                raise RouteError("暂存变更与本次 Bug 文件清单不一致")
            # Detect concurrent writes between validation and staging.
            if snapshot(p) != after:
                raise RouteError("验证后检测到外部修改，停止提交")
            validate_workspace(rec["route"])
            title = str(rec.get("title", "")).replace("\n", " ").replace("\r", " ")[:150]
            git(p, "commit", "-m", "fix(zentao): 修复 Bug #%s %s" % (bug_id, title), env=env)
            commit = text(p, "rev-parse", "HEAD")
            rec.update(commit=commit, status="commit_created")
            save(record_path(project, bug_id), rec)
            if text(p, "rev-parse", "HEAD^") != before["head"]:
                raise RouteError("提交父节点不符，队列暂停")
            committed = {os.fsdecode(n) for n in git(p, "diff", "HEAD^", "HEAD", "--name-only", "-z").split(b"\0") if n}
            if committed != set(files):
                raise RouteError("Git hook 改变提交文件清单，队列暂停")
            # Update only the initially clean selected paths in the real index.
            for name in files:
                entry = git(p, "ls-tree", "-z", "HEAD", "--", name)
                if entry:
                    header, _ = entry.rstrip(b"\0").split(b"\t", 1)
                    mode, _, oid = header.decode().split()
                    git(p, "update-index", "--add", "--cacheinfo", mode, oid, name)
                else:
                    git(p, "update-index", "--force-remove", "--", name)
            validate_workspace(rec["route"])
            now = snapshot(p)
            if set(now["dirty"]) != set(before["dirty"]):
                raise RouteError("提交后仍有额外变更，队列暂停")
            if any(now["entries"].get(n) != before["entries"].get(n) for n in before["dirty"]):
                raise RouteError("已有开发改动发生变化，队列暂停")
            rec.update(status="committed", files=files)
        finally:
            Path(index_name).unlink(missing_ok=True)
            Path(index_name + ".lock").unlink(missing_ok=True)
    rec["ok"] = True
    meta = read(report / "meta.json")
    meta.update(status=rec["status"], commit=rec.get("commit"), run_id=rec["run_id"], validation=rec["validation"], analysis_sealed=rec["analysis_sealed"])
    save(report / "meta.json", meta)
    with (report / "fix-report.md").open("a", encoding="utf-8") as f:
        f.write("\n\n## 最终提交结果\n\n状态：%s\n\nCommit：`%s`\n" % (rec["status"], rec.get("commit", "无需代码修改")))
    rec["html_reports"] = _reports.render_reports(report, require_complete=True)
    meta["html_reports"] = rec["html_reports"]
    save(report / "meta.json", meta)
    save(record_path(project, bug_id), rec)
    release(rec)
    return rec
