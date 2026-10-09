"""Tests for independent run archives and navigable module/history indexes."""
import contextlib
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote

spec = importlib.util.spec_from_file_location(
    'run_records', Path(__file__).parents[1] / 'scripts' / 'run_records.py')
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


class TestRunRecords(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        (self.ws / 'workspace.yaml').write_text('project: demo\n', encoding='utf-8')

    def command(self, *args, expected=0):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = rr.main(list(args))
        self.assertEqual(rc, expected, output.getvalue())
        return json.loads(output.getvalue())

    def create(self, mods=('order',), topic='订单回归', extra=()):
        args = ['create', '--workspace', str(self.ws), '--topic', topic,
                '--environment', '147', '--mode', 'existing']
        for name in mods:
            args += ['--module', name]
        return self.command(*args, *extra)['data']

    def test_repeated_runs_unique_and_rerun_preserves_history(self):
        first = self.create()
        p = Path(first['runDir'])
        (p / 'report.md').write_text('original report', encoding='utf-8')
        second = self.create(extra=('--rerun-of', first['runId']))
        self.assertNotEqual(first['runId'], second['runId'])
        self.assertRegex(second['runId'], r'^\d{8}-\d{6}-\d{6}__order__订单回归$')
        data = json.loads((Path(second['runDir']) / 'run.json').read_text(encoding='utf-8'))
        self.assertIsNotNone(datetime.fromisoformat(data['startedAt']).utcoffset())
        self.assertEqual(data['rerunOf'], first['runId'])
        self.assertEqual((p / 'report.md').read_text(encoding='utf-8'), 'original report')

    def test_cross_module_links_resolve_and_review_updates(self):
        run = self.create(('order', 'alarm'))
        directory = Path(run['runDir'])
        self.assertIn('__cross-module__', run['runId'])
        for name in ('report.md', 'report.html'):
            (directory / name).write_text('report', encoding='utf-8')
        (directory / 'videos').mkdir()
        self.command('update', '--run-dir', str(directory), '--status', 'completed',
                     '--summary', '自动通过，录像待核对', '--human-review', 'pending')
        for p in (self.ws / 'runs/INDEX.md', self.ws / 'runs/by-module/order.md',
                  self.ws / 'runs/by-module/alarm.md'):
            text = p.read_text(encoding='utf-8')
            self.assertIn('自动通过，录像待核对', text)
            self.assertIn('pending', text)
            for target in re.findall(r'\]\(([^)]+)\)', text):
                self.assertTrue((p.parent / unquote(target)).exists(), (p, target))
        data = json.loads((directory / 'run.json').read_text(encoding='utf-8'))
        self.assertIsNotNone(data['finishedAt'])
        self.command('update', '--run-dir', str(directory), '--human-review', 'reviewed',
                     '--summary', '人工已核对')
        self.assertEqual(json.loads((directory / 'run.json').read_text(encoding='utf-8'))['finishedAt'],
                         data['finishedAt'])
        self.command('update', '--run-dir', str(directory), '--status', 'running', expected=1)

    def test_keeps_over_twenty_records_and_legacy_report(self):
        old = self.ws / 'runs/old-order-regression'
        old.mkdir(parents=True)
        (old / 'report.md').write_text('legacy original', encoding='utf-8')
        run = self.create()
        data = json.loads((Path(run['runDir']) / 'run.json').read_text(encoding='utf-8'))
        for i in range(22):
            d = self.ws / 'runs' / f'run-{i:02d}'
            d.mkdir()
            current = dict(data, runId=d.name, startedAt=f'2025-01-{i+1:02d}T10:00:00+08:00')
            (d / 'run.json').write_text(json.dumps(current), encoding='utf-8')
        result = self.command('reindex', '--workspace', str(self.ws))['data']
        self.assertEqual(result['runs'], 23)
        self.assertEqual(result['legacyRuns'], 1)
        index = (self.ws / 'runs/INDEX.md').read_text(encoding='utf-8')
        self.assertIn('run-00', index)
        self.assertLess(index.index('run-21'), index.index('run-00'))
        self.assertIn('旧记录', index)
        self.assertIn('未知', index)
        self.assertEqual((old / 'report.md').read_text(encoding='utf-8'), 'legacy original')

    def test_paths_and_modules_cannot_escape(self):
        self.command('create', '--workspace', str(self.ws), '--module', '../other',
                     '--topic', 't', '--environment', '147', '--mode', 'local', expected=1)
        run = self.create(topic='../测试/主题')
        self.assertEqual(Path(run['runDir']).parent, self.ws / 'runs')
        self.command('update', '--run-dir', str(self.ws), '--status', 'completed', expected=1)

    def test_user_module_file_not_overwritten(self):
        root = self.ws / 'runs/by-module'
        root.mkdir(parents=True)
        target = root / 'order.md'
        target.write_text('user notes', encoding='utf-8')
        self.command('create', '--workspace', str(self.ws), '--module', 'order',
                     '--topic', 't', '--environment', '147', '--mode', 'local', expected=1)
        self.assertEqual(target.read_text(encoding='utf-8'), 'user notes')


if __name__ == '__main__':
    unittest.main()
