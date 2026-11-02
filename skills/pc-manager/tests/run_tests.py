#!/usr/bin/env python3
"""run_tests.py — pc-manager 脚本单测入口（unittest discover）。

用法: python tests/run_tests.py           # 或 python -m unittest discover -s tests
依赖: 纯标准库；Windows + Windows PowerShell 5.1+。
退出码: 0=全部通过 1=有失败。
"""
import sys
import unittest

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=__file__.rsplit('\\', 1)[0] if '\\' in __file__ else '.', pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
