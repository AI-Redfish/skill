#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
html-pages-publish: 把本地生成的静态 HTML 页面同步到 git 托管仓库，供 Pages 服务暴露公网访问。

纯 Python 标准库实现（Python 3.9+），依赖 git 命令行（>=2.20）。

典型用法：
    # 1) 首次初始化：生成配置模板并克隆部署仓库
    python publish.py --init --repo-url https://gitee.com/<owner>/<repo>.git \
        --provider gitcode --branch master --clone-dir D:/pages-repo

    # 2) 发布一个页面（页面文件在 workspace/my-page/ 下，入口 index.html）
    python publish.py --page my-page --src D:/workspace/my-page --update-index

    # 3) 删除一个页面
    python publish.py --remove my-page --update-index

    # 4) 只刷新根导航页并推送
    python publish.py --update-index

    # 5) 查看已发布页面与访问地址
    python publish.py --list
"""

import argparse
import base64
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_NAME = "config.json"

PROVIDER_URL_TEMPLATES = {
    # provider: (站点根 URL 模板, 说明)
    "gitcode": "https://{owner}.gitcode.io/{repo}/",
    "github": "https://{owner}.github.io/{repo}/",
    "gitee": "https://{owner}.gitee.io/{repo}/",
    "edgeone": "{custom_domain}",
    "custom": "{custom_domain}",
}

PROVIDER_NOTES = {
    "agentr-pages": (
        "AgentR Pages：页面经接口上传到 AgentR 共享 store（含 git 版本记录），"
        "链接永久有效（无 token，AgentR 重启后不变）；范围为本机/局域网，"
        "公网访问请改用 provider=gitcode。首次使用需启动 AgentR（restart.bat）。"
    ),
    "gitee": (
        "[警告] Gitee Pages 已于 2021-09 起停止服务：不再接受新开通申请，"
        "已开通的旧服务也无法重新开启。推送已完成，页面是否可公网访问取决于"
        "该仓库此前是否已成功开通 Pages（概率很低）。建议改用 provider=gitcode "
        "（仓库设置→Pages 开启）或腾讯云 EdgeOne Pages。"
    ),
    "gitcode": (
        "GitCode Pages：首次使用需在仓库网页端开启：仓库页 → 设置/服务 → Pages，"
        "选择部署分支（须与配置的 branch 一致）后保存；每次推送后如未自动更新，"
        "请在同一页面手动点击更新/重建。"
    ),
    "github": (
        "GitHub Pages：仓库 Settings → Pages → 选择部署分支保存即可；"
        "推送后自动部署（1~2 分钟）。注意：国内直连 github.io 可能不稳定。"
    ),
    "edgeone": "EdgeOne/自定义托管：按对应平台流程绑定部署目录，脚本只负责同步仓库。",
    "custom": "custom：自行完成托管绑定，脚本只负责把页面推送到仓库。",
}

# agentr-pages 专用：导航页 slug
AGENTR_NAV_SLUG = "nav"


def run(cmd, cwd=None, check=True, capture=True):
    """执行 shell 命令，返回 (returncode, stdout+stderr 文本)。"""
    proc = subprocess.run(
        cmd, cwd=cwd, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "").strip()
    if check and proc.returncode != 0:
        raise RuntimeError(
            "命令失败 [{}]: {}\n{}".format(" ".join(cmd), cwd or ".", out)
        )
    return proc.returncode, out


def check_git():
    try:
        _, out = run(["git", "--version"])
        ver = out.split()[-1] if out else "?"
        return ver
    except FileNotFoundError:
        raise SystemExit("[错误] 未找到 git 命令，请先安装 Git（https://git-scm.com）")


def valid_slug(slug):
    """页面名：小写字母/数字/短横线，1~64 位，字母或数字开头。"""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug or ""))


def load_config(config_path):
    if not config_path.exists():
        raise SystemExit(
            "[错误] 未找到配置 {}。请先运行 --init 完成初始化。".format(config_path)
        )
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not cfg.get("provider"):
        raise SystemExit("[错误] 配置缺少字段: provider")
    if cfg["provider"] == "agentr-pages":
        if not cfg.get("gateway_base"):
            raise SystemExit("[错误] 配置缺少字段: gateway_base")
        return cfg
    for key in ("repo_url", "provider", "branch", "clone_dir"):
        if not cfg.get(key):
            raise SystemExit("[错误] 配置缺少字段: {}".format(key))
    return cfg


def save_config(config_path, cfg):
    config_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ensure_clone(cfg):
    """确保本地部署仓库克隆存在且可用，返回克隆目录 Path。"""
    clone_dir = Path(cfg["clone_dir"]).expanduser()
    git_dir = clone_dir / ".git"
    if git_dir.exists():
        return clone_dir
    if clone_dir.exists() and any(clone_dir.iterdir()):
        raise SystemExit(
            "[错误] 目录 {} 已存在且非空、不是 git 仓库，请更换 clone_dir。".format(clone_dir)
        )
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    print("[sync] 克隆部署仓库: {}".format(cfg["repo_url"]))
    code, out = run(["git", "clone", "-b", cfg["branch"], cfg["repo_url"],
                     str(clone_dir)], check=False)
    if code != 0:
        # 分支可能尚不存在（空仓库），尝试普通克隆
        code, out = run(["git", "clone", cfg["repo_url"], str(clone_dir)], check=False)
        if code != 0:
            raise SystemExit(
                "[错误] 克隆失败：{}\n提示：HTTPS 方式需要已保存的凭证"
                "（Windows Git Credential Manager 会弹窗；或改用 SSH 并先配置公钥）。".format(out)
            )
    return clone_dir


def git_sync_clone(cfg, clone_dir):
    """推送前与远程对齐（pull --rebase），失败不阻断（可能是无上游的新仓库）。"""
    run(["git", "pull", "--rebase", "autostash"], cwd=clone_dir, check=False)


def copy_page(src: Path, dest: Path):
    """把页面文件/目录拷贝到仓库内 dest。入口必须是 index.html。"""
    if src.is_file():
        if src.name != "index.html":
            raise SystemExit(
                "[错误] --src 为单文件时必须命名为 index.html（Pages 站点入口约定）。"
            )
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / "index.html")
        return [dest / "index.html"]
    if src.is_dir():
        index = src / "index.html"
        if not index.exists():
            raise SystemExit("[错误] 目录 {} 中缺少 index.html 入口。".format(src))
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        return sorted(p for p in dest.rglob("*") if p.is_file())
    raise SystemExit("[错误] --src 不存在: {}".format(src))


def build_index(clone_dir: Path, cfg):
    """扫描仓库内所有页面子目录，重建根导航 index.html。"""
    pages = []
    for child in sorted(clone_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if (child / "index.html").exists():
            title = child.name
            m = re.search(r"<title>(.*?)</title>",
                          (child / "index.html").read_text(encoding="utf-8",
                                                           errors="ignore"),
                          re.S | re.I)
            if m and m.group(1).strip():
                title = m.group(1).strip()[:40]
            pages.append((child.name, title))
    site = cfg.get("site_name") or "Pages 导航"
    items = "\n".join(
        '      <li><a href="{0}/index.html">{1}</a>'
        '<span class="path">/{0}/</span></li>'.format(slug, title)
        for slug, title in pages
    ) or '      <li class="empty">暂无页面：发布第一个页面后这里会自动更新</li>'
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, "Microsoft YaHei", sans-serif; margin: 0;
         background: #f6f7f9; color: #1f2328; }}
  main {{ max-width: 640px; margin: 8vh auto; padding: 0 16px; }}
  h1 {{ font-size: 1.3rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ background: #fff; border: 1px solid #e4e7eb; border-radius: 10px;
        padding: 14px 18px; margin-bottom: 10px; display: flex; gap: 10px;
        align-items: baseline; }}
  a {{ font-size: 1.02rem; color: #0969da; text-decoration: none; font-weight: 600; }}
  a:hover {{ text-decoration: underline; }}
  .path {{ color: #8b949e; font-size: .85rem; margin-left: auto; }}
  .empty {{ color: #8b949e; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0d1117; color: #e6edf3; }}
    li {{ background: #161b22; border-color: #30363d; }}
    a {{ color: #58a6ff; }}
  }}
</style>
</head>
<body>
<main>
  <h1>{site}</h1>
  <ul>
{items}
  </ul>
</main>
</body>
</html>
""".format(site=site, items=items)
    root_index = clone_dir / "index.html"
    changed = (not root_index.exists()) or root_index.read_text(
        encoding="utf-8", errors="ignore") != html
    if changed:
        root_index.write_text(html, encoding="utf-8")
    return changed, [p[0] for p in pages]


