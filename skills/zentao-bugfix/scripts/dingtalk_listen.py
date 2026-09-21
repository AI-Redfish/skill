#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""zentao-bugfix skill · 钉钉消息监听器（全自动触发禅道 bug 修复）

纯标准库、无第三方依赖。Windows 原生 Python 与 WSL/Linux 均可运行。
推荐 uv 隔离运行：uv run --no-project scripts/dingtalk_listen.py <子命令>

功能链路：
    监听多个指定人员/机器人的钉钉单聊消息（dws Stream 长连接 + 定时轮询
    「过去X分钟」消息的拉取兜底，message_id 去重，两通道互为冗余）
    → 消息交给本地 Agent（pi/codex/claude/custom）无头提取"是否修 bug + bugId"
    → 命中则自动执行 zentao-bugfix 全流程（bugfix.py prepare 拉取禅道 bug、
       建 worktree，再由同一 Agent 无头会话分析修复、生成报告）
    → 全程结果只写本地日志（启动工作空间 .agents/logs/），不发钉钉回执。

配置（**启动时所在工作空间**的 .agents/.env，KEY=VALUE；首次运行交互式收集并保存。
旧版存于 skill 目录 .agents/.env，仅只读兜底，首次 save-config 自动迁移）：
    ZENTAO_BASE_URL / ZENTAO_ACCOUNT / ZENTAO_PASSWORD   禅道（自动修复必需）
    DWS_LISTEN_USERS=李四,张三                            监听人员（逗号分隔；
                                                          只监听机器人时可留空）
    DWS_LISTEN_BOTS=通知机器人                              监听机器人（可选）
    BUGFIX_BASE_BRANCH=dev/v6.0.6.3                     worktree 基准分支（可选）
    TARGET_PROJECT_PATH=D:\\path\\to\\repo                目标仓库（缺省=启动目录）
    AGENT_TYPE=pi|codex|claude|custom                     执行 Agent（缺省=自动探测）
    AGENT_MODEL=provider-x/model-y                     Agent 模型（provider/model 或模型名）
    AGENT_CUSTOM_CMD=dsh -p --model {model} {prompt}      custom 适配器命令模板（可选）
    LISTEN_MODE=auto                                     auto=推送+拉取双通道(默认)/stream/poll
    POLL_INTERVAL_SECONDS=20                             拉取兜底轮询间隔（可选，默认20秒）
    POLL_LOOKBACK_MINUTES=10                             兜底每轮重扫「过去X分钟」窗口（默认10）
    POLL_MAX_CATCHUP_MINUTES=60                          停机后兜底最多回看分钟数（默认60）

Agent/模型选择优先级：命令行参数 > .env > 自动探测当前 pi 会话 > 交互询问。
目标仓库优先级：.env 的 TARGET_PROJECT_PATH > 启动时所在项目目录。
注意：配置/日志/守护状态均锚定启动时所在工作空间（.agents/），start/status/stop
需在同一工作空间目录执行；不要在 skill 目录内运行，避免产生嵌套 .agents。

子命令：
    start [--foreground] [--agent T] [--model M]      启动监听（默认后台守护；配置缺失退出码 2）
    status                                            查看运行状态（JSON）
    stop                                              停止监听（优雅退出）
    config-status                                     检查配置完整性（JSON，密码脱敏）
    save-config KEY=VALUE...                          保存/合并写入 .agents/.env
    test-extract <消息文本>                           手动测试意图提取（不监听）

配置缺失时脚本不交互提问（避免无终端环境卡死）：退出码 2 并列出缺失键，
由调用方（AI）按双闭环逐项向用户索取后 save-config 写入，再重新执行。

前置条件：dws 已安装且已登录（dws auth login）；pi/codex/claude 已登录对应服务。
已知限制：dws 登录账号自己发出的消息不会进入事件流（钉钉官方过滤，非本脚本缺陷）。

退出码：0 成功；2 配置/参数错误；3 运行环境错误（dws 未登录/未安装等）。

