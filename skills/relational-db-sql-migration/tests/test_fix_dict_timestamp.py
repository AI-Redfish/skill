#!/usr/bin/env python3
"""fix_dict_timestamp.py 的单元测试。

运行: uv run tests/test_fix_dict_timestamp.py
  或: uv run python -m unittest discover -s tests
覆盖: 正常路径（四类语句形态）、边界（引号标识符/运行时函数/纯数值/非字典表）、
      错误路径（文件不存在/一致性断言），以及实战回归用例
      （Kingbase UPDATE...SET...FROM 不得吞 FROM 子句）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fix_dict_timestamp as m  # noqa: E402

DICTS = set(m.DEFAULT_TABLES)


def fix(text: str) -> str:
    edits, _ = m.find_edits(text, DICTS)
    return m.apply_edits(text, edits)


def count(text: str) -> int:
    edits, _ = m.find_edits(text, DICTS)
    return len(edits)


class NormalPathTests(unittest.TestCase):
    def test_replace_values_backticks(self):
        sql = ("REPLACE INTO `basic_platform_ops`.`zz_tenant_global_dict` "
               "(`dict_id`, `dict_code`, `create_user_id`, `create_time`, `update_user_id`, `update_time`, `deleted_flag`) "
               "VALUES (2065100912000020001, 'mw', '1927320924684554240', '2026-10-09 12:00:00', "
               "'1927320924684554240', '2026-10-09 12:00:00', 0);")
        self.assertEqual(count(sql), 2)
        out = fix(sql)
        self.assertIn("CURRENT_TIMESTAMP, '1927320924684554240', CURRENT_TIMESTAMP", out)
        self.assertNotIn("2026-10-09", out)

    def test_insert_select_union(self):
        sql = ("INSERT INTO sys_dict_key (id, code, create_time, update_time, flag)\n"
               "SELECT '1', 'A', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 0\n"
               "FROM t WHERE NOT EXISTS (SELECT 1 FROM sys_dict_key)\n"
               "UNION ALL\n"
               "SELECT '2', 'B', '2026-01-03 00:00:00', '2026-01-04 00:00:00', 0\n"
               "FROM t2;")
        self.assertEqual(count(sql), 4)
        out = fix(sql)
        self.assertNotIn("2026-01-", out)
        self.assertEqual(out.count("CURRENT_TIMESTAMP"), 4)

    def test_select_sparse_columns(self):
        # create_time/update_time 位于第 7/9 列（稀疏下标回归）
        sql = ("INSERT INTO sys_dict_value (a, b, c, d, e, f, create_time, h, update_time)\n"
               "SELECT '1', '2', '3', '4', '5', '6', '2026-01-01 00:00:00', '8', '2026-01-02 00:00:00' FROM x;")
        self.assertEqual(count(sql), 2)
        out = fix(sql)
        self.assertIn("'8', CURRENT_TIMESTAMP", out)
        self.assertNotIn("2026-01-", out)

    def test_update_set_with_alias(self):
        sql = ("UPDATE zz_tenant_global_dict d\n"
               "SET d.initial_data = '[]', d.update_user_id = 'system', d.update_time = '2026-10-14 10:00:00'\n"
               "WHERE d.dict_code = 'X';")
        out = fix(sql)
        self.assertIn("d.update_time = CURRENT_TIMESTAMP", out)
        self.assertNotIn("2026-10-14", out)

    def test_on_duplicate_key_update(self):
        sql = ("INSERT INTO zz_global_dict (id, code, create_time, update_time)\n"
               "VALUES ('1', 'A', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)\n"
               "ON DUPLICATE KEY UPDATE update_time = '2026-01-03 10:00:00';")
        self.assertEqual(count(sql), 1)
        self.assertIn("ON DUPLICATE KEY UPDATE update_time = CURRENT_TIMESTAMP", fix(sql))

    def test_insert_set_out_of_scope(self):
        # INSERT...SET 无列清单，无法按列位置定位：与 awk 检查器一致地跳过（需人工改写）
        sql = ("INSERT INTO sys_dict_key SET id='1', create_time='2026-01-01 08:00:00', "
               "update_time='2026-01-01 08:00:00';")
        self.assertEqual(count(sql), 0)


class RegressionTests(unittest.TestCase):
    def test_kingbase_update_from_clause_preserved(self):
        # 实战事故回归：value_end 缺少 from 会吞掉 FROM 子句导致整块删除
        sql = ("UPDATE zz_tenant_global_dict d\n"
               "SET initial_data = t.payload, update_user_id = 'system', update_time = '2026-10-14 10:00:00'\n"
               "FROM (\n"
               "  SELECT '[' || string_agg(s.payload, ',') || ']' AS payload\n"
               "  FROM (SELECT m.system_code FROM monitor_system m GROUP BY m.system_code) s\n"
               ") t\n"
               "WHERE d.dict_code = 'X' AND t.payload IS NOT NULL;")
        out = fix(sql)
        self.assertEqual(count(sql), 1)
        self.assertIn("FROM (", out)
        self.assertIn("string_agg", out)
        self.assertIn(") t", out)
        self.assertIn("update_time = CURRENT_TIMESTAMP", out)
        self.assertNotIn("2026-10-14", out)

    def test_no_cross_statement_leak(self):
        # 修复不得越过分号影响后续语句
        sql = ("UPDATE sys_dict_key SET update_time = '2026-01-01 00:00:00';\n"
               "UPDATE sys_dict_key SET remark = 'keep';\n"
               "INSERT INTO other_table (a, update_time) VALUES (1, '1999-01-01 00:00:00');")
        out = fix(sql)
        self.assertIn("remark = 'keep'", out)
        self.assertIn("'1999-01-01 00:00:00'", out)  # 非字典表不动
        self.assertEqual(out.count("CURRENT_TIMESTAMP"), 1)


class BoundaryTests(unittest.TestCase):
    def test_runtime_functions_not_replaced(self):
        sql = ("INSERT INTO sys_dict_key (id, create_time, update_time)\n"
               "VALUES ('1', CURRENT_TIMESTAMP, NOW());")
        self.assertEqual(count(sql), 0)

    def test_null_and_quoted_number_not_replaced(self):
        sql = ("INSERT INTO sys_dict_key (id, create_time, update_time)\n"
               "VALUES ('1', NULL, '123');")
        self.assertEqual(count(sql), 0)

    def test_bare_integer_time_replaced(self):
        sql = "UPDATE sys_dict_key SET update_time = 20261014 WHERE id = '1';"
        self.assertEqual(count(sql), 1)
        self.assertIn("update_time = CURRENT_TIMESTAMP", fix(sql))

    def test_non_dict_table_skipped(self):
        sql = ("INSERT INTO risk_template (id, create_time, update_time)\n"
               "VALUES ('1', '2026-01-01 00:00:00', '2026-01-01 00:00:00');")
        self.assertEqual(count(sql), 0)

    def test_no_column_list_skipped(self):
        sql = "INSERT INTO sys_dict_key VALUES ('1', 'A', '2026-01-01 00:00:00', '2026-01-01 00:00:00');"
        self.assertEqual(count(sql), 0)

    def test_double_quoted_identifiers(self):
        sql = ('INSERT INTO "sys_dict_key" ("id", "create_time", "update_time")\n'
               "VALUES ('1', '2026-01-01 00:00:00', '2026-01-01 00:00:00');")
        self.assertEqual(count(sql), 2)

    def test_crlf_and_chinese_bytes_preserved(self):
        sql = ("REPLACE INTO sys_dict_key (`id`, `name`, `create_time`, `update_time`) VALUES ('1', '施工监管', "
               "'2026-01-01 00:00:00', '2026-01-01 00:00:00');\r\n")
        out = fix(sql)
        self.assertIn("\r\n", out)
        self.assertNotIn("\r\n\r\n", out)
        raw_in = sql.encode("utf-8")
        raw_out = out.encode("utf-8")
        self.assertEqual(raw_in.count("\r\n".encode()), raw_out.count("\r\n".encode()))
        self.assertIn("施工监管".encode("utf-8"), raw_out)

    def test_idempotent(self):
        sql = ("INSERT INTO sys_dict_key (id, create_time, update_time) "
               "VALUES ('1', '2026-01-01 00:00:00', '2026-01-01 00:00:00');")
        once = fix(sql)
        self.assertEqual(count(once), 0)
        self.assertEqual(fix(once), once)

    def test_overlapping_edits_rejected(self):
        # find_edits 输出必须互不重叠（对真实数据 228 处验证过的性质）
        sql = ("INSERT INTO sys_dict_key (id, create_time, update_time) "
               "VALUES ('1', '2026-01-01 00:00:00', '2026-01-02 00:00:00');")
        edits, _ = m.find_edits(sql, DICTS)
        for a, b in zip(edits, edits[1:]):
            self.assertLessEqual(a[1], b[0])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "fix_dict_timestamp.py"), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def test_missing_file_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            r = self.run_cli(str(Path(td) / "nope.sql"))
            self.assertEqual(r.returncode, 2)

    def test_dry_run_exit_1_apply_exit_0(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.sql"
            f.write_text("UPDATE sys_dict_key SET update_time = '2026-01-01 00:00:00';", encoding="utf-8")
            r = self.run_cli(str(f))
            self.assertEqual(r.returncode, 1)
            r = self.run_cli("--apply", str(f))
            self.assertEqual(r.returncode, 0)
            self.assertIn("CURRENT_TIMESTAMP", f.read_text(encoding="utf-8"))
            # 幂等：再次 dry-run 无待修复项
            r = self.run_cli(str(f))
            self.assertEqual(r.returncode, 0)

    def test_line_endings_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "crlf.sql"
            f.write_bytes("UPDATE sys_dict_key SET update_time = '2026-01-01 00:00:00';\r\n".encode("utf-8"))
            before = f.read_bytes()
            r = self.run_cli("--apply", str(f))
            self.assertEqual(r.returncode, 0)
            after = f.read_bytes()
            self.assertEqual(before.count(b"\r\n"), after.count(b"\r\n"))
            self.assertIn("CURRENT_TIMESTAMP".encode(), after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
