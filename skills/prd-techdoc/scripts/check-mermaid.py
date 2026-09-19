# check-mermaid.py — Mermaid 全量校验（纯标准库，无第三方依赖；本地脚本，替代对预装 mmdc/Chrome 的强依赖）
# 行为：
#   1) .agents/.env 配置了 MMDC_PATH（或 PATH 中存在 mmdc）时：逐块真实渲染，通过标准 failures=0；
#   2) 未配置时：执行内置结构化 lint（图类型、空块、未闭合、引号不配对、未加引号的 ASCII 括号/竖线/冒号、
#      erDiagram/stateDiagram/sequenceDiagram 常见语法问题），输出 mode=lint；
#   3) 渲染全部失败（疑似渲染环境问题，如 CHROME_PATH 缺失）时：自动回退 lint 结果并提示 WARN。
# 用法:
#   uv run scripts/check-mermaid.py --md <doc.md> [--work-dir <dir>]
#   python scripts/check-mermaid.py --md <doc.md> [--work-dir <dir>]
# 退出码: 0 = failures=0；1 = 存在失败；2 = 输入问题。
# 本脚本只读文档，不修改文档；修改一律走主调用方。

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import import_agent_env  # noqa: E402

DIAGRAM_TYPES = (
    "graph|flowchart|stateDiagram|erDiagram|sequenceDiagram|classDiagram|journey|gantt|pie|"
    "mindmap|timeline|quadrantChart|requirementDiagram|gitGraph|sankey|xychart|block|packet|"
    "architecture|C4Context|C4Container|C4Component|C4Dynamic|C4Deployment"
)
TYPE_RE = re.compile(r"^(" + DIAGRAM_TYPES + r")\b")
# 复合形状优先：[[x]] 子程序、[(x)] 圆柱、((x)) 圆；再退单层 [x]/(x)/{x}/>x]（>x] 需紧跟节点 id，避免误匹配 --> 箭头）
SHAPE_RE = re.compile(
    r"\[\[([^\]]*)\]\]|\[\(([^\)\]]*)\)\]|\(\(([^\)]*)\)\)|\[([^\]]*)\]|\(([^\)]*)\)|\{([^\}]*)\}|(?<=[\w\)\]])>([^\]]*)\]"
)
FLOWCHART_META_LINE = re.compile(r"^\s*(linkStyle|classDef|class|style|click|init|direction)\b", re.IGNORECASE)
ER_TITLE = re.compile(r"^title\b")
ER_ENTITY_OPEN = re.compile(r"^[A-Za-z_]\w*\s*\{\s*$")
ER_ENTITY_CLOSE = re.compile(r"^\}\s*,?\s*$")
ER_REL = re.compile(r"^[A-Za-z_]\w*\s+[|\}\{\]\[\>\<o\*x\-\.\+]{2,12}\s*[A-Za-z_]\w*\s*:")
ER_ATTR = re.compile(r"^[A-Za-z_]\w*(\(\d+(,\d+)?\))?\s+[A-Za-z_]\w*(\s+(PK|FK|UK))?(\s+\"[^\"]*\")?\s*,?\s*$")
SEQ_OPEN = re.compile(r"^\s*(alt|opt|loop|par|critical|box|rect)\b", re.IGNORECASE)
SEQ_END = re.compile(r"^\s*end\b", re.IGNORECASE)