排障日志（均在启动工作空间 .agents/logs/）：start.log 记录启动全过程与失败原因；
listener.log 为运行主日志；events.log 为原始消息；fix-<bugId>.log 含修复会话输出末尾
与 [VERIFY] 产物校验结果（无头会话退出码 0 不代表流程完成，以 worktree/meta.json
等文件证据为准）；status 的 last_fix 字段展示最近一次修复结果。
"""
import argparse
import json
import os
import queue as queue_mod
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
# 运行时基准 = 启动时所在工作空间：配置与日志一律写 <工作空间>/.agents/，
# 不写 skill 目录（skill 安装在 <工作空间>/.agents/skills/ 下时避免嵌套 .agents）。
# start/status/stop 需在同一工作空间目录执行（pid/state 锚定启动目录）。
BASE_DIR = Path.cwd().resolve()
ENV_FILE = BASE_DIR / ".agents" / ".env"
LOG_DIR = BASE_DIR / ".agents" / "logs"
LEGACY_ENV_FILE = SKILL_DIR / ".agents" / ".env"   # 旧版位置：只读兜底 + 迁移源
STATE_FILE = LOG_DIR / "state.json"
PID_FILE = LOG_DIR / "listener.pid"
STOP_FILE = LOG_DIR / "stop.flag"
PROCESSED_FILE = LOG_DIR / "processed-ids.json"
EXTRACT_TIMEOUT = 300        # 意图提取超时（秒）
FIX_TIMEOUT = 7200           # 自动修复会话超时（秒）
RESTART_BACKOFF = (5, 15, 60, 300)   # dws 子进程退出后的重启退避（秒）
PROCESSED_MAX = 1000         # message_id 去重环形容量
POLL_INTERVAL = 20           # 拉取兜底轮询间隔（秒，可用 POLL_INTERVAL_SECONDS 覆盖）
POLL_LOOKBACK_MIN = 10       # 兜底每轮重扫「过去X分钟」窗口（自愈：不依赖水位正确性）
POLL_MAX_CATCHUP_MIN = 60    # 水位过旧（停机等）时最多回看上限（分钟）
STREAM_STABLE_SEC = 600      # 推送流稳定运行超过该时长后重置重启退避计数

REQUIRED_KEYS = ["ZENTAO_BASE_URL", "ZENTAO_ACCOUNT", "ZENTAO_PASSWORD"]
KEY_HELP = {
    "DWS_LISTEN_USERS": "监听人员姓名，多个用英文逗号分隔（如：李四,张三）；"
                        "只监听机器人时可留空（需配 DWS_LISTEN_BOTS）",
    "DWS_LISTEN_BOTS": "监听机器人名称，多个逗号分隔（可留空）",
    "ZENTAO_BASE_URL": "禅道站点根地址（如 http://host:port）",
    "ZENTAO_ACCOUNT": "禅道登录账号",
    "ZENTAO_PASSWORD": "禅道登录密码（敏感，仅存本地 .env）",
    "TARGET_PROJECT_PATH": "目标项目仓库绝对路径（留空=启动时所在目录）",
    "AGENT_TYPE": "执行 Agent：pi / codex / claude / custom（留空=自动探测当前会话）",
    "AGENT_MODEL": "Agent 模型（pi 用 provider/model，codex/claude 用模型名）",
    "AGENT_CUSTOM_CMD": "custom 适配器命令模板，占位符 {model} {prompt}",
    "BUGFIX_BASE_BRANCH": "worktree 基准分支（可选；优先级：.env > 对话询问 > 仓库当前分支）",
    "LISTEN_MODE": "监听模式 auto/stream/poll（默认 auto：推送+拉取双通道，自动互为兜底）",
    "POLL_INTERVAL_SECONDS": "拉取兜底轮询间隔秒数（默认 20）",
    "POLL_LOOKBACK_MINUTES": "兜底每轮重扫的「过去X分钟」窗口（默认 10；调大更抗丢消息）",
    "POLL_MAX_CATCHUP_MINUTES": "停机/水位过旧时兜底最多回看的分钟数（默认 60）",
}


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)            # pythonw/计划任务等无 stdout 环境下静默
    except Exception:
        pass
    try:                                   # 运行日志同步落盘（会话关闭后仍可排查）
        write_log("listener.log", line)
    except OSError:
        pass


def write_log(name, text):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / name).open("a", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


# ---------------------------------------------------------------- 配置(.env)

def _parse_env_file(path):
    cfg = {}
    if path.is_file():
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def load_env(path=None):
    """读取配置：优先 <工作空间>/.agents/.env。

    工作空间无 .env 而旧版位置（skill 目录 .agents/.env）存在时，只读兜底读取
    并提示迁移（save-config 会自动整体迁移到工作空间）。显式传入 path 时只读该文件。
    """
    if path is not None:
        return _parse_env_file(Path(path))
    cfg = _parse_env_file(ENV_FILE)
    if not cfg and LEGACY_ENV_FILE.is_file() and LEGACY_ENV_FILE != ENV_FILE:
        cfg = _parse_env_file(LEGACY_ENV_FILE)
        log("[warn] 使用旧版配置位置 %s（skill 目录内，只读兜底）；"
            "运行 save-config 任意一项即可自动迁移到 %s" % (LEGACY_ENV_FILE, ENV_FILE))
    return cfg


def migrate_legacy_env():
    """旧版配置迁移：skill 目录 .agents/.env 存在而工作空间 .env 不存在时整体拷贝。"""
    if LEGACY_ENV_FILE.is_file() and not ENV_FILE.is_file() and LEGACY_ENV_FILE != ENV_FILE:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LEGACY_ENV_FILE, ENV_FILE)
        log("[info] 旧版配置已迁移到 %s（旧文件保留，可手动删除）" % ENV_FILE)


def save_env(path, updates):
    old = {}
    lines = []
    if path.is_file():
        raw = path.read_text(encoding="utf-8-sig").splitlines()
        for ln in raw:
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                old[s.split("=", 1)[0].strip()] = ln
        lines = [ln for ln in raw if (ln.strip().startswith("#")
                 or "=" not in ln
                 or ln.strip().split("=", 1)[0].strip() not in updates)]
    for k, v in updates.items():
        lines.append("%s=%s" % (k, v))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def missing_keys(cfg, required=REQUIRED_KEYS):
    miss = [k for k in required if not cfg.get(k)]
    # 监听名单：人员与机器人至少其一（只监听机器人时 DWS_LISTEN_USERS 可留空）
    if required is REQUIRED_KEYS and not miss \
            and not (cfg.get("DWS_LISTEN_USERS") or cfg.get("DWS_LISTEN_BOTS")):
        miss.append("DWS_LISTEN_USERS")
    return miss


def mask(v):
    return (v[:3] + "***") if v and len(v) > 3 else ("***" if v else "")


def _positive_int(val, name, default):
    """解析正整数配置（空/None 用默认值；非正数报配置错，退出码 2）。"""
    s = str(val).strip() if val is not None else ""
    if not s:
        return default
    try:
        n = int(float(s))
    except ValueError:
        raise SystemExit("%s 需为正整数，当前: %s" % (name, s))
    if n <= 0:
        raise SystemExit("%s 需为正整数，当前: %s" % (name, s))
    return n


# ---------------------------------------------------------------- 工具函数

def creation_flags():
    """Windows 下子进程隐藏控制台窗口（CREATE_NO_WINDOW，全程不弹黑窗）；其他平台返回 0。"""
    return 0x08000000 if os.name == "nt" else 0


def find_dws():
    for name in (os.environ.get("DWS_PATH"), "dws", "dws.exe"):
        if name and shutil.which(name):
            return shutil.which(name)
    raise SystemExit("未找到 dws 命令，请先安装并加入 PATH，或设置 DWS_PATH")


def run_dws(args, timeout=60):
    """执行一次性 dws 命令，返回 stdout 文本；失败抛异常。"""
    cmd = [find_dws()] + args
    p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                       creationflags=creation_flags())
    out = p.stdout.decode("utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("dws %s 失败(%d): %s" % (
            args[:2], p.returncode, (p.stderr or b"").decode("utf-8", "replace")[:300]))
    return out


def parse_json_loose(text):
    """从 Agent 输出中宽松提取第一个 JSON 对象（容忍 ```json 围栏与前后杂文）。"""
    text = re.sub(r"```(?:json)?", "", text)
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    raise ValueError("输出中未找到合法 JSON: %s" % text[:200])


def _wsl_to_win_path(p):
    """WSL 路径转 Windows 形式：/mnt/d/x → D:\\x（非 WSL 路径原样返回）。"""
    m = re.match(r"^/mnt/([a-z])/(.*)$", p)
    if not m:
        return p
    return "%s:\\%s" % (m.group(1).upper(), m.group(2).replace("/", "\\"))


def detect_pi_session_model(root=None, cwd=None):
    """在 pi 会话库中定位 cwd 对应的最新会话，返回其 provider/modelId。

    不依赖目录名映射规则（会变），直接读会话文件首行的 cwd 字段精确匹配。
    """
    if root is None:
        home = Path(os.environ.get("USERPROFILE", str(Path.home()))) if os.name == "nt" \
            else Path.home()
        root = home / ".pi" / "agent" / "sessions"
    root = Path(root)
    cwd = cwd or os.getcwd()
    candidates = {cwd, _wsl_to_win_path(cwd)}
    if not root.is_dir():
        return None
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
        if not d.is_dir():
            continue
        for sf in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            try:
                lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()[:25]
                head = json.loads(lines[0]) if lines else {}
                if head.get("type") != "session" or head.get("cwd") not in candidates:
                    continue
                for line in lines:
                    ev = json.loads(line)
                    if ev.get("type") == "model_change" and ev.get("provider") and ev.get("modelId"):
                        return "%s/%s" % (ev["provider"], ev["modelId"])
            except (json.JSONDecodeError, OSError):
                continue
    return None


