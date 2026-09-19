# db-schema-check.py — 真实 MySQL 库表核对（本地脚本，替代 mcp:@bytebase/dbhub）
# 读取 <work_dir>/.agents/.env 的 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME，
# 优先用 pymysql（uv run 自动安装隔离依赖），缺失时降级本机 mysql 客户端，
# 执行只读 SHOW 语句（SHOW TABLES / SHOW CREATE TABLE）核对真实表结构。
# 用法:
#   uv run scripts/db-schema-check.py --tables "t_a,t_b" [--work-dir <dir>]   # 推荐：uv 自动隔离并安装 pymysql
#   python scripts/db-schema-check.py [--work-dir <dir>]                       # 无 pymysql 时自动降级 mysql CLI
# 退出码: 0 = 查询成功；1 = 连接/SQL 失败；2 = 环境缺失（.agents/.env 配置不全或无可用客户端）。
# 环境缺失时不阻断 skill：提示用户输入并由主调用方写入 .agents/.env 后重跑，或按 SKILL.md 降级处理。
#
# /// script
# requires-python = ">=3.9"
# dependencies = ["pymysql"]
# ///

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import import_agent_env  # noqa: E402

REQUIRED_KEYS = ("DB_HOST", "DB_USER", "DB_NAME")


def try_pymysql(env_map: dict[str, str], sqls: list[str]) -> int:
    import pymysql  # 由 uv run 自动安装；纯 python 运行且未安装时抛 ImportError

    conn = pymysql.connect(
        host=env_map["DB_HOST"],
        port=int(env_map.get("DB_PORT") or 3306),
        user=env_map["DB_USER"],
        password=env_map.get("DB_PASSWORD", ""),
        database=env_map["DB_NAME"],
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            for sql in sqls:
                cur.execute(sql)
                rows = cur.fetchall()
                for row in rows:
                    print("\n".join(str(x) for x in row))
    finally:
        conn.close()
    return 0


def try_mysql_cli(env_map: dict[str, str], sql: str) -> int:
    env = dict(os.environ)
    if env_map.get("DB_PASSWORD"):
        env["MYSQL_PWD"] = env_map["DB_PASSWORD"]  # 口令经环境变量传递，不上命令行
    cmd = [
        "mysql",
        "-h", env_map["DB_HOST"],
        "-P", env_map.get("DB_PORT") or "3306",
        "-u", env_map["DB_USER"],
        "--default-character-set=utf8mb4",
        "-t",
        "-e", sql,
        env_map["DB_NAME"],
    ]
    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 MySQL 库表核对")
    parser.add_argument("--tables", default="", help="逗号分隔表名；为空时仅列出库中全部表")
    parser.add_argument("--work-dir", default=None, help="skill 运行时工作目录（.agents/.env 所在目录），默认当前目录")
    args = parser.parse_args()

    env_map = import_agent_env(args.work_dir)
    env_file = (Path(args.work_dir) if args.work_dir else Path.cwd()) / ".agents" / ".env"

    missing = [k for k in REQUIRED_KEYS if not env_map.get(k)]
    if missing:
        print(f"MISSING_ENV keys={','.join(missing)}")
        print(f"请在 {env_file} 中配置：DB_HOST / DB_PORT(默认3306) / DB_USER / DB_PASSWORD / DB_NAME")
        print("由主调用方提示用户输入后写入；用户拒绝则跳过真实库核对并在文档“待确认与需求冲突”段注明")
        return 2

    if args.tables.strip():
        names = [t for t in re.split(r"[,\s]+", args.tables) if re.fullmatch(r"[A-Za-z0-9_$]+", t)]
        bad = [t for t in re.split(r"[,\s]+", args.tables) if t and not re.fullmatch(r"[A-Za-z0-9_$]+", t)]
        if bad:
            print(f"WARN 忽略非法表名: {','.join(bad)}")
        if not names:
            print("ERROR 未提供合法表名")
            return 2
        sqls = [f"SHOW CREATE TABLE `{n}`;" for n in names]
        cli_sql = " ".join(sqls)
    else:
        sqls = ["SHOW TABLES;"]
        cli_sql = "SHOW TABLES;"

    print(f"# mysql -h {env_map['DB_HOST']} -P {env_map.get('DB_PORT') or '3306'} -u {env_map['DB_USER']} db={env_map['DB_NAME']}")

    try:
        code = try_pymysql(env_map, sqls)
        if code == 0:
            print("DB_CHECK_OK (pymysql)")
            return 0
    except ImportError:
        print("NOTE pymysql 未安装（建议 uv run 自动隔离安装），尝试降级 mysql CLI")
    except Exception as exc:  # 连接/SQL 失败
        print(f"DB_CHECK_FAILED pymysql error: {exc}")
        return 1

    if not shutil.which("mysql"):
        print("MISSING_TOOL pymysql 未安装且 mysql 客户端不在 PATH；跳过真实库核对并按 SKILL.md 降级处理")
        return 2
    code = try_mysql_cli(env_map, cli_sql)
    if code != 0:
        print(f"DB_CHECK_FAILED exit={code}")
        return 1
    print("DB_CHECK_OK (mysql cli)")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
