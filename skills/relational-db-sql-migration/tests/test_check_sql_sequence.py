import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_sql_sequence import API, CheckError, config, parse_file, summarize


class SequenceCheckTests(unittest.TestCase):
    def test_parse_scopes_database_iteration_and_engine(self):
        path = 'mysql/basic_platform_ops/V2026.11.17.16.12.06_6.0.9.2.7__basic_platform_ops_create.sql'
        item = parse_file(path, '6.0.9.2', 'basic_platform_ops')
        self.assertEqual(item['sequence'], 7)
        self.assertIsNone(parse_file(path, '6.0.9.3', 'basic_platform_ops'))
        self.assertIsNone(parse_file(path, 'mysql/basic_platform_mgr/x', 'basic_platform_ops'))

    def test_malformed_matching_filename_fails_closed(self):
        with self.assertRaises(CheckError):
            parse_file('mysql/basic_platform_ops/Vbad_6.0.9.2.8__basic_platform_ops_create.sql',
                       '6.0.9.2', 'basic_platform_ops')

    def test_inventory_includes_unmerged_mr_and_detects_collision(self):
        paths = 'mysql/basic_platform_ops/V2026.11.17.16.12.06_6.0.9.2.7__basic_platform_ops_create.sql'
        data = summarize({'local': [], 'target': [], 'mr!1': [paths], 'mr!2': [paths]},
                         '6.0.9.2', 'basic_platform_ops')
        self.assertEqual(data['next_sequence'], 8)
        self.assertEqual(data['conflicts'][0]['sequence'], 7)

    def test_env_does_not_override_process_environment(self):
        with tempfile.TemporaryDirectory() as td:
            env = Path(td) / '.agents' / '.env'
            env.parent.mkdir()
            env.write_text('GITLAB_TOKEN="from-file"\n', encoding='utf-8')
            with patch.dict(os.environ, {'GITLAB_TOKEN': 'from-process'}):
                self.assertEqual(config(td)['GITLAB_TOKEN'], 'from-process')

    def test_http_requires_explicit_opt_in(self):
        with self.assertRaises(CheckError):
            API('http://gitlab.example', 'token')
        self.assertIsNotNone(API('http://gitlab.example', 'token', allow_http=True))


if __name__ == '__main__':
    unittest.main()