# ---------------------------------------------------------------- Agent 适配器

def resolve_exe(name):
    """解析可执行文件真实路径（Windows 下 npm 垫片是 .cmd/.ps1，无 .exe）。"""
    found = shutil.which(name)
    if found:
        return found
    for ext in (".cmd", ".exe", ".bat"):
        found = shutil.which(name + ext)
        if found:
            return found
    return name          # 找不到时原样返回，交给系统报可理解的错


def _prompt_file(prompt):
    """提示词落盘为临时文件（Windows .cmd 垫片会破坏含引号/换行的长 argv）。"""
    d = LOG_DIR / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    f = d / ("prompt-%d.txt" % int(time.time() * 1000))
    f.write_text(prompt, encoding="utf-8")
    return f


class AgentAdapter:
    """把「意图提取」与「bug 修复」翻译为各 Agent CLI 的无头命令。

    方法返回 (命令列表, stdin文本或None)：提示词优先走文件/stdin，避开 argv 编码陷阱。
    """

    name = "?"

    def __init__(self, model):
        self.model = model
        self.exe = resolve_exe(self.name)

    def extract(self, prompt):
        raise NotImplementedError

    def fix(self, prompt, repo):
        raise NotImplementedError


class PiAdapter(AgentAdapter):
    name = "pi"

    def extract(self, prompt):
        return ([self.exe, "-p", "--no-session", "--no-extensions", "--no-skills",
                 "--no-prompt-templates", "--no-tools", "--model", self.model,
                 "@" + str(_prompt_file(prompt))], None)

    def fix(self, prompt, repo):
        return ([self.exe, "-p", "--model", self.model, "--skill", str(SKILL_DIR),
                 "@" + str(_prompt_file(prompt))], None)


class CodexAdapter(AgentAdapter):
    name = "codex"

    def extract(self, prompt):
        return ([self.exe, "exec", "-s", "read-only", "--skip-git-repo-check",
                 "-m", self.model], prompt)

    def fix(self, prompt, repo):
        # worktree 建在仓库同级目录，超出 workspace-write 沙箱范围，需完全访问
        return ([self.exe, "exec", "-s", "danger-full-access",
                 "--skip-git-repo-check", "-m", self.model], prompt)


class ClaudeAdapter(AgentAdapter):
    name = "claude"

    def extract(self, prompt):
        return ([self.exe, "-p", "--no-session-persistence", "--model",
                 self.model], prompt)

    def fix(self, prompt, repo):
        return ([self.exe, "-p", "--dangerously-skip-permissions",
                 "--model", self.model], prompt)


class CustomAdapter(AgentAdapter):
    name = "custom"

    def __init__(self, model, template):
        super().__init__(model)
        self.template = template or ""

    def _render(self, prompt):
        if not self.template or "{prompt}" not in self.template:
            raise RuntimeError("AGENT_CUSTOM_CMD 未配置或缺少 {prompt} 占位符")
        rendered = self.template.replace("{model}", self.model or "").replace(
            "{prompt}", prompt.replace('"', "'"))
        tokens = shlex.split(rendered, posix=(os.name != "nt"))
        if tokens:
            tokens[0] = resolve_exe(tokens[0])
        return tokens

    def extract(self, prompt):
        return (self._render(prompt), None)

    def fix(self, prompt, repo):
        return (self._render(prompt), None)


def build_adapter(cfg, args):
    """按 优先级(参数 > .env > 自动探测) 解析 Agent 类型与模型（全非交互）。

    解析失败时退出码 2，由调用方（AI）向用户索取后 save-config 重试。
    """
    atype = (getattr(args, "agent", None) or cfg.get("AGENT_TYPE") or "").strip().lower()
    model = (getattr(args, "model", None) or cfg.get("AGENT_MODEL") or "").strip()
    if not atype:
        detected = detect_pi_session_model()
        if detected:
            atype, model = "pi", model or detected
            log("自动探测到当前 pi 会话 Agent: %s" % detected)
        else:
            raise SystemExit("AGENT_TYPE 未配置且无法自动探测（当前目录无 pi 会话）；"
                             "请 save-config AGENT_TYPE=pi|codex|claude|custom 后重试")
    if atype not in ("pi", "codex", "claude", "custom"):
        raise SystemExit("不支持的 AGENT_TYPE: %s" % atype)
    if atype == "custom":
        model = model or "default"
        return CustomAdapter(model, cfg.get("AGENT_CUSTOM_CMD", ""))
    if not model:
        raise SystemExit("AGENT_MODEL 未配置（如 provider-x/model-y）；"
                         "请 save-config AGENT_MODEL=<模型> 后重试")
    return {"pi": PiAdapter, "codex": CodexAdapter,
            "claude": ClaudeAdapter}[atype](model)


EXTRACT_PROMPT = (
    "你是禅道 bug 修复触发器。分析下面这条来自钉钉的消息，判断它是否是"
    "「要求修复禅道 bug」的请求（特征：含禅道 bug 单号、bug 链接，或明确说修 bug/问题）。"
    "只输出一个 JSON 对象，不要输出任何其他文字。"
    "输出字段名必须严格使用：is_bugfix、bug_id、reason 三个字段，示例：\n"
    '{"is_bugfix": true, "bug_id": "12345", "reason": "用户要求修复禅道bug单12345"}\n'
    "判定规则：①消息只含一个数字（如\"74996\"）时视为修 bug 委托，is_bugfix=true 且 bug_id=该数字——"
    "用户向本助手发送孤立单号即是委托修复；②bug-view-XXXXX.html 链接中的 XXXXX 是单号，同样为 true；"
    "③与修 bug 无关的闲聊/问候/讨论才为 false 且 bug_id 为 null。\n"
    "消息内容：\n%s\n")