def lint_block(tag: str, start: int, text: str) -> list[str]:
    problems: list[str] = []
    raw = text.split("\n")
    code = [x for x in raw if not x.lstrip().startswith("%%")]
    non_empty = [x for x in code if x.strip()]
    if not non_empty:
        return [f"FAIL {tag} line={start}: EMPTY_BLOCK"]
    first = non_empty[0].strip()
    m = TYPE_RE.match(first)
    if not m:
        return [f"FAIL {tag} line={start}: UNKNOWN_DIAGRAM_TYPE '{re.sub(r'\s+.*$', '', first)}'"]
    dtype = m.group(1)
    if first.startswith("stateDiagram"):
        dtype = "stateDiagram"
    if first.startswith(("graph", "flowchart")):
        dtype = "flowchart"

    decl_idx = -1
    for j, x in enumerate(raw):
        if x.lstrip().startswith("%%"):
            continue
        if x.strip():
            decl_idx = j
            break

    for j, line in enumerate(raw):
        if j == decl_idx:
            continue
        if line.lstrip().startswith("%%"):
            continue
        if not line.strip():
            continue
        ln = start + 1 + j
        if line.count('"') % 2 != 0:
            problems.append(f"FAIL {tag} line={ln}: UNBALANCED_QUOTES '{line.strip()}'")
            continue
        residual = re.sub(r'"[^"]*"', "", line)
        if dtype == "flowchart":
            if FLOWCHART_META_LINE.match(line):
                continue
            for sm in SHAPE_RE.finditer(residual):
                label = "".join(g for g in sm.groups() if g is not None)
                if re.search(r"[()|:]", label):
                    problems.append(f"FAIL {tag} line={ln}: UNQUOTED_SPECIAL_CHAR_IN_LABEL '{line.strip()}'")
            for em in re.finditer(r"\|([^\|]*)\|", residual):
                if re.search(r"[():]", em.group(1)):
                    problems.append(f"FAIL {tag} line={ln}: UNQUOTED_SPECIAL_CHAR_IN_EDGE_LABEL '{line.strip()}'")
            if ":" in residual:
                problems.append(f"FAIL {tag} line={ln}: BARE_COLON '{line.strip()}'")
        elif dtype == "stateDiagram":
            if "-->" in line:
                before, after = line.split("-->", 1)
                rhs = after.split(":", 1)[0].strip()
                for side in (before.strip(), rhs):
                    if side == "" or (side != "[*]" and re.search(r"\s", side)):
                        problems.append(f"FAIL {tag} line={ln}: BAD_STATE_TOKEN '{line.strip()}'")
        elif dtype == "erDiagram":
            t = line.strip()
            ok = (
                ER_TITLE.match(t)
                or ER_ENTITY_OPEN.match(t)
                or ER_ENTITY_CLOSE.match(t)
                or ER_REL.match(t)
                or ER_ATTR.match(t)
            )
            if not ok:
                problems.append(f"FAIL {tag} line={ln}: ER_UNKNOWN_LINE '{t}'")
        elif dtype == "sequenceDiagram":
            t = line.strip()
            if "->" in t and ":" not in t:
                problems.append(f"FAIL {tag} line={ln}: SEQ_MESSAGE_MISSING_COLON '{t}'")

    if dtype == "erDiagram":
        opens = sum(1 for x in code if ER_ENTITY_OPEN.match(x.strip()))
        closes = sum(1 for x in code if ER_ENTITY_CLOSE.match(x.strip()))
        if opens != closes:
            problems.append(f"FAIL {tag} line={start}: ER_BRACE_MISMATCH open={opens} close={closes}")
    if dtype == "sequenceDiagram":
        opens = sum(1 for x in code if SEQ_OPEN.match(x))
        ends = sum(1 for x in code if SEQ_END.match(x))
        if opens != ends:
            problems.append(f"FAIL {tag} line={start}: SEQ_BLOCK_MISMATCH open={opens} end={ends}")
    return problems


