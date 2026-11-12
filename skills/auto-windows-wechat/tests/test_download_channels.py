"""Offline downloader tests; never log in, download, or send WeChat messages."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'download_channels.py'
spec = importlib.util.spec_from_file_location('channels_downloader', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class DownloadTests(unittest.TestCase):
    def test_valid_share_url(self):
        url = 'https://weixin.qq.com/sph/Ab_cd-123'
        self.assertEqual(mod.validate_share_url(url), url)

    def test_invalid_share_urls(self):
        for url in ['', 'http://weixin.qq.com/sph/test',
                    'https://weixin.qq.com.evil.test/sph/one',
                    'https://weixin.qq.com@evil.test/sph/one',
                    'https://weixin.qq.com/sph/a?token=secret',
                    'https://weixin.qq.com/sph/a#fragment',
                    'https://weixin.qq.com/sph/../../other']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                mod.validate_share_url(url)

    def test_inline_result(self):
        self.assertEqual(mod.materialize({'value':{'ok':True}}, Path('cli'), 'task'), {'ok':True})

    def test_resource_pagination(self):
        value = {'ok':True, 'note':'完整中文'}
        raw = json.dumps(value, ensure_ascii=False)
        parts = [{'data':raw[:12], 'nextOffset':12, 'eof':False},
                 {'data':raw[12:], 'eof':True}]
        with patch.object(mod, 'cli_call', side_effect=parts) as call:
            result = mod.materialize({'resourceId':'resource'}, Path('cli'), 'task')
        self.assertEqual(result, value)
        self.assertIn('65536', call.call_args_list[0].args[1])
        self.assertIn('12', call.call_args_list[1].args[1])

    def test_resource_cycle_rejected(self):
        with patch.object(mod, 'cli_call', return_value={'data':'{', 'nextOffset':0, 'eof':False}):
            with self.assertRaises(mod.DownloadError):
                mod.materialize({'resourceId':'resource'}, Path('cli'), 'task')

    def test_missing_resource_data(self):
        with patch.object(mod, 'cli_call', return_value={'eof':True}):
            with self.assertRaises(mod.DownloadError):
                mod.materialize({'resourceId':'resource'}, Path('cli'), 'task')

    def test_receipt_when_stdout_empty(self):
        receipt = {'status':'succeeded', 'result':{'type':'inline', 'value':{'ok':True}}}
        with patch.object(mod, 'cli_call', return_value=receipt) as call:
            self.assertEqual(mod.read_request({}, Path('cli'), 'task', 'same-id'), {'ok':True})
        self.assertIn('receipt', call.call_args.args[1])
        self.assertIn('same-id', call.call_args.args[1])

    def test_pending_receipt_preserved(self):
        with patch.object(mod, 'cli_call', return_value={'status':'running'}):
            with self.assertRaises(mod.DownloadError):
                mod.read_request({'status':'running'}, Path('cli'), 'task', 'same-id')

    def test_raw_failure_redacted(self):
        with self.assertRaises(mod.DownloadError) as error:
            mod.read_request({'status':'failed','error':'signed-secret-token'}, Path('cli'), 'task', 'id')
        self.assertNotIn('signed-secret-token', str(error.exception))

    def test_cli_prefix_lines(self):
        self.assertEqual(mod.parse_cli_json('INSTANCE=test\n{"ok":true}'), {'ok':True})

    def test_invalid_cli_json(self):
        with self.assertRaises(mod.DownloadError):
            mod.parse_cli_json('not-json')

    def test_save_and_no_overwrite(self):
        data = b'\x00\x00\x00\x18ftypisom' + b'\x00' * 24
        value = {'ok':True, 'bytes':len(data), 'base64':base64.b64encode(data).decode()}
        with tempfile.TemporaryDirectory(prefix='channels-test-') as folder:
            path = Path(folder) / '中文 空格.mp4'
            result = mod.save_media(value, path)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(len(result['sha256']), 64)
            with self.assertRaises(mod.DownloadError):
                mod.save_media(value, path)
            self.assertEqual(path.read_bytes(), data)

    def test_bad_media_not_saved(self):
        with tempfile.TemporaryDirectory(prefix='channels-test-') as folder:
            path = Path(folder) / 'video.mp4'
            for value in [{'ok':False,'error':'login required'},
                          {'ok':True,'bytes':4,'base64':'!!!!'},
                          {'ok':True,'bytes':20,'base64':base64.b64encode(b'<html>not-video</html>').decode()}]:
                with self.subTest(value=value), self.assertRaises(mod.DownloadError):
                    mod.save_media(value, path)
                self.assertFalse(path.exists())

    def test_invalid_cli_has_no_browser_side_effect(self):
        with patch.object(mod, 'cli_call') as call, patch.object(sys, 'argv',
                ['download_channels.py', 'http://evil.test', '--tab','1','-o','unused.mp4']):
            with self.assertRaises(SystemExit) as exit_info:
                mod.main()
        self.assertEqual(exit_info.exception.code, 2)
        call.assert_not_called()

    def test_generated_js_syntax(self):
        program = mod.make_program('https://weixin.qq.com/sph/example', 10000)
        result = subprocess.run(['node','--check','-'], input='async function run(){'+program+'}',
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('page.goto', program)
        self.assertNotIn('storageState', program)
        self.assertNotIn('cookies()', program)


if __name__ == '__main__':
    unittest.main(verbosity=2)