def run_agent_cmd(cmd, cwd=None, timeout=EXTRACT_TIMEOUT, stdin_text=None):
    """运行 Agent 无头命令，返回 stdout 文本。stdin_text 非空时经 stdin 输入提示词。"""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, env=env,
                       input=(stdin_text.encode("utf-8") if stdin_text else None),
                       creationflags=creation_flags())   # 后台执行：不弹任何黑窗
    out = p.stdout.decode("utf-8", errors="replace")
    err = p.stderr.decode("utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("Agent 命令失败(%d): %s" % (p.returncode, err[:300]))
    return out


def extract_bug_intent(adapter, sender, content):
    """调用 Agent 提取意图。返回 dict(is_bugfix, bug_id, reason)。

    容错字段别名（is_bug_fix_request/is_bug），防模型自造字段名。
    """
    msg = "发送人：%s\n消息正文：%s" % (sender, content)
    cmd, stdin_text = adapter.extract(EXTRACT_PROMPT % msg)
    out = run_agent_cmd(cmd, timeout=EXTRACT_TIMEOUT, stdin_text=stdin_text)
    data = parse_json_loose(out)
    is_bug = data.get("is_bugfix")
    if not isinstance(is_bug, bool):
        for alias in ("is_bug_fix_request", "is_bug", "bugfix"):
            if isinstance(data.get(alias), bool):
                is_bug = data[alias]
                break
    if not isinstance(is_bug, bool):
        raise ValueError("Agent 返回缺少 is_bugfix 布尔字段: %s" % str(data)[:200])
    data["is_bugfix"] = is_bug
    if is_bug:
        bug = str(data.get("bug_id") or data.get("bugId") or "").strip()
        data["bug_id"] = re.sub(r"\D", "", bug) or None
    return data


def sync_zentao_env_to_repo(repo):
    """把 skill .env 中的禅道配置同步到目标仓库 .agents/.env（bugfix.py 从那里读）。"""
    src = load_env()
    zentao = {k: v for k, v in src.items() if k.startswith("ZENTAO_")}
    if not zentao:
        raise RuntimeError("skill .env 缺少 ZENTAO_* 配置，无法自动修复")
    repo_env = Path(repo) / ".agents" / ".env"
    repo_cfg = load_env(repo_env)
    updates = {k: v for k, v in zentao.items() if repo_cfg.get(k) != v}
    if updates:
        save_env(repo_env, updates)
    # 防密钥入库：未忽略则追加 .gitignore
    gi = Path(repo) / ".gitignore"
    entry = ".agents/.env"
    need = True
    if gi.is_file():
        need = not any(ln.strip().rstrip("/") in (entry, ".agents") for ln in
                       gi.read_text(encoding="utf-8", errors="replace").splitlines())
    if need:
        with gi.open("a", encoding="utf-8") as f:
            f.write("\n# zentao-bugfix listener\n.agents/.env\n")
        log("已将 %s 追加到 %s（防止密钥入库）" % (entry, gi))


def build_fix_prompt(bug_id, base_branch=None):
    """构造修复会话提示词；base_branch 非空时显式传给 prepare（.env/用户指定优先）。"""
    branch_note = ("基准分支必须使用 %s（用户指定，禁止改用其他分支）。" % base_branch
                   if base_branch else
                   "prepare 不传基准分支参数，使用当前仓库所在分支。")
    barg = " " + base_branch if base_branch else ""
    return ("请使用 zentao-bugfix skill 修复禅道 bug %s。\n"
            "skill 目录：%s（先读其中 SKILL.md 了解完整流程）。\n"
            "%s\n"
            "步骤：1) 运行 `python %s prepare %s%s --project .`（或 uv run --no-project 同命令）；"
            "2) 按 SKILL.md 在 worktree 中分析根因并修复（禁止 commit/push）；"
            "3) 运行 report 子命令生成修复报告并补全（待填写）章节。"
            "全程遵守 SKILL.md 的边界约束，完成后输出根因一句话与报告路径。\n"
            % (bug_id, SKILL_DIR, branch_note,
               SKILL_DIR / "scripts" / "bugfix.py", bug_id, barg))


def verify_fix(bug_id, repo):
    """客观校验修复产物：prepare 成功的标志是 worktree 目录 + meta.json。

    无头 Agent 会话退出码 0 ≠ 流程完成（可能中途需要向用户提问后正常退出，
    例如禅道密码失效时只能“提问后结束”），必须以文件系统证据为准。
    返回 {"ok": bool, "worktree": str|None, "report": str|None}。
    """
    parent = Path(repo).resolve().parent
    for pat in ("bugfix_%s_*" % bug_id, "bugfix_%s" % bug_id):
        for wt in sorted(parent.glob(pat)):
            report_dir = wt / ".agents" / "bugfix" / str(bug_id)
            if wt.is_dir() and (report_dir / "meta.json").is_file():
                reports = sorted(p.name for p in report_dir.glob("fix-report*.md"))
                return {"ok": True, "worktree": str(wt),
                        "report": (str(report_dir / reports[0]) if reports else None)}
    return {"ok": False, "worktree": None, "report": None}


def run_auto_fix(adapter, bug_id, repo, base_branch=None):
    sync_zentao_env_to_repo(repo)
    prompt = build_fix_prompt(bug_id, base_branch)
    cmd, stdin_text = adapter.fix(prompt, repo)
    t0 = time.time()
    try:
        out = run_agent_cmd(cmd, cwd=str(repo), timeout=FIX_TIMEOUT, stdin_text=stdin_text)
    except subprocess.TimeoutExpired:
        write_log("fix-%s.log" % bug_id, "[TIMEOUT] 修复会话超时(%ds)" % FIX_TIMEOUT)
        return {"bug_id": bug_id, "ok": False, "error": "timeout", "worktree": None}
    except RuntimeError as e:
        write_log("fix-%s.log" % bug_id, "[ERROR] %s" % e)
        return {"bug_id": bug_id, "ok": False, "error": str(e)[:300], "worktree": None}
    tail = out.strip().splitlines()[-40:]
    v = verify_fix(bug_id, repo)
    write_log("fix-%s.log" % bug_id,
              "[cmd] %s\n[耗时] %.0fs\n[输出末尾]\n%s" % (
                  " ".join(cmd[:6]), time.time() - t0, "\n".join(tail)))
    if v["ok"]:
        write_log("fix-%s.log" % bug_id,
                  "[VERIFY] OK worktree=%s report=%s" % (v["worktree"], v["report"]))
        return {"bug_id": bug_id, "ok": True, "worktree": v["worktree"],
                "report": v["report"], "elapsed": int(time.time() - t0)}
    # 会话退出但无 worktree：prepare 未成功（常见：禅道密码失效/网络不通，
    # 无头会话无法向人提问只能“提问后结束”）——完整原因看本日志[输出末尾]
    write_log("fix-%s.log" % bug_id,
              "[VERIFY-FAIL] Agent 会话已结束但未检测到 worktree/报告 —— prepare 未成功，"
              "流程未完成。完整原因见上方[输出末尾]（常见：禅道密码失效，无头会话无法向人提问）")
    return {"bug_id": bug_id, "ok": False, "error": "no-worktree(prepare 未成功)",
            "worktree": None, "agent_exit": 0, "elapsed": int(time.time() - t0)}


# ---------------------------------------------------------------- 目标解析

def resolve_targets(users, bots):
    """把姓名/机器人名解析为 openDingTalkId 列表 [(名称, id, 类型)]。"""
    targets = []
    problems = []
    for name in filter(None, [x.strip() for x in users.split(",")]):
        try:
            data = parse_json_loose(run_dws(
                ["contact", "user", "search", "--query", name, "-f", "json"]))
            hits = [r for r in (data.get("result") or [])
                    if (r.get("name") == name or r.get("nick") == name)
                    and r.get("openDingTalkId")]
            if len(hits) != 1:
                problems.append("人员[%s]精确匹配 %d 个（需唯一）" % (name, len(hits)))
            else:
                targets.append((name, hits[0]["openDingTalkId"], "user"))
        except (RuntimeError, ValueError) as e:
            problems.append("人员[%s]解析失败: %s" % (name, e))
    for name in filter(None, [x.strip() for x in bots.split(",")]):
        try:
            data = parse_json_loose(run_dws(
                ["chat", "bot", "find", "--query", name, "--limit", "50", "-f", "json"]))
            hits = [b for b in ((data.get("result") or {}).get("bots") or [])
                    if b.get("name") == name and b.get("botOpenDingTalkId")]
            if len(hits) != 1:
                problems.append("机器人[%s]精确匹配 %d 个（需唯一）" % (name, len(hits)))
            else:
                targets.append((name, hits[0]["botOpenDingTalkId"], "bot"))
        except (RuntimeError, ValueError) as e:
            problems.append("机器人[%s]解析失败: %s" % (name, e))
    if not targets:
        raise SystemExit("无可监听目标：%s" % "；".join(problems or ["名单为空"]))
    for p in problems:
        log("警告: %s" % p)
    return targets


class DedupStore:
    """message_id 去重（内存 + 环形持久化）。"""

    def __init__(self, path=None):
        self.path = Path(path) if path else PROCESSED_FILE
        self.ids = deque(maxlen=PROCESSED_MAX)
        if self.path.is_file():
            try:
                self.ids.extend(json.loads(self.path.read_text(encoding="utf-8"))[-PROCESSED_MAX:])
            except (json.JSONDecodeError, OSError):
                pass
        self.lock = threading.Lock()

    def seen(self, mid):
        with self.lock:
            return mid in self.ids

    def add(self, mid):
        with self.lock:
            if mid not in self.ids:
                self.ids.append(mid)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(list(self.ids)), encoding="utf-8")


