#!/usr/bin/env python3
"""init_workspace.py — 初始化 product-design 产物目录与设计系统骨架。

用途: 在 <workdir>/.agents/out/YYYYMMDD/product-design/<项目名>/ 下创建 DESIGN.md 骨架、
      (多页模式) SITE.md 骨架、pages/ 与 shots/ 子目录。幂等：已存在的文件不覆盖。
依赖: Python 3.9+ 纯标准库，无第三方依赖（python 直跑或 uv run 均可）。
用法:
  uv run init_workspace.py --name "外卖App" --mode multi
  uv run init_workspace.py --name "官网" --workdir /path/to/ws --dir /custom/out
  uv run init_workspace.py --name "官网" --force   # 覆盖已有骨架文件
参数:
  --name     项目名（必需，用于目录名与文档标题）
  --mode     single=单页(默认) / multi=多页（额外生成 SITE.md）
  --workdir  运行时工作目录（默认当前目录），产物落其 .agents/out/YYYYMMDD/product-design/ 下
  --dir      直接指定产物目录（优先级高于 --workdir 推导）
  --force    覆盖已存在的骨架文件（默认跳过）
  --json     结果另存到指定文件路径
退出码: 0=成功(含部分跳过) / 2=参数错误
输出: stdout JSON {status, dir, created[], skipped[], mode}；日志到 stderr。
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
import sys
from pathlib import Path

DESIGN_TEMPLATE = """# Design System: {name}

> 本文件是 `{name}` 的唯一视觉基准。生成任何页面前必须先读本文件并严格遵守；
> 修改视觉规范只改这里，再同步到各页面。

## 0. 刻度配置（1-10，生成前先定档）
| 刻度 | 档位 | 说明 |
|---|---|---|
| 创造力 Creativity | TODO | 1 极简瑞士/5 平衡有个性/10 编辑风大胆非对称 |
| 密度 Density | TODO | 1 画廊大留白/5 平衡分区/10 驾驶舱高密 |
| 变化 Variance | TODO | 1 对称可预测/5 微错位/10 艺术化无重复结构 |
| 动效 Motion | TODO | 1 静态/5 微交互提示/10 电影级编排 |

## 1. 视觉主题与氛围
<!-- TODO: 两三句话定调：气质、密度感受、整体印象（"贵气、克制、有生命感"式描述） -->

## 2. 色板与角色
<!-- 格式：描述名 (#hex) — 功能角色。约束：仅 1 个主强调色且饱和度<80%；禁纯黑 #000000；同一灰阶体系 -->
- 画布底色 (#TODO) — 
- 卡片面 (#TODO) — 
- 主文字 (#TODO) — 
- 次要文字 (#TODO) — 
- 主强调色 (#TODO) — 

## 3. 字体规则
<!-- 中文原型用系统栈：-apple-system, "PingFang SC", "HarmonyOS Sans SC", "MiSans", "Microsoft YaHei", sans-serif；标题字重/字号分级、行高、字距 -->
- 标题：
- 正文：
- 数字/等宽：

## 4. 组件规范
<!-- 按钮（主/次/幽灵+按压态）、卡片（圆角/描边/阴影）、输入框、导航、加载（骨架屏非转圈）、空态、错误态 -->

## 5. 布局原则
<!-- 栅格体系、内容最大宽、留白节奏；禁三等分一排卡片，用 2 列之字/Bento 不对称/横向画廊 -->

## 6. 响应式规则
<!-- 375 / 768 / 1440 三档硬验证；移动端单列、触控目标≥44px、禁横向滚动 -->

## 7. 动效与交互
<!-- 只动 transform/opacity；spring 参数（stiffness 100 / damping 20）；列表级联入场 -->

## 8. 图标与图像
<!-- 图标一律内联 SVG，禁 emoji 当图标；占位图用纯 CSS 渐变或内联 SVG，禁外链图片 -->

## 9. 反模式清单（本项目禁用项）
<!-- 从通用反 AI 味清单裁剪本项目特别注意的项，如：紫色霓虹渐变 / 纯黑 / emoji 图标 / Lorem ipsum / 编造指标 -->
"""

SITE_TEMPLATE = """# Site Vision: {name}

> 多页原型的"长期记忆"。每完成一页必须更新第 2 节勾选状态。

## 1. 项目身份
- 项目名称：{name}
- 使命：
- 目标用户：
- 语气：

## 2. 页面清单（当前状态）
<!-- 完成一页勾选一页；文件名小写英文 -->
- [ ] index.html — 

## 3. 路线图（待办池）
<!-- 按优先级列未做页面；完成即移入第 2 节 -->

## 4. 全局约定
<!-- 导航结构、页脚内容、页面命名规则、共享组件（从 DESIGN.md 引用不复制） -->
"""


def safe_dirname(name: str) -> str:
    """项目名转安全目录名：保留中英文数字与连字符，空白转连字符。"""
    s = re.sub(r"\s+", "-", name.strip())
    s = re.sub(r"[^\w\u4e00-\u9fff\-]", "", s, flags=re.UNICODE)
    return s or "untitled"


def main() -> int:
    ap = argparse.ArgumentParser(description="初始化 product-design 产物目录与骨架（幂等）")
    ap.add_argument("--name", required=True, help="项目名")
    ap.add_argument("--mode", choices=["single", "multi"], default="single", help="单页/多页模式")
    ap.add_argument("--workdir", default=".", help="运行时工作目录（默认当前目录）")
    ap.add_argument("--dir", default=None, help="直接指定产物目录（优先于 --workdir 推导）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在骨架文件")
    ap.add_argument("--json", default=None, help="结果 JSON 另存路径")
    args = ap.parse_args()

    if args.dir:
        root = Path(args.dir)
    else:
        root = Path(args.workdir) / ".agents" / "out" / datetime.now().strftime("%Y%m%d") / "product-design" / safe_dirname(args.name)

    created: list[str] = []
    skipped: list[str] = []

    def write_once(path: Path, content: str) -> None:
        if path.exists() and not args.force:
            skipped.append(str(path))
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(str(path))

    write_once(root / "DESIGN.md", DESIGN_TEMPLATE.format(name=args.name))
    if args.mode == "multi":
        write_once(root / "SITE.md", SITE_TEMPLATE.format(name=args.name))
    for sub in ("pages", "shots"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    result = {"status": "ok", "dir": str(Path.absolute(root)), "mode": args.mode,
              "created": created, "skipped": skipped}
    out = json.dumps(result, ensure_ascii=False, indent=2)
    print(out)
    if args.json:
        Path(args.json).write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # 未预期异常：快失败并给出三要素
        print(json.dumps({"status": "error", "error": {
            "message": f"初始化失败：{exc}",
            "hint": "检查 --dir/--workdir 是否可写；磁盘满或权限不足时处理后重试"}},
            ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
