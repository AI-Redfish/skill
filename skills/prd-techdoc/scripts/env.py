# env.py — 读取 skill 运行时工作目录下 .agents/.env 的共享函数
# 被 check-mermaid.py / db-schema-check.py 复用。
# 约定：UTF-8 文本，一行一个 `键=值`，支持 # 注释与成对双引号包裹。
# 本文件只读取环境信息，一律不写入；写入由主调用方在征得用户输入后完成。

from __future__ import annotations

from pathlib import Path


def import_agent_env(work_dir: str | None = None) -> dict[str, str]:
    """读取 <work_dir>/.agents/.env，返回键值字典；文件不存在返回空字典。"""
    base = Path(work_dir) if work_dir else Path.cwd()
    env_file = base / ".agents" / ".env"
    result: dict[str, str] = {}
    if not env_file.is_file():
        return result
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        i = line.find("=")
        if i <= 0:
            continue
        key = line[:i].strip()
        value = line[i + 1:].strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        result[key] = value
    return result