# ---------------------------------------------------------------- 拉取兜底(poll)

_POLL_STATE_LOCK = threading.Lock()
POLL_STATE_FILE = LOG_DIR / "poll-state.json"


def _load_poll_states():
    """读取各目标的拉取水位（canonical 归一化格式；损坏时视为空，自愈重建）。"""
    with _POLL_STATE_LOCK:
        try:
            return json.loads(POLL_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def _save_poll_state(name, wm):
    """读-改-写合并单个目标水位（多拉取线程并发写同一文件，锁内整体重读）。"""
    with _POLL_STATE_LOCK:
        try:
            states = json.loads(POLL_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            states = {}
        states[name] = wm
        try:
            POLL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            POLL_STATE_FILE.write_text(json.dumps(states), encoding="utf-8")
        except OSError:
            pass


def _norm_ts(v):
    """时间归一化为可字典序比较的定长数字串 YYYYmmddHHMMSSffffff；无法解析返回 ''。

    兼容常见格式：'2026-09-19 21:00:00'、ISO8601（'T'/毫秒/时区后缀，时区按同一
    墙钟忽略）、epoch 毫秒/秒（纯数字）。定长保证不同来源可直接比较。
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if s.isdigit() and len(s) in (10, 13):
        ep = int(s) / (1000.0 if len(s) == 13 else 1.0)
        return time.strftime("%Y%m%d%H%M%S", time.localtime(ep)) + "000000"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?", s)
    if not m:
        return ""
    frac = (m.group(7) or "")[:6].ljust(6, "0")
    return "".join(m.groups()[:6]) + frac


def _epoch_to_norm(ep):
    """epoch 秒 → canonical 归一化串（本地时区）。"""
    return time.strftime("%Y%m%d%H%M%S", time.localtime(ep)) + "000000"


def _norm_to_epoch(norm):
    """canonical 串 → epoch 秒（本地时区）；坏值抛 ValueError 由调用方容忍。"""
    return time.mktime(time.strptime(norm[:14], "%Y%m%d%H%M%S"))


def _fmt_local_rfc3339(epoch):
    """epoch 秒 → 本地时区 RFC3339 整秒串（dws --start/--end 只接受整秒）。"""
    lt = time.localtime(epoch)
    off = -time.altzone if (lt.tm_isdst and time.daylight) else -time.timezone
    return "%s%+03d:%02d" % (time.strftime("%Y-%m-%dT%H:%M:%S", lt),
                             int(off / 3600), abs(off) % 3600 // 60)


def poll_cutoff_epoch(wm, now=None, lookback_sec=None, max_catchup_sec=None):
    """计算本轮拉取窗口下界（epoch 秒）：min(水位, now-回看窗)，再被最大回看上限托底。

    - 水位正常时窗口 = 过去 X 分钟（自愈重扫，不依赖水位正确性）；
    - 停机后水位较旧 → 窗口前探到水位（补停机期间漏收的消息）；
    - 水位过旧（首次部署/长期停机）→ 最多回看 max_catchup，防远古消息重放。
    """
    now = time.time() if now is None else now
    lookback_sec = POLL_LOOKBACK_MIN * 60 if lookback_sec is None else lookback_sec
    max_catchup_sec = POLL_MAX_CATCHUP_MIN * 60 if max_catchup_sec is None else max_catchup_sec
    lower = now - lookback_sec
    if wm:
        try:
            lower = min(lower, _norm_to_epoch(wm))
        except (ValueError, OverflowError, OSError):
            pass
    return max(lower, now - max_catchup_sec)


def poll_messages(oid, start_epoch=None, limit=50):
    """拉取与指定 openDingTalkId 的单聊消息（拉取通道与推送流独立，互为冗余）。

    start_epoch 非空时用服务端时间窗（--start/--order asc，区间 [start, now)），
    避免依赖 limit 截断；旧版 dws 不认识该参数会报错，由调用方降级重试。
    兼容 result 包裹与裸信封两种输出形态。
    """
    args = ["chat", "+chat-messages", "--open-dingtalk-id", oid,
            "--limit", str(limit), "-f", "json"]
    if start_epoch is not None:
        args += ["--start", _fmt_local_rfc3339(start_epoch), "--order", "asc"]
    out = run_dws(args, timeout=60)
    data = parse_json_loose(out)
    env = data.get("result") if isinstance(data.get("result"), dict) else data
    return env.get("messages") or []


def normalize_poll_message(m):
    """把拉取到的消息归一化为事件流同构 dict（worker 无需区分来源）。"""
    return {
        "type": "poll_message",
        "sender": m.get("sender") or "",
        "sender_open_dingtalk_id": m.get("senderId") or "",
        "sender_type": m.get("senderType") or "",
        "content": m.get("text") or "",
        "message_id": m.get("messageId") or "",
        "conversation_id": m.get("conversationId") or "",
        "create_time": m.get("createTime") or "",
        "source": "poll",
    }


def pick_new_poll_messages(msgs, cutoff):
    """筛出时间窗内（归一化 createTime ≥ cutoff）的消息，按时间正序返回。

    语义是「窗口重扫」而非「水位增量」：窗口内已处理过的消息由调用方的
    DedupStore（message_id）去重，这样水位损坏/进程重启也不会永久漏消息。
    无法解析时间的消息保守丢弃（防重放）。
    """
    got = []
    for m in msgs:
        mn = _norm_ts(m.get("createTime"))
        if mn and mn >= cutoff:
            got.append((mn, m))
    got.sort(key=lambda t: t[0])
    return [m for _mn, m in got]


# ---------------------------------------------------------------- 监听核心

class Listener:
    """多目标 dws 监听 + 串行修复队列。"""

    def __init__(self, targets, adapter, repo, base_branch=None, mode="auto",
                 poll_interval=None, poll_lookback_min=None, poll_max_catchup_min=None):
        self.targets = targets
        self.adapter = adapter
        self.repo = repo
        self.base_branch = (base_branch or "").strip() or None
        self.mode = (mode or "auto").strip().lower()
        if self.mode not in ("auto", "stream", "poll"):
            raise SystemExit("LISTEN_MODE 必须是 auto/stream/poll: %s" % mode)
        # 拉取兜底参数（X 分钟窗口/同隔/停机回看上限，均可 .env 覆盖）
        self.poll_interval = _positive_int(poll_interval, "POLL_INTERVAL_SECONDS", POLL_INTERVAL)
        self.poll_lookback_min = _positive_int(poll_lookback_min, "POLL_LOOKBACK_MINUTES", POLL_LOOKBACK_MIN)
        self.poll_max_catchup_min = _positive_int(
            poll_max_catchup_min, "POLL_MAX_CATCHUP_MINUTES", POLL_MAX_CATCHUP_MIN)
        self.dedup = DedupStore()
        self.queue = queue_mod.Queue()
        self.procs = {}          # name -> {"proc", "restarts", "last_event"}
        self.stop_flag = threading.Event()
        self.state_lock = threading.Lock()
        self.stats = {"processed": 0, "fix_ok": 0, "fix_fail": 0}

    # ---- dws 子进程管理 ----
    def _spawn(self, name, oid):
        cmd = [find_dws(), "event", "+listen-im", "--kind", "sender",
               "--open-dingtalk-id", oid, "--events", "message",
               "--duration", "0", "-f", "ndjson"]
        # stdin 保持打开：dws 把 stdin EOF 视为退出信号；关闭 stdin 即优雅停机
        # stderr 落盘（ready 标志/连接错误可观测，不与事件流混流）
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\u4e00-\u9fff-]", "_", name)
        errf = (LOG_DIR / ("dws-%s.log" % safe)).open("ab")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=errf,
                                creationflags=creation_flags())   # 无窗口后台运行
        return proc

    def _reader(self, name, oid):
        restarts = 0
        while not self.stop_flag.is_set():
            t0 = time.time()
            info = self.procs.get(name) or {}
            proc = self._spawn(name, oid)
            with self.state_lock:
                self.procs[name] = {"proc": proc, "restarts": restarts,
                                    "last_event": info.get("last_event")}
            log("[%s] dws 监听已启动 pid=%s" % (name, proc.pid))
            try:
                for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mid = ev.get("message_id")
                    if mid and self.dedup.seen(mid):
                        continue
                    if mid:
                        self.dedup.add(mid)
                    with self.state_lock:
                        if name in self.procs:
                            self.procs[name]["last_event"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    write_log("events.log", json.dumps(
                        {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "target": name, "event": ev}, ensure_ascii=False))
                    self.queue.put((name, ev))
            except Exception as e:                          # 读流异常：记日志后重启
                log("[%s] 读流异常: %s" % (name, e))
            if self.stop_flag.is_set():
                try:
                    proc.stdin.close()   # 优雅退出：dws 收到 EOF 自动退订清理
                    proc.wait(timeout=15)
                except Exception:
                    proc.kill()
                return
            if time.time() - t0 >= STREAM_STABLE_SEC:
                restarts = 0        # 稳定运行过一段时间的属于新故障：重置退避，避免累计放弃
            restarts += 1
            if restarts > len(RESTART_BACKOFF):
                log("[%s] 重启次数过多，放弃该目标" % name)
                return
            wait = RESTART_BACKOFF[min(restarts - 1, len(RESTART_BACKOFF) - 1)]
            log("[%s] dws 异常退出(rc=%s)，%ds 后第 %d 次重启"
                % (name, proc.returncode, wait, restarts))
            self.stop_flag.wait(wait)

    def _poll_reader(self, name, oid, ttype="user"):
        """拉取兜底：每 poll_interval 秒重扫「过去 X 分钟」窗口，补推送流丢的消息。

        自愈设计：不依赖单一水位的正确性——每轮都重扫时间窗（X 分钟），窗口内
        漏掉的消息（水位跳过/进程重启/限流截断）下一轮仍会被重新捞到；重复处理
        由 DedupStore 的 message_id 去重拦截。持久化水位只用于停机后把窗口
        向前延伸（上限 max_catchup 分钟，防首次部署/长期停机重放远古消息）。
        旧版 dws 不支持 --start 时自动降级为纯 limit 拉取 + 客户端窗口过滤。
        """
        wm = _norm_ts(_load_poll_states().get(name))    # 兼容旧版水位格式
        legacy = False
        lookback = self.poll_lookback_min * 60
        max_catchup = self.poll_max_catchup_min * 60
        while not self.stop_flag.is_set():
            self.stop_flag.wait(self.poll_interval)
            if self.stop_flag.is_set():
                return
            lower = poll_cutoff_epoch(wm, lookback_sec=lookback, max_catchup_sec=max_catchup)
            cutoff = _epoch_to_norm(lower)
            try:
                msgs = poll_messages(oid, None if legacy else lower - 1)
            except Exception as e1:
                if legacy:
                    log("[%s] 拉取失败(下次重试): %s" % (name, str(e1)[:200]))
                    continue
                legacy = True
                log("[%s] 带时间窗拉取失败，降级为 limit 拉取: %s" % (name, str(e1)[:200]))
                try:
                    msgs = poll_messages(oid)
                except Exception as e2:
                    log("[%s] 拉取失败(下次重试): %s" % (name, str(e2)[:200]))
                    continue
            newest = wm
            for m in pick_new_poll_messages(msgs, cutoff):
                mn = _norm_ts(m.get("createTime"))
                if mn and mn > newest:
                    newest = mn
                sid = str(m.get("senderId") or "").strip()
                stype = str(m.get("senderType") or "").lower()
                # 只处理目标发来的消息（单聊里非目标即为自己发出的）；senderId 缺失
                # 或机器人类型标记时放行，交给去重与意图提取兜底，防字段形态差异漏拉
                if sid and sid != oid and not (ttype == "bot"
                                               and ("bot" in stype or "app" in stype)):
                    continue
                mid = m.get("messageId")
                if mid and self.dedup.seen(mid):
                    continue
                if mid:
                    self.dedup.add(mid)
                ev = normalize_poll_message(m)
                write_log("events.log", json.dumps(
                    {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "target": name, "event": ev}, ensure_ascii=False))
                with self.state_lock:
                    if name in self.procs:
                        self.procs[name]["last_event"] = time.strftime("%Y-%m-%d %H:%M:%S")
                log("[%s] 拉取兜底命中消息 mid=%s" % (name, mid or "?"))
                self.queue.put((name, ev))
            if newest != wm:
                wm = newest
                _save_poll_state(name, wm)

    # ---- 串行处理 ----
    def _worker(self):
        while not self.stop_flag.is_set() or not self.queue.empty():
            try:
                name, ev = self.queue.get(timeout=2)
            except queue_mod.Empty:
                continue
            sender = ev.get("sender") or name
            content = str(ev.get("content") or "")
            if not content.strip():                     # 图片/文件等无文本消息：不可能含 bugId
                log("[%s] 消息无文本内容，跳过" % name)
                self.queue.task_done()
                continue
            try:
                intent = extract_bug_intent(self.adapter, sender, content)
            except Exception as e:                     # 提取失败不致命，记录后跳过
                log("[%s] 提取失败: %s" % (name, e))
                self.queue.task_done()
                continue
            self.stats["processed"] += 1
            if not intent.get("is_bugfix") or not intent.get("bug_id"):
                log("[%s] 非修bug消息(%s)，忽略" % (name, intent.get("reason", "")))
                self.queue.task_done()
                continue
            bug_id = intent["bug_id"]
            log("[%s] 命中 bug %s，开始自动修复 (repo=%s, agent=%s/%s)"
                % (name, bug_id, self.repo, self.adapter.name, self.adapter.model))
            result = run_auto_fix(self.adapter, bug_id, self.repo, self.base_branch)
            self.stats["fix_ok" if result.get("ok") else "fix_fail"] += 1
            self.stats["last_fix"] = dict(
                result, ts=time.strftime("%Y-%m-%d %H:%M:%S"))   # status 可见最近一次结果
            log("[bug %s] 修复会话结束: %s" % (bug_id, result))
            self.queue.task_done()

    def _save_state(self):
        with self.state_lock:
            targets = [{"name": n, "id": i, "restarts": self.procs.get(n, {}).get("restarts", 0),
                        "last_event": self.procs.get(n, {}).get("last_event")}
                       for n, i, _ in self.targets]
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "pid": os.getpid(), "started": self.started, "agent": self.adapter.name,
            "model": self.adapter.model, "repo": str(self.repo), "base_branch": self.base_branch,
            "targets": targets, "mode": self.mode, "queue": self.queue.qsize(),
            "poll": {"interval_s": self.poll_interval,
                     "lookback_min": self.poll_lookback_min,
                     "max_catchup_min": self.poll_max_catchup_min},
            "stats": self.stats, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    def run(self):
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        STOP_FILE.unlink(missing_ok=True)
        threads = []
        for n, i, _t in self.targets:
            if self.mode in ("auto", "stream"):
                threads.append(threading.Thread(target=self._reader, args=(n, i), daemon=True))
            if self.mode in ("auto", "poll"):
                threads.append(threading.Thread(
                    target=self._poll_reader, args=(n, i, _t), daemon=True))
        threads.append(threading.Thread(target=self._worker, daemon=True))
        for t in threads:
            t.start()
        note = {"auto": "（stream推送+poll拉取双通道：每%ds重扫过去%dmin，message_id去重）"
                % (self.poll_interval, self.poll_lookback_min),
                "poll": "（仅poll拉取：每%ds重扫过去%dmin，停机回看上限%dmin）"
                % (self.poll_interval, self.poll_lookback_min, self.poll_max_catchup_min),
                "stream": ""}[self.mode]
        log("监听就绪：%d 个目标 | agent=%s/%s | repo=%s | mode=%s%s"
            % (len(self.targets), self.adapter.name, self.adapter.model, self.repo,
               self.mode, note))
        try:
            while not STOP_FILE.is_file():
                alive = sum(1 for t in threads if t.is_alive())
                if alive <= 1:            # 只剩 worker：所有 reader 已放弃
                    log("所有监听目标线程已退出，主进程退出")
                    break
                self._save_state()
                time.sleep(5)
        finally:
            self.stop_flag.set()
            with self.state_lock:
                for info in self.procs.values():
                    try:
                        info["proc"].stdin.close()
                        info["proc"].wait(timeout=15)
                    except Exception:
                        try:
                            info["proc"].kill()
                        except Exception:
                            pass
            self._save_state()
            PID_FILE.unlink(missing_ok=True)
            STOP_FILE.unlink(missing_ok=True)
            log("监听已停止")


# ---------------------------------------------------------------- 守护进程管理

def _daemon_spawn(args, adapter):
    """以后台守护方式重新拉起自身（--foreground 模式）。

    显式传入已解析的 --agent/--model，确保子进程无终端环境下不再需要任何交互。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve()), "start", "--foreground",
           "--agent", adapter.name, "--model", adapter.model]
    out = (LOG_DIR / "daemon.out").open("ab")
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": out}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS|NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    time.sleep(2)
    log("后台守护已启动(agent=%s/%s)，日志: %s/daemon.out"
        % (adapter.name, adapter.model, LOG_DIR))