def public_url(cfg, slug=None):
    if cfg["provider"] == "agentr-pages":
        base = (cfg.get("gateway_base") or "http://127.0.0.1:8319").rstrip("/")
        return base + "/api/node/pages/" + ("{}/".format(slug) if slug else "")
    tpl = PROVIDER_URL_TEMPLATES.get(cfg["provider"])
    if not tpl:
        return None
    owner = cfg.get("owner") or ""
    repo = cfg.get("repo") or ""
    m = re.search(r"[/:]([^/:]+?)(?:\.git)?/([^/]+?)(?:\.git)?/?$",
                  cfg["repo_url"])
    if m and not owner:
        owner, repo = m.group(1), m.group(2)
    base = tpl.format(owner=owner, repo=repo,
                      custom_domain=cfg.get("custom_domain", "<未配置 custom_domain>"))
    if not base.endswith("/"):
        base += "/"
    return base + ("{}/".format(slug) if slug else "")


# ---------- agentr-pages：接口上传到 AgentR 共享 store，永久链接访问 ----------

def agentr_request(cfg, method, path, payload=None, timeout=180):
    base = (cfg.get("gateway_base") or "http://127.0.0.1:8319").rstrip("/")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            message = json.loads(detail).get("message") or detail
        except Exception:
            message = detail
        raise SystemExit("[错误] AgentR 接口 {} {} 返回 {}: {}".format(method, path, error.code, message))
    except urllib.error.URLError as error:
        raise SystemExit(
            "[错误] 无法连接 AgentR 网关 {}（{}）。\n提示：1) 先启动 AgentR（其目录下 restart.bat）；"
            "2) 检查 config.json 的 gateway_base 是否正确。".format(base, error.reason))


