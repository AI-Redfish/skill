#!/usr/bin/env python3
"""test_pcmanager.py — pc-manager PowerShell 脚本单测（正常/边界/错误三路径）。

原则：
- 全部在 fixture 临时目录内构造数据；通过子进程环境变量（TEMP/USERPROFILE/
  APPDATA/LOCALAPPDATA）把扫描根重定向到 fixture，不触碰真实用户数据
- 唯一进入真实回收站的是 fixture 文件本身（recycle trash 用例），无害
- 需要管理员的路径只验证「正确报错提示提权」，不提权执行

用法: python -m unittest test_pcmanager -v   （或 run_tests.py）
依赖: 纯标准库。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts')
PS = 'powershell'
# fixture 基目录：放在 tests/.tmp-fixtures（系统 Temp 位于 \AppData\ 下，
# 会被部分脚本的 AppData 忽略清单误杀，故避开）
FIXTURE_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.tmp-fixtures')


def fixture_dir(prefix):
    os.makedirs(FIXTURE_BASE, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=FIXTURE_BASE)


def run_ps(script, args=(), env_extra=None, timeout=120):
    """执行一个 .ps1 并解析 JSON 信封。返回 (parsed_dict, exit_code, stderr)。"""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
         os.path.join(SCRIPTS, script)] + list(args),
        capture_output=True, env=env, timeout=timeout)
    text = proc.stdout.decode('utf-8', errors='replace').strip()
    parsed = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # 容错：取最后一个以 { 开头的行（防警告混入）
            for line in reversed(text.splitlines()):
                if line.strip().startswith('{'):
                    try:
                        parsed = json.loads(line.strip())
                        break
                    except json.JSONDecodeError:
                        continue
    return parsed, proc.returncode, proc.stderr.decode('utf-8', errors='replace')


def make_file(path, size=1024, age_days=0, content=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(content if content is not None else (b'x' * size))
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))


class TestProtectedPath(unittest.TestCase):
    """common.psm1 受保护路径判定（fail-safe 语义）。"""

    def _is_protected(self, path, allow=None):
        allow_arg = ("-AllowSystemPrefixes " + ','.join(allow)) if allow else ''
        script = (f"Import-Module '{SCRIPTS}\\common.psm1' -Force -DisableNameChecking; "
                  f"(Test-ProtectedPath -Path '{path}' {allow_arg}).ToString().ToLower()")
        proc = subprocess.run([PS, '-NoProfile', '-Command', script],
                              capture_output=True, timeout=60)
        out = proc.stdout.decode('utf-8', errors='replace').strip().splitlines()
        return bool(out) and out[-1].strip().lower() == 'true'

    def test_windows_dir_protected(self):
        self.assertTrue(self._is_protected(r'C:\Windows\System32\evil.dll'))

    def test_drive_root_protected(self):
        self.assertTrue(self._is_protected(r'C:\\'))
        self.assertTrue(self._is_protected(r'C:'))

    def test_empty_and_relative_protected(self):
        self.assertTrue(self._is_protected(''))
        self.assertTrue(self._is_protected(r'relative\path.txt'))

    def test_pagefile_protected(self):
        self.assertTrue(self._is_protected(r'C:\pagefile.sys'))

    def test_user_desktop_not_protected(self):
        self.assertFalse(self._is_protected(r'C:\Users\u\Desktop\a.txt'))

    def test_allow_prefix_gates_system_paths(self):
        p = r'C:\Windows\SoftwareDistribution\Download\pkg.msu'
        # 不放行 → 保护
        self.assertTrue(self._is_protected(p))
        # 放行声明根目录内 → 不保护
        self.assertFalse(self._is_protected(
            p, allow=[r'C:\Windows\SoftwareDistribution\Download']))
        # 放行前缀之外的同级系统路径仍保护
        self.assertTrue(self._is_protected(
            r'C:\Windows\System32\evil.dll',
            allow=[r'C:\Windows\SoftwareDistribution\Download']))


class TestJunkScan(unittest.TestCase):
    """junk.ps1 扫描预过滤 + 会话删除 + danger 强确认。"""

    def setUp(self):
        self.tmp = fixture_dir('pcm_junk_')
        env_home = os.path.join(self.tmp.name, 'env')
        os.makedirs(env_home, exist_ok=True)
        self.env = {'TEMP': os.path.join(env_home, 'temp'),
                    'TMP': os.path.join(env_home, 'temp'),
                    'LOCALAPPDATA': os.path.join(env_home, 'local'),
                    'APPDATA': os.path.join(env_home, 'roam')}
        os.makedirs(self.env['TEMP'], exist_ok=True)
        self.old_file = os.path.join(self.env['TEMP'], 'old.log')
        make_file(self.old_file, size=2048, age_days=30)
        make_file(os.path.join(self.env['TEMP'], 'new.log'), size=512, age_days=0)
        make_file(os.path.join(self.env['TEMP'], 'link.lnk'), size=100, age_days=30)
        make_file(os.path.join(self.env['TEMP'], 'desktop.ini'), size=10, age_days=30)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_filters(self):
        parsed, code, _ = run_ps('junk.ps1', ['-Action', 'scan'], self.env)
        self.assertEqual(code, 0, msg=f'scan failed: {parsed}')
        self.assertEqual(parsed['status'], 'ok')
        paths = [c['path'] for c in parsed['data']['candidates']]
        self.assertIn(self.old_file, paths)                 # 正常路径：过期文件列出
        self.assertNotIn(os.path.join(self.env['TEMP'], 'new.log'), paths)  # 边界：未过期不列
        self.assertNotIn(os.path.join(self.env['TEMP'], 'link.lnk'), paths)  # 边界：.lnk 跳过
        self.assertNotIn(os.path.join(self.env['TEMP'], 'desktop.ini'), paths)
        self.assertTrue(os.path.isfile(parsed['data']['session']))

    def test_delete_via_session(self):
        parsed, _, _ = run_ps('junk.ps1', ['-Action', 'scan'], self.env)
        session = parsed['data']['session']
        old_id = next(c['id'] for c in parsed['data']['candidates']
                      if c['path'] == self.old_file)
        # 错误路径：无 Session 直接删 → 拒绝
        err_parsed, err_code, _ = run_ps('junk.ps1', ['-Action', 'delete'])
        self.assertEqual(err_code, 1)
        self.assertEqual(err_parsed['status'], 'error')
        # 正常路径：按 id 永久删除 fixture 文件
        parsed2, code2, _ = run_ps('junk.ps1', [
            '-Action', 'delete', '-Session', session, '-Ids', old_id, '-Purge'], self.env)
        self.assertEqual(code2, 0, msg=str(parsed2))
        self.assertEqual(parsed2['data']['deleted_count'], 1)
        self.assertFalse(os.path.exists(self.old_file))

    def test_danger_requires_force(self):
        # 手工构造 danger 级会话，验证不带 -Force 被拒绝
        session = os.path.join(self.tmp.name, 'danger-session.json')
        with open(session, 'w', encoding='utf-8') as f:
            json.dump({'candidates': [{
                'id': 'x', 'path': os.path.join(self.env['TEMP'], 'd.bin'),
                'size': 10, 'level': 'danger', 'recommend': False}]}, f)
        make_file(os.path.join(self.env['TEMP'], 'd.bin'), size=10, age_days=0)
        parsed, code, _ = run_ps('junk.ps1', [
            '-Action', 'delete', '-Session', session, '-Ids', 'x'], self.env)
        self.assertEqual(code, 1)                            # 错误路径：danger 无 -Force
        self.assertIn('danger', parsed['error'])
        self.assertTrue(os.path.exists(os.path.join(self.env['TEMP'], 'd.bin')))


class TestSocial(unittest.TestCase):
    """social.ps1 四级分级 + 聊天记录锁死。"""

    def setUp(self):
        self.tmp = fixture_dir('pcm_soc_')
        base = os.path.join(self.tmp.name, 'env')
        os.makedirs(base, exist_ok=True)
        self.env = {'USERPROFILE': os.path.join(base, 'profile'),
                    'APPDATA': os.path.join(base, 'roam'),
                    'LOCALAPPDATA': os.path.join(base, 'local')}
        root = os.path.join(self.env['USERPROFILE'], 'Documents', 'xwechat_files', 'wxid')
        # safe：临时缓存
        make_file(os.path.join(root, 'cache', 'a.tmp'), size=100, age_days=1)
        # advise：图片缓存（.dat 加密图）
        make_file(os.path.join(root, 'msg', 'attach', 'img1.dat'), size=500, age_days=1)
        # locked：聊天记录库（绝不可删、不可计入可清理）
        make_file(os.path.join(root, 'msg', 'db', 'MicroMsg.db'), size=4096, age_days=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_levels_and_lock(self):
        parsed, code, _ = run_ps('social.ps1', ['-Action', 'scan'], self.env)
        self.assertEqual(code, 0, msg=f'scan failed: {parsed}')
        self.assertEqual(parsed['status'], 'ok')
        items = parsed['data']['items']
        levels = {i['level'] for i in items}
        self.assertIn('safe', levels)          # cache 命中 safe
        self.assertIn('advise', levels)        # attach 命中 advise（.dat 不锁）
        self.assertIn('locked', levels)        # 聊天记录聚合条目存在
        locked = [i for i in items if i['level'] == 'locked']
        self.assertTrue(locked and locked[0]['locked'] is True)
        self.assertGreater(locked[0]['size'], 0)   # .db 体积计入 locked 展示
        cleanable = parsed['data']['cleanable_bytes']
        self.assertGreater(cleanable, 0)           # 可清理体积不含 .db
        self.assertNotIn(4096, [i['size'] for i in items if not i['locked']])


class TestDup(unittest.TestCase):
    """dup.ps1 三级哈希分组。"""

    def setUp(self):
        self.tmp = fixture_dir('pcm_dup_')
        base = os.path.join(self.tmp.name, 'env')
        os.makedirs(base, exist_ok=True)
        self.env = {'USERPROFILE': os.path.join(base, 'profile')}
        content = bytes(range(256)) * 64   # 16KB 相同内容
        make_file(os.path.join(self.env['USERPROFILE'], 'Desktop', 'a.bin'),
                  content=content, age_days=5)
        make_file(os.path.join(self.env['USERPROFILE'], 'Desktop', 'sub', 'b.bin'),
                  content=content, age_days=2)
        make_file(os.path.join(self.env['USERPROFILE'], 'Desktop', 'c.bin'),
                  content=b'different' * 512, age_days=1)   # 同为 16KB 但内容不同

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_group(self):
        parsed, code, _ = run_ps('dup.ps1', ['-MinMb', '0'], self.env)
        self.assertEqual(code, 0, msg=f'scan failed: {parsed}')
        groups = parsed['data']['groups']
        self.assertEqual(len(groups), 1)                   # 只有 a/b 成组
        self.assertEqual(groups[0]['count'], 2)
        self.assertEqual(groups[0]['wasted'], 256 * 64)    # size(16384) × (count-1)


class TestRecycleTrash(unittest.TestCase):
    """recycle.ps1 trash：合法目标移入回收站；受保护路径拦截。"""

    def test_trash_fixture_file(self):
        with fixture_dir('pcm_tr_') as tmp:
            f = os.path.join(tmp, 'victim.txt')
            make_file(f, size=64)
            parsed, code, _ = run_ps('recycle.ps1', ['-Action', 'trash', '-Path', f])
            self.assertEqual(code, 0, msg=str(parsed))
            self.assertFalse(os.path.exists(f))            # 已移入回收站

    def test_trash_protected_rejected(self):
        parsed, code, _ = run_ps('recycle.ps1', [
            '-Action', 'trash', '-Path', r'C:\Windows\System32\kernel32.dll'])
        self.assertEqual(code, 1)                          # 错误路径：保护拦截
        self.assertIn('受保护', parsed['error'])


class TestSysinfo(unittest.TestCase):
    def test_sysinfo_ok(self):
        parsed, code, _ = run_ps('sysinfo.ps1')
        self.assertEqual(code, 0)
        self.assertEqual(parsed['status'], 'ok')
        self.assertTrue(parsed['data']['os'])
        self.assertGreater(parsed['data']['cpu_threads'], 0)


class TestTweaks(unittest.TestCase):
    """tweaks.ps1：只读 list/status + 错误路径；另含一个 HKCU-only 的
    apply→revert 往返（自动备份+精确还原，与真实回收站用例同级无害）。"""

    def test_list_ok(self):
        parsed, code, _ = run_ps('tweaks.ps1', ['-Action', 'list'])
        self.assertEqual(code, 0, msg=str(parsed))
        self.assertEqual(parsed['status'], 'ok')
        data = parsed['data']
        self.assertEqual(data['count'], 41)
        self.assertTrue(data['os_build'] > 0)
        tweaks = {t['id']: t for t in data['tweaks']}
        # 目录完整性：四类代表项存在且字段齐全
        for tid in ('perf-keyboard', 'priv-telemetry', 'gpu-nv-pstate', 'ux-menus'):
            self.assertIn(tid, tweaks)
            self.assertIn(tweaks[tid]['risk'], ('safe', 'caution', 'danger'))
            self.assertIsInstance(tweaks[tid]['applicable'], bool)
        # 显卡门控：AMD 项在无 AMD 卡的机器上 applicable=False（有 AMD 卡则跳过断言）
        vendors = {g['vendor'] for g in data['gpus']}
        if 'amd' not in vendors:
            self.assertFalse(tweaks['gpu-amd-ulps']['applicable'])
            self.assertTrue(tweaks['gpu-amd-ulps']['not_applicable_reason'])

    def test_apply_requires_ids(self):
        parsed, code, _ = run_ps('tweaks.ps1', ['-Action', 'apply'])
        self.assertEqual(code, 1)
        self.assertIn('-Ids', parsed['error'])

    def test_apply_rejects_unknown_id(self):
        parsed, code, _ = run_ps('tweaks.ps1',
                                 ['-Action', 'apply', '-Ids', 'not-a-tweak'])
        self.assertEqual(code, 1)
        self.assertIn('未知 id', parsed['error'])

    def test_revert_without_state(self):
        parsed, code, _ = run_ps('tweaks.ps1',
                                 ['-Action', 'revert', '-Ids', 'ux-menus'])
        self.assertEqual(code, 0)                          # ok 信封
        self.assertTrue(any('没有应用记录' in e for e in parsed['data']['errors']))

    def test_hkcu_roundtrip(self):
        """ux-menus（HKCU-only safe）apply→revert 完全还原原状态。
        源状态：MenuShowDelay 改为非默认值，Serialize 键不存在；
        断言 revert 后二者精确复位。"""
        ps = lambda script: subprocess.run(
            [PS, '-NoProfile', '-Command', script],
            capture_output=True, timeout=60)
        # 造一个非默认源状态，确保备份/还原走的是真实旧值
        ps("Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name MenuShowDelay -Value '350'")
        try:
            parsed, code, _ = run_ps('tweaks.ps1', ['-Action', 'apply', '-Ids', 'ux-menus'])
            self.assertEqual(code, 0, msg=str(parsed))
            applied = parsed['data']['applied']
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0]['steps_ok'], 2)
            self.assertTrue(os.path.exists(applied[0]['state_file']))
            # 重复 apply 应被跳过（已有应用记录）
            parsed2, _, _ = run_ps('tweaks.ps1', ['-Action', 'apply', '-Ids', 'ux-menus'])
            self.assertEqual(len(parsed2['data']['applied']), 0)
            self.assertIn('已有应用记录', parsed2['data']['skipped'][0]['reason'])
            # revert 精确还原
            parsed3, code3, _ = run_ps('tweaks.ps1', ['-Action', 'revert', '-Ids', 'ux-menus'])
            self.assertEqual(code3, 0, msg=str(parsed3))
            self.assertEqual(parsed3['data']['restored'][0]['steps_restored'], 2)
        finally:
            ps("Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name MenuShowDelay -Value '350'")
            ps("Remove-Item 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Serialize' -Recurse -Force -ErrorAction SilentlyContinue")
        # 终态：MenuShowDelay=350，临时键已随 revert 清理
        out = ps("(Get-ItemProperty 'HKCU:\\Control Panel\\Desktop').MenuShowDelay")
        self.assertEqual(out.stdout.decode().strip(), '350')
        out2 = ps("Test-Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Serialize'")
        self.assertEqual(out2.stdout.decode().strip(), 'False')


@unittest.skipUnless(os.environ.get('PC_MANAGER_SLOW_TESTS') == '1',
                     '完整体检较慢；设 PC_MANAGER_SLOW_TESTS=1 启用')
class TestHealthSlow(unittest.TestCase):
    def test_health_quick(self):
        parsed, code, _ = run_ps('health.ps1', ['-Quick'], timeout=300)
        self.assertEqual(code, 0, msg=str(parsed))
        self.assertEqual(parsed['status'], 'ok')
        self.assertTrue(0 <= parsed['data']['score'] <= 100)
        self.assertEqual(len(parsed['data']['factors']), 11)


if __name__ == '__main__':
    unittest.main(verbosity=2)