def _pid_alive(pid):
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                               capture_output=True, text=True,
                               creationflags=creation_flags())
            return str(pid) in (r.stdout or "")
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def resolve_repo(cfg):
    repo = cfg.get("TARGET_PROJECT_PATH", "").strip()
    if not repo:
        repo = os.getcwd()
    if not (Path(repo) / ".git").exists():
        raise SystemExit("目标仓库 %s 不是 git 仓库（请配置 TARGET_PROJECT_PATH 或在项目目录启动）" % repo)
    return Path(repo).resolve()


# ---------------------------------------------------------------- 子命令

def cmd_start(args):
    """启动监听。全阶段写入 .agents/logs/start.log：会话关闭后失败原因仍可排查。"""
    write_log("start.log", "[start] 开始 (cwd=%s, pid=%d, foreground=%s)"
              % (BASE_DIR, os.getpid(), bool(getattr(args, "foreground", False))))
    try:
        _cmd_start_impl(args)
    except SystemExit as e:
        write_log("start.log", "[start] 失败退出: %s" % (e.code if e.code is not None else 0))
        raise
    except Exception:
        import traceback
        write_log("start.log", "[start] 异常:\n%s" % traceback.format_exc())
        raise


def _cmd_start_impl(args):
    cfg = load_env()
    missing = missing_keys(cfg)
    write_log("start.log", "[start] 配置: %s"
              % ("缺失 %s" % missing if missing else "OK（env=%s）" % ENV_FILE))
    if PID_FILE.is_file():
        pid = int(PID_FILE.read_text().strip() or 0)
        if pid and _pid_alive(pid):
            write_log("start.log", "[start] 已在运行 (pid=%d)，拒绝重复启动" % pid)
            raise SystemExit("监听已在运行 (pid=%d)，可用 stop 子命令停止" % pid)
        PID_FILE.unlink(missing_ok=True)
    if missing:
        raise SystemExit("配置缺失: %s；请逐项向用户索取后 save-config 写入再重试"
                         % ", ".join(missing))
    adapter = build_adapter(cfg, args)
    write_log("start.log", "[start] Agent 解析: %s/%s" % (adapter.name, adapter.model))
    repo = resolve_repo(cfg)
    write_log("start.log", "[start] 目标仓库: %s" % repo)
    targets = resolve_targets(cfg.get("DWS_LISTEN_USERS", ""),
                              cfg.get("DWS_LISTEN_BOTS", ""))
    write_log("start.log", "[start] 监听目标(%d): %s"
              % (len(targets), ", ".join("%s(%s)" % (n, t) for n, _, t in targets)))
    if not args.foreground:
        _daemon_spawn(args, adapter)
        return
    write_log("start.log", "[start] 进入前台监听主循环")
    Listener(targets, adapter, repo, cfg.get("BUGFIX_BASE_BRANCH"),
             cfg.get("LISTEN_MODE", "auto"),
             cfg.get("POLL_INTERVAL_SECONDS"),
             cfg.get("POLL_LOOKBACK_MINUTES"),
             cfg.get("POLL_MAX_CATCHUP_MINUTES")).run()


