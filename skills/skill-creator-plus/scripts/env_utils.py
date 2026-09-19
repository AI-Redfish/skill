#!/usr/bin/env python3
"""env_utils.py — 管理运行时工作目录下 <workdir>/.agents/.env（环境信息，含账号密码）。

约定（与 prd-techdoc 的 env.py 一致）：UTF-8 文本，一行一个 `键=值`，
支持 # 注释与成对双引号包裹。该文件可能含敏感信息：
  - 写入只发生在「用户主动输入之后」（SKILL.md §5.2），不得自动填充猜测值；
  - 写入后必须 ensure-gitignore，防止入库。

用法：
  python env_utils.py list [--workdir D] [--show-values]
  python env_utils.py get KEY [--workdir D]
  python env_utils.py set KEY=VALUE [KEY2=V2 ...] [--workdir D]
  python env_utils.py missing --keys K1,K2 [--workdir D]
  python env_utils.py ensure-gitignore [--workdir D]

输出：JSON 到 stdout；日志到 stderr。退出码：0 成功；1 未找到/缺失；2 参数错误。
纯标准库，Python 3.9+。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ENV_REL = Path(".agents") / ".env"


def log(msg: str) -> None:
    print(f"[env_utils] {msg}", file=sys.stderr)


def env_path(workdir: Path) -> Path:
    return workdir / ENV_REL


def parse_env(text: str) -> dict:
    result = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        i = line.find("=")
        if i <= 0:
            continue
        key, value = line[:i].strip(), line[i + 1:].strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        result[key] = value
    return result


def load(workdir: Path) -> dict:
    p = env_path(workdir)
    if not p.is_file():
        return {}
    return parse_env(p.read_text(encoding="utf-8-sig", errors="replace"))


def mask(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return value[:2] + "***"


def upsert(workdir: Path, kv: dict) -> Path:
    """按键更新/追加，保留既有行序、注释与未识别行。"""
    p = env_path(workdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines() if p.is_file() else []
    for key, value in kv.items():
        if "\n" in value or "=" in key:
            raise ValueError(f"非法键值：{key!r}")
        target = f"{key}={value}"
        idx = next((i for i, ln in enumerate(lines)
                    if ln.strip() and not ln.strip().startswith("#")
                    and ln.strip().split("=", 1)[0].strip() == key), None)
        if idx is not None:
            lines[idx] = target
        else:
            lines.append(target)  # 一行一键，不插入空行，避免多次 set 后空行堆积
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def find_git_root(workdir: Path) -> Path | None:
    cur = workdir.resolve()
    while not (cur / ".git").exists():
        if cur.parent == cur:
            return None
        cur = cur.parent
    return cur


GITIGNORE_COVER = {".env", ".env*", ".agents/", ".agents/*", ".agents/.env"}


def main() -> int:
    parser = argparse.ArgumentParser(description="管理 <workdir>/.agents/.env")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出键（值默认脱敏）")
    p.add_argument("--workdir", default=".")
    p.add_argument("--show-values", action="store_true", help="显示明文值（谨慎：可能含密码）")

    p = sub.add_parser("get", help="读取一个键")
    p.add_argument("key")
    p.add_argument("--workdir", default=".")

    p = sub.add_parser("set", help="写入键值（用户输入后调用；可多个）")
    p.add_argument("kv", nargs="+", help="KEY=VALUE ...")
    p.add_argument("--workdir", default=".")

    p = sub.add_parser("missing", help="检查哪些必需键缺失")
    p.add_argument("--keys", required=True, help="逗号分隔的键名清单")
    p.add_argument("--workdir", default=".")

    p = sub.add_parser("ensure-gitignore", help="确保 .env 被 .gitignore 覆盖")
    p.add_argument("--workdir", default=".")

    args = parser.parse_args()
    workdir = Path(args.workdir).expanduser().resolve()
    if not workdir.is_dir():
        print(json.dumps({"status": "error",
                          "error": {"message": f"工作目录不存在：{workdir}"}}, ensure_ascii=False))
        return 2

    if args.cmd == "list":
        data = load(workdir)
        p = env_path(workdir)
        out = {"status": "ok", "file": str(p), "exists": p.is_file(),
               "keys": {k: (v if args.show_values else mask(v)) for k, v in sorted(data.items())},
               "count": len(data)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "get":
        data = load(workdir)
        if args.key not in data:
            print(json.dumps({"status": "missing", "key": args.key,
                              "hint": f"向用户收取后用 set {args.key}=<值> 写入"},
                             ensure_ascii=False))
            return 1
        print(json.dumps({"status": "ok", "key": args.key, "value": data[args.key]},
                         ensure_ascii=False))
        return 0

    if args.cmd == "set":
        kv = {}
        for item in args.kv:
            if "=" not in item:
                print(json.dumps({"status": "error",
                                  "error": {"message": f"参数须为 KEY=VALUE 形式：{item!r}"}},
                                 ensure_ascii=False))
                return 2
            k, _, v = item.partition("=")
            kv[k.strip()] = v
        try:
            p = upsert(workdir, kv)
        except ValueError as exc:
            print(json.dumps({"status": "error", "error": {"message": str(exc)}},
                             ensure_ascii=False))
            return 2
        log("该文件可能含敏感信息，请随即运行 ensure-gitignore")
        print(json.dumps({"status": "ok", "file": str(p), "written": sorted(kv)},
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "missing":
        need = [k.strip() for k in args.keys.split(",") if k.strip()]
        data = load(workdir)
        missing = [k for k in need if k not in data]
        print(json.dumps({"status": "ok", "needed": need,
                          "present": [k for k in need if k in data],
                          "missing": missing,
                          "file": str(env_path(workdir)),
                          "hint": ("逐项向用户询问缺失键（说明用途与敏感性），"
                                   "输入后 set 写入并 ensure-gitignore"
                                   if missing else "环境信息齐全，可直接进入测试")},
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "ensure-gitignore":
        git_root = find_git_root(workdir)
        if git_root is None:
            print(json.dumps({"status": "ok", "action": "no_git",
                              "message": f"{workdir} 不在 git 仓库内，无需 .gitignore"},
                             ensure_ascii=False))
            return 0
        gi = git_root / ".gitignore"
        lines = gi.read_text(encoding="utf-8-sig", errors="replace").splitlines() if gi.is_file() else []
        covered = any(ln.strip() in GITIGNORE_COVER for ln in lines)
        if covered:
            print(json.dumps({"status": "ok", "action": "exists",
                              "gitignore": str(gi)}, ensure_ascii=False))
            return 0
        block = ["", "# skill-creator-plus: 环境信息（可能含密钥），不得提交", ".agents/.env"]
        gi.write_text("\n".join(lines + block) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "action": "added",
                          "gitignore": str(gi), "added": ".agents/.env"},
                         ensure_ascii=False))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