def collect_page_files(src: Path):
    """页面目录/单文件 → [{path, contentBase64}]，并校验入口与大小。"""
    if src.is_file():
        if src.name != "index.html":
            raise SystemExit("[错误] --src 为单文件时必须命名为 index.html。")
        pairs = [(Path("index.html"), src)]
    elif src.is_dir():
        if not (src / "index.html").exists():
            raise SystemExit("[错误] 目录 {} 中缺少 index.html 入口。".format(src))
        pairs = [(p.relative_to(src).as_posix() and Path(p.relative_to(src).as_posix()), p)
                 for p in sorted(src.rglob("*")) if p.is_file()]
    else:
        raise SystemExit("[错误] --src 不存在: {}".format(src))
    result = []
    total = 0
    for rel, path in pairs:
        data = path.read_bytes()
        total += len(data)
        result.append({"path": rel.as_posix(), "contentBase64": base64.b64encode(data).decode("ascii")})
    if total > 50 * 1024 * 1024:
        raise SystemExit("[错误] 页面总大小超过 50MB 上限。")
    return result, total


def build_nav_page_html(pages, site_name):
    """从 AgentR 页面列表生成导航页（链接为网关同源绝对路径）。"""
    items = "\n".join(
        '      <li><a href="/api/node/pages/{0}/index.html">{1}</a>'
        '<span class="path">/{0}/</span></li>'.format(p["slug"], p.get("title") or p["slug"])
        for p in pages)
    items = items or '      <li class="empty">暂无页面</li>'
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site}</title>
<style>
  body {{ font-family: system-ui, "Microsoft YaHei", sans-serif; margin: 0;
         background: #f6f7f9; color: #1f2328; }}
  main {{ max-width: 640px; margin: 8vh auto; padding: 0 16px; }}
  h1 {{ font-size: 1.3rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ background: #fff; border: 1px solid #e4e7eb; border-radius: 10px;
        padding: 14px 18px; margin-bottom: 10px; display: flex; gap: 10px; align-items: baseline; }}
  a {{ color: #0969da; text-decoration: none; font-weight: 600; }}
  a:hover {{ text-decoration: underline; }}
  .path {{ color: #8b949e; font-size: .85rem; margin-left: auto; }}
  .empty {{ color: #8b949e; }}
</style>
</head>
<body>
<main>
  <h1>{site}</h1>
  <ul>
{items}
  </ul>
</main>
</body>
</html>
""".format(site=site_name, items=items)


def lan_ip_hint():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except Exception:
        return None


def agentr_flow(args, cfg):
    """provider=agentr-pages 的主流程：全部通过 AgentR HTTP 接口完成。"""
    gateway = (cfg.get("gateway_base") or "http://127.0.0.1:8319").rstrip("/")
    dirty = False

    if args.remove:
        if not valid_slug(args.remove):
            raise SystemExit("[错误] 非法页面名: {}".format(args.remove))
        result = agentr_request(cfg, "POST", "/api/node/pages/delete", {"slug": args.remove})
        print("[remove] {}: {}".format("已删除" if result.get("removed") else "页面不存在（忽略）", args.remove))
        dirty = True

    if args.page:
        if not valid_slug(args.page):
            raise SystemExit("[错误] 非法页面名: {}".format(args.page))
        if not args.src:
            raise SystemExit("[错误] --page 需要配对 --src（页面目录或 index.html）")
        files, total = collect_page_files(Path(args.src).expanduser())
        result = agentr_request(cfg, "POST", "/api/node/pages/upload",
                                {"slug": args.page, "files": files})
        print("[publish] 已上传 {0}（{1} 个文件，{2} 字节）到 AgentR store".format(
            args.page, result.get("files", len(files)), result.get("totalBytes", total)))
        if result.get("warning"):
            print("[warn] " + result["warning"])
        dirty = True

    if args.update_index or args.page or args.remove:
        pages = agentr_request(cfg, "GET", "/api/node/pages").get("pages", [])
        nav = build_nav_page_html(pages, cfg.get("site_name") or "Pages 导航")
        payload = {"slug": AGENTR_NAV_SLUG, "files": [
            {"path": "index.html",
             "contentBase64": base64.b64encode(nav.encode("utf-8")).decode("ascii")}]}
        agentr_request(cfg, "POST", "/api/node/pages/upload", payload)
        print("[index] 导航页已更新（{} 个页面）".format(len(pages)))
        dirty = True

    if args.list:
        pages = agentr_request(cfg, "GET", "/api/node/pages").get("pages", [])
        print("站点入口: {}".format(public_url(cfg, AGENTR_NAV_SLUG)))
        for item in pages:
            print("  - {0}  {1}  ->  {2}".format(
                item["slug"], item.get("title", ""), public_url(cfg, item["slug"])))
        if not pages:
            print("  （暂无页面）")
        return

    if not dirty:
        print("[done] 无变更。")
        return

    ip = lan_ip_hint()
    lan_port = urllib.parse.urlparse(gateway).port or (443 if gateway.startswith("https") else 80)
    print("")
    print("===== 发布结果 =====")
    print("站点入口(本机): {}".format(public_url(cfg, AGENTR_NAV_SLUG)))
    if args.page:
        print("本次页面(本机): {}".format(public_url(cfg, args.page)))
    if ip:
        print("局域网地址(需在 AgentR 设置页开启允许 IP 访问): http://{0}:{1}/api/node/pages/{2}/index.html".format(
            ip, lan_port, args.page or AGENTR_NAV_SLUG))
    print("出口说明: " + PROVIDER_NOTES.get(cfg["provider"], ""))


def main():
    ap = argparse.ArgumentParser(
        description="同步本地 HTML 页面到 git 仓库并输出 Pages 访问地址")
    ap.add_argument("--config", default=str(Path(__file__).parent / CONFIG_NAME),
                    help="配置文件路径（默认 skill scripts 目录下 config.json）")
    ap.add_argument("--init", action="store_true", help="生成配置模板并克隆仓库")
    ap.add_argument("--repo-url", help="部署仓库地址（--init 时必填）")
    ap.add_argument("--provider", choices=list(PROVIDER_URL_TEMPLATES) + ["agentr-pages"],
                    help="Pages 出口平台")
    ap.add_argument("--gateway-base", help="AgentR 网关地址（provider=agentr-pages 时用，默认 http://127.0.0.1:8319）")
    ap.add_argument("--branch", help="部署分支（Pages 服务绑定的分支）")
    ap.add_argument("--clone-dir", help="部署仓库本地克隆目录")
    ap.add_argument("--site-name", help="根导航页标题（可选）")
    ap.add_argument("--page", help="页面 slug（小写字母/数字/短横线）")
    ap.add_argument("--src", help="页面来源：目录（含 index.html）或单个 index.html")
    ap.add_argument("--remove", metavar="SLUG", help="删除已发布页面")
    ap.add_argument("--update-index", action="store_true",
                    help="重建根导航 index.html")
    ap.add_argument("--list", action="store_true", help="列出已发布页面")
    ap.add_argument("--message", help="自定义提交信息")
    args = ap.parse_args()

    config_path = Path(args.config)
    check_git()

    # ---------- init ----------
    if args.init:
        if args.provider == "agentr-pages":
            cfg = {
                "provider": "agentr-pages",
                "gateway_base": (args.gateway_base or "http://127.0.0.1:8319").rstrip("/"),
                "site_name": args.site_name or "Pages 导航",
            }
            save_config(config_path, cfg)
            print("[init] 配置已写入: {}".format(config_path))
            agentr_request(cfg, "GET", "/api/node/pages")
            print("[init] AgentR 网关连接正常。")
            print("[init] " + PROVIDER_NOTES["agentr-pages"])
            return
        if not (args.repo_url and args.provider and args.branch and args.clone_dir):
            raise SystemExit("[错误] --init 需要 --repo-url --provider --branch --clone-dir")
        cfg = {
            "repo_url": args.repo_url,
            "provider": args.provider,
            "branch": args.branch,
            "clone_dir": str(Path(args.clone_dir).expanduser()),
            "site_name": args.site_name or "Pages 导航",
        }
        save_config(config_path, cfg)
        print("[init] 配置已写入: {}".format(config_path))
        clone_dir = ensure_clone(cfg)
        print("[init] 部署仓库已就绪: {}".format(clone_dir))
        print("[init] " + PROVIDER_NOTES[cfg["provider"]])
        return

    cfg = load_config(config_path)
    if args.site_name:
        cfg["site_name"] = args.site_name
        save_config(config_path, cfg)
    if cfg["provider"] == "agentr-pages":
        return agentr_flow(args, cfg)
    clone_dir = ensure_clone(cfg)
    git_sync_clone(cfg, clone_dir)

    # ---------- list ----------
    if args.list:
        _, pages = build_index(clone_dir, cfg)
        print("部署仓库: {}".format(clone_dir))
        print("部署分支: {}".format(cfg["branch"]))
        print("站点入口: {}".format(public_url(cfg)))
        for p in pages:
            print("  - /{}/ -> {}".format(p, public_url(cfg, p)))
        return

    # ---------- remove ----------
    dirty = False
    if args.remove:
        if not valid_slug(args.remove):
            raise SystemExit("[错误] 非法页面名: {}（限小写字母/数字/短横线）".format(args.remove))
        target = clone_dir / args.remove
        if target.exists():
            shutil.rmtree(target)
            print("[remove] 已删除页面目录: {}".format(target))
            dirty = True
        else:
            print("[remove] 页面不存在（忽略）: {}".format(target))

    # ---------- publish page ----------
    if args.page:
        if not valid_slug(args.page):
            raise SystemExit("[错误] 非法页面名: {}（限小写字母/数字/短横线）".format(args.page))
        if not args.src:
            raise SystemExit("[错误] --page 需要配对 --src（页面目录或 index.html）")
        dest = clone_dir / args.page
        files = copy_page(Path(args.src).expanduser(), dest)
        print("[publish] 页面文件（{} 个）:".format(len(files)))
        for f in files:
            print("    " + str(f))
        dirty = True

    # ---------- update index ----------
    if args.update_index or args.page or args.remove:
        changed, pages = build_index(clone_dir, cfg)
        if changed:
            print("[index] 根导航页已重建，共 {} 个页面".format(len(pages)))
            dirty = True
        else:
            print("[index] 根导航页无变化")

    if not dirty:
        print("[done] 无变更。")
        return

    run(["git", "add", "-A"], cwd=clone_dir)
    code, out = run(["git", "status", "--porcelain"], cwd=clone_dir)
    if not out:
        print("[done] 内容与远程一致，无需提交。")
        return
    else:
        msg = args.message or "publish: {0} at {1}".format(
            args.page or (args.remove and "remove " + args.remove) or "index",
            time.strftime("%Y-%m-%d %H:%M:%S"))
        run(["git", "commit", "-m", msg], cwd=clone_dir)
        code, out = run(["git", "push"], cwd=clone_dir, check=False)
        if code != 0:
            raise SystemExit(
                "[错误] push 失败：{}\n提示：1) 检查远程凭证（HTTPS 需保存的令牌/弹窗登录，"
                "SSH 需已配置公钥）；2) 若远程有新提交，先 git pull --rebase 后重试；"
                "3) 确认对仓库有写权限。".format(out)
            )
        print("[push] 已推送到 {0} ({1})".format(cfg["repo_url"], cfg["branch"]))

    print("")
    print("===== 发布结果 =====")
    print("站点入口: {}".format(public_url(cfg)))
    if args.page:
        print("本次页面: {}".format(public_url(cfg, args.page)))
    print("出口说明: " + PROVIDER_NOTES[cfg["provider"]])


if __name__ == "__main__":
    main()