def cmd_status(_args):
    result = {"running": False}
    if PID_FILE.is_file():
        pid = int(PID_FILE.read_text().strip() or 0)
        result["pid"] = pid
        result["running"] = bool(pid and _pid_alive(pid))
    if STATE_FILE.is_file():
        try:
            result.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    print(json.dumps(result, ensure_ascii=False, indent=1))


def cmd_stop(_args):
    if not PID_FILE.is_file():
        raise SystemExit("未发现运行中的监听（pid 文件不存在）")
    pid = int(PID_FILE.read_text().strip() or 0)
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text("stop\n")            # 守护进程轮询到即优雅退出
    for _ in range(12):
        time.sleep(2.5)
        if not _pid_alive(pid):
            log("监听已停止 (pid=%d)" % pid)
            return
    log("优雅停止超时，强制结束 pid=%d" % pid)
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"]
                   if os.name == "nt" else ["kill", "-9", str(pid)],
                   creationflags=creation_flags())


def cmd_config_status(_args):
    cfg = load_env()
    optional = ["DWS_LISTEN_BOTS", "BUGFIX_BASE_BRANCH", "TARGET_PROJECT_PATH",
                "AGENT_TYPE", "AGENT_MODEL", "AGENT_CUSTOM_CMD", "LISTEN_MODE",
                "POLL_INTERVAL_SECONDS", "POLL_LOOKBACK_MINUTES",
                "POLL_MAX_CATCHUP_MINUTES"]
    print(json.dumps({
        "env_file": str(ENV_FILE),
        "legacy_env_file": str(LEGACY_ENV_FILE),
        "legacy_in_use": bool(LEGACY_ENV_FILE.is_file()
                              and not ENV_FILE.is_file()
                              and LEGACY_ENV_FILE != ENV_FILE),
        "missing_required": missing_keys(cfg),
        "present": {k: (mask(v) if "PASSWORD" in k or "SECRET" in k else v)
                    for k, v in cfg.items()},
        "optional_keys": {k: KEY_HELP[k] for k in optional},
    }, ensure_ascii=False, indent=1))