def run_mmdc(mmdc: str, args: list[str]) -> tuple[int, str]:
    """跨平台调用 mmdc（Windows 下 .cmd/.bat 需经 cmd /c）。"""
    cmd = [mmdc]
    if os.name == "nt" and mmdc.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", mmdc]
    try:
        proc = subprocess.run(cmd + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, output
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def resolve_mmdc(env_map: dict[str, str]) -> str | None:
    configured = env_map.get("MMDC_PATH", "")
    if configured:
        if Path(configured).exists():
            return configured
        found = shutil.which(configured)
        if found:
            return found
        print("WARN MMDC_PATH 已配置但不可用，回退结构化 lint")
    # PATH 探测时优先可执行文件（mmdc.cmd/.exe），避免 .ps1 shim 的 stderr 干扰
    return shutil.which("mmdc") or shutil.which("mmdc.cmd") or shutil.which("mmdc.exe")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mermaid 全量校验")
    parser.add_argument("--md", required=True, help="被校验的技术文档路径")
    parser.add_argument("--work-dir", default=None, help="skill 运行时工作目录（.agents/.env 所在目录），默认当前目录")
    args = parser.parse_args()

    env_map = import_agent_env(args.work_dir)
    md_path = Path(args.md)
    if not md_path.is_file():
        print(f"ERROR doc not found: {args.md}")
        return 2
    lines = md_path.read_text(encoding="utf-8-sig").splitlines()

    blocks: list[tuple[int, str]] = []
    in_block = False
    start_line = 0
    buf: list[str] = []
    for i, t in enumerate(lines):
        if not in_block and re.match(r"^```mermaid\s*$", t):
            in_block = True
            start_line = i + 1
            buf = []
            continue
        if in_block and re.match(r"^```\s*$", t):
            in_block = False
            blocks.append((start_line, "\n".join(buf)))
            continue
        if in_block:
            buf.append(t)
    if in_block:
        print(f"FAIL b{len(blocks) + 1:03d} line={start_line}: UNCLOSED_MERMAID_BLOCK")
        print("mode=lint")
        print(f"mermaid_blocks={len(blocks) + 1} failures=1")
        return 1

    mmdc = resolve_mmdc(env_map)
    mode = "lint"
    failures = 0
    if mmdc:
        mode = "render"
        out_dir = Path(tempfile.gettempdir()) / "prd-techdoc-mermaid"
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.mmd"):
            old.unlink()
        cfg: dict = {"args": ["--no-sandbox", "--disable-gpu"]}
        chrome = env_map.get("CHROME_PATH", "")
        if chrome:
            cfg["executablePath"] = chrome
        pcfg = out_dir / "pcfg.json"
        pcfg.write_text(json.dumps(cfg), encoding="utf-8")
        render_failures = 0
        for idx, (start, text) in enumerate(blocks, 1):
            mmd_file = out_dir / f"b{idx:03d}.mmd"
            svg_file = out_dir / f"b{idx:03d}.svg"
            mmd_file.write_text(text, encoding="utf-8")
            code, output = run_mmdc(mmdc, ["-p", str(pcfg), "-i", str(mmd_file), "-o", str(svg_file)])
            if code != 0:
                render_failures += 1
                print(f"FAIL b{idx:03d} line={start}: RENDER_ERROR")
                for err_line in [x for x in output.splitlines() if x.strip()][:4]:
                    print(f"    {err_line}")
        failures = render_failures
        if blocks and render_failures == len(blocks):
            print("WARN RENDER_ENV_BROKEN 全部渲染失败（检查 MMDC_PATH/CHROME_PATH），回退结构化 lint 结果")
            mode = "lint(fallback)"
            problems: list[str] = []
            for idx, (start, text) in enumerate(blocks, 1):
                problems.extend(lint_block(f"b{idx:03d}", start, text))
            for p in problems:
                print(p)
            failures = len(problems)
    else:
        problems: list[str] = []
        for idx, (start, text) in enumerate(blocks, 1):
            problems.extend(lint_block(f"b{idx:03d}", start, text))
        for p in problems:
            print(p)
        failures = len(problems)

    print(f"mode={mode}")
    print(f"mermaid_blocks={len(blocks)} failures={failures}")
    if mode.startswith("lint"):
        print("NOTE lint 模式：未做真实渲染，仅本地结构化校验（最终答复中说明）")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
