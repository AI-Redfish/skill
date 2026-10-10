#!/usr/bin/env python3
"""Reserve a PRD review directory in the current Agent workspace.

Default: <workspace>/.agents/prd-review/YYYY-MM-DD/<prd-name>-HH-MM/
HH-MM is the Windows-compatible spelling of HH:MM. Each invocation reserves
an independent directory; repeated reviews in the same minute get -02, -03...
Python 3.9+ standard library. Prints JSON; does not read or change PRD sources.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

MODES = {
    'logic': 'PRD逻辑梳理',
    'issues': 'PRD问题审查报告',
    'full': 'PRD评审报告',
}


def safe_name(name: str) -> str:
    # Windows forbids these characters and trailing spaces/dots in directory names.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name.strip()).strip(' .-')
    value = value[:80].rstrip(' .-')
    if not value:
        value = '未命名PRD'
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value, re.I):
        value = 'PRD-' + value
    return value


def reserve(workspace: Path, prd_name: str, mode: str, *, output_root=None, timestamp=None):
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f'Agent 工作空间不存在：{workspace}')
    moment = timestamp or datetime.now().astimezone()
    root = Path(output_root) if output_root is not None else Path('.agents/prd-review')
    if not root.is_absolute():
        root = workspace / root
    root = root.resolve()
    day = root / moment.strftime('%Y-%m-%d')
    day.mkdir(parents=True, exist_ok=True)
    name = safe_name(prd_name)
    base = f'{name}-{moment:%H-%M}'
    index = 1
    while True:
        directory = day / (base if index == 1 else f'{base}-{index:02d}')
        try:
            directory.mkdir()
            break
        except FileExistsError:
            index += 1
    stem = f'{name}-{MODES[mode]}'
    return {
        'workspace': str(workspace), 'outputDirectory': str(directory),
        'prdName': prd_name, 'safePrdName': name, 'mode': mode,
        'createdAt': moment.isoformat(),
        'markdown': str(directory / f'{stem}.md'),
        'html': str(directory / f'{stem}.html'),
        'assetsDirectory': str(directory / 'assets'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True,
                        help='当前 Agent 工作空间绝对路径（在切换到 skill/材料目录前确认）')
    parser.add_argument('--prd-name', required=True, help='PRD 标题；不明确时用源文件/材料目录名')
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--output-root', type=Path,
                        help='仅用户明确另指定输出根目录时使用；相对路径基于 Agent 工作空间')
    args = parser.parse_args(argv)
    try:
        data = reserve(args.workspace, args.prd_name, args.mode, output_root=args.output_root)
        print(json.dumps({'status': 'ok', 'data': data}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