def cmd_save_config(args):
    updates = {}
    for kv in args.pairs:
        if "=" not in kv:
            raise SystemExit("参数格式应为 KEY=VALUE: %s" % kv)
        k, v = kv.split("=", 1)
        updates[k.strip()] = v.strip()
    migrate_legacy_env()          # 旧版 skill 目录配置自动迁移到工作空间
    save_env(ENV_FILE, updates)
    cfg = load_env()
    print(json.dumps({"saved": sorted(updates),
                      "still_missing": missing_keys(cfg)}, ensure_ascii=False))


def cmd_test_extract(args):
    cfg = load_env()
    adapter = build_adapter(cfg, args)
    text = " ".join(args.text)
    if text.strip() == "-":                       # 从 stdin 读（避开 argv 编码/长度限制）
        raw = sys.stdin.buffer.read()
        for enc in ("utf-8", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
    result = extract_bug_intent(adapter, "manual-test", text)
    print(json.dumps(result, ensure_ascii=False, indent=1))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="zentao-bugfix 钉钉消息监听器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("start", cmd_start), ("status", cmd_status),
                     ("stop", cmd_stop), ("config-status", cmd_config_status),
                     ("save-config", cmd_save_config),
                     ("test-extract", cmd_test_extract)):
        sp = sub.add_parser(name)
        sp.set_defaults(func=fn)
        if name in ("start", "test-extract"):
            sp.add_argument("--agent", default="", help="pi/codex/claude/custom")
            sp.add_argument("--model", default="", help="模型（provider/model 或模型名）")
        if name == "start":
            sp.add_argument("--foreground", action="store_true", help="前台运行（默认后台守护）")
        if name == "save-config":
            sp.add_argument("pairs", nargs="+", help="KEY=VALUE ...")
        if name == "test-extract":
            sp.add_argument("text", nargs="+", help="要测试的消息文本")
    args = ap.parse_args()
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    args.func(args)


if __name__ == "__main__":
    main()
