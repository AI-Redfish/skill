#!/usr/bin/env python3
"""ensure_ffmpeg.py — 探测/自动获取可用的 ffmpeg 二进制。

用途: HTML→MP4 导出流水线的前置依赖。探测顺序: 系统 PATH → 本地缓存
      (<workdir>/.agents/cache/ffmpeg/) → 从 PyPI 镜像下载 imageio-ffmpeg
      wheel 并提取静态二进制(内置 linux/win 双平台, 无需 root)。
      WSL 环境优先取 linux 二进制(WSL 直接 exec win exe 会报 Invalid
      argument, 见 references/tech-notes.md)。
用法: python3 ensure_ffmpeg.py --workdir <目录> [--force]
依赖: Python 3.9+ 纯标准库(urllib/zipfile)。
输出: JSON 到 stdout(status/path/source)；日志到 stderr。
退出码: 0=ok/installed 1=获取失败 2=参数错误。
"""
from __future__ import annotations
import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple/imageio-ffmpeg/",
    "https://mirrors.aliyun.com/pypi/simple/imageio-ffmpeg/",
    "https://pypi.org/simple/imageio-ffmpeg/",
]


def is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def want_windows_binary() -> bool:
    """仅纯 Windows 取 win exe；WSL(sys.platform=linux)取 linux 静态版，
    因 WSL 直接 exec 下载的 win exe 会报 Invalid argument(见 tech-notes)。"""
    return sys.platform == "win32"


def exe_name() -> str:
    return "ffmpeg.exe" if want_windows_binary() else "ffmpeg"


def run_ok(binpath: Path) -> bool:
    try:
        r = subprocess.run([str(binpath), "-version"], capture_output=True, timeout=20)
        return r.returncode == 0 and b"ffmpeg" in (r.stdout + r.stderr)
    except Exception:
        return False


def parse_wheel_urls(simple_html: str) -> list[str]:
    """从 PyPI simple 页面按平台挑选 wheel 下载相对链接。"""
    pat_win = re.compile(r'href="([^"]*imageio_ffmpeg-[^"]*-win_amd64\.whl)[#"]')
    pat_linux = re.compile(r'href="([^"]*imageio_ffmpeg-[^"]*manylinux[^"]*x86_64\.whl)[#"]')
    pats = [pat_win] if want_windows_binary() else [pat_linux]  # 严格按平台, 不交叉
    urls = []
    for pat in pats:
        for href in pat.findall(simple_html):
            if href.startswith("../../"):
                urls.append("https://pypi.tuna.tsinghua.edu.cn/simple/" + href[6:])
            elif href.startswith("/"):
                urls.append("https://pypi.org" + href)
            elif href.startswith("http"):
                urls.append(href)
    return urls


def fetch(url: str, dest: Path, timeout: int = 300) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        return dest.stat().st_size > 1_000_000
    except Exception as e:
        print(f"[warn] 下载失败 {url}: {e}", file=sys.stderr)
        return False


def install_from_pypi(cache_bin: Path) -> Path | None:
    with tempfile.TemporaryDirectory() as td:
        whl = Path(td) / "iff.whl"
        for mirror in MIRRORS:
            try:
                html = urlopen(Request(mirror, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode()
            except Exception as e:
                print(f"[warn] 镜像不可达 {mirror}: {e}", file=sys.stderr)
                continue
            for url in parse_wheel_urls(html):
                if fetch(url, whl):
                    z = zipfile.ZipFile(whl)
                    bins = [n for n in z.namelist() if re.search(r"binaries/ffmpeg-.+(\.exe)?$", n)]
                    want_exe = want_windows_binary()
                    picked = [b for b in bins if b.endswith(".exe") == want_exe]
                    if not picked:
                        continue
                    cache_bin.parent.mkdir(parents=True, exist_ok=True)
                    z.extract(picked[0], cache_bin.parent)
                    src = cache_bin.parent / picked[0]
                    target = cache_bin.parent / exe_name()
                    if src != target:
                        shutil.move(str(src), str(target))
                    target.chmod(0o755)
                    return target
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="探测/获取 ffmpeg")
    ap.add_argument("--workdir", default=".", help="缓存根目录(默认当前目录)")
    ap.add_argument("--force", action="store_true", help="忽略缓存强制重新获取")
    a = ap.parse_args()

    cache_bin = Path(a.workdir).resolve() / ".agents" / "cache" / "ffmpeg" / exe_name()
    if not a.force:
        found = shutil.which("ffmpeg")
        if found and run_ok(Path(found)):
            json.dump({"status": "ok", "path": found, "source": "system"},
                      sys.stdout, ensure_ascii=False, indent=2)
            return
        if cache_bin.is_file() and run_ok(cache_bin):
            json.dump({"status": "ok", "path": str(cache_bin), "source": "cache"},
                      sys.stdout, ensure_ascii=False, indent=2)
            return
    got = install_from_pypi(cache_bin)
    if got and run_ok(got):
        json.dump({"status": "installed", "path": str(got), "source": "pypi-wheel"},
                  sys.stdout, ensure_ascii=False, indent=2)
        return
    json.dump({"status": "error", "error": {
        "message": "ffmpeg 获取失败",
        "reason": "系统无 ffmpeg 且所有 PyPI 镜像下载/校验失败",
        "action": "检查网络后重试；或手动安装 ffmpeg 并加入 PATH；或用 --force 重新下载"}},
        sys.stdout, ensure_ascii=False)
    sys.exit(1)


if __name__ == "__main__":
    main()
