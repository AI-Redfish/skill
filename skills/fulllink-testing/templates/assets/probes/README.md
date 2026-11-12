# assets/probes/ — 沉淀测试脚本（按功能模块分目录，**Python/uv 优先**）

从 `runs/<run-id>/tmp/`（本轮临时脚本目录）沉淀出的可复用脚本。
**目录按功能模块整理，与 `docs/02-modules/<模块名>/` 同名对齐**
（模块清单见 `docs/01-architecture/module-map.md`）：

```
assets/
├── common/                  # 公共库（全局共享，不按模块分）
└── probes/
    ├── monitor-iot/         # ← 对应 docs/02-modules/monitor-iot/（后端：Python/uv）
    │   └── check_fanout.py
    ├── order-operation/     # ← 前端模块：playwright 页面 e2e（Vue 等优先）
    │   └── check_order_flow.py
    └── order/
        └── check_side_effect.py
```

模块的探针清单在 `docs/02-modules/<模块名>/README.md` 的"已沉淀探针"节双向登记。

## 通用契约（仅 Python/uv 与 Node.js；优先 Python）

优先编写 E2E：从真实页面/API/消息/任务入口触发，验证完整链路的最终业务结果；
单点检查仅补充取证，无法执行 E2E 时在计划与报告注明原因及未覆盖环节。
Git 仓库和黑盒组件均按实际 path 只读引用（空间内外皆可，不强制 clone）；
不改代码、配置、锁文件或自带测试，不在原目录安装/构建/写缓存。
脚本、截图、trace、日志等放组件目录外工作空间；启动或服务问题只读取证、记录阻断
并通过对话提示用户，不自行修补源码、配置、启动脚本或现有服务。

1. **测试脚本仅允许 Python（uv run）与 Node.js，优先 Python**；不生成 Shell 或
   其他语言脚本，不在任何业务 Git 仓库新增或修改单元/集成/E2E 测试；e2e 页面测试由本 skill 在仓库外生成
   （Python playwright），不用 git 仓库自带的 e2e
2. **退出码**：0 = 全部断言通过；非 0 = 存在失败
3. **输出**：断言明细到 stdout（JSON 优先，含 name/ok/evidence），日志到 stderr
4. **凭据**只从 `assets/common/env.secret.json` 读取（经 lib.py / lib.js 合并 env.json），不硬编码
5. **测试输入样本与预期值都在执行时从目标环境 DB 现查**（fixtures 存筛选条件，
   SQL 见 docs/05-test-data.md），禁止把 ID/SN 写死在脚本里；
   长整型 ID 一律按字符串处理
6. **依赖装在工作空间侧**，永不装进 skill 目录或 repos/ 下的代码仓库：
   - Python → 探针头部 PEP 723 内联依赖（`# /// script` 块），`uv run <脚本>` 执行，
     脚本内 `sys.path` 加入 `common/` 后 `import lib`
   - Node → 空间根 `package.json` + `npm install`，脚本内 `require('../common/lib.js')`
7. 每个测试点编号关联实际 UI/非 UI 方式和证据；执行时记录脱敏数据来源、选样时间、
   输入/前置状态、预期、实测到 evidence/<环境>/<模块>/<编号>/attempt-<序号>/，
   不能只输出 PASS。页面流程预定 UI 未执行/未完成时报告具体原因、替代检查与缺口。
8. 每个探针头部注释写清：**用途、运行方式、依赖**（多文件探针配 README）

## 运行示例

```bash
# 后端/中间件探针（首选：uv 自动按内联依赖装环境）
uv run assets/probes/monitor-iot/check_fanout.py

# 前端页面 e2e（Vue 等优先 playwright；首次先装浏览器）
uv run --with 'playwright>=1.40,<2' python -m playwright install chromium
uv run assets/probes/order-operation/check_order_flow.py --run-dir runs/<run-id> --attempt 1

# Node 探针（仅在 Python 不适合时）
node assets/probes/monitor-iot/check_consume.js
```

## 前端 playwright 探针要点（前后端项目）

- 头部 PEP 723 内联 `playwright` 依赖；页面目标地址从环境台账/env.json 取，不写死；
  测试账号等敏感输入从 env.secret.json 对应环境读
- UI 自动化必须完整录屏，默认 slowMo 500ms、状态就绪后停留 1000ms；成功、失败及
  重试均保留 `runs/<run-id>/videos/<环境>/<场景>/<尝试>/`，finally 中关闭 context
  后确认录像落盘。报告给出视频链接与待人工核对项，详见 skill 的 ui-recording.md。
- 断言页面元素/交互流转，关键数据断言配合 MCP（websocket_read/http_send）或
  mysql_query 取证；退出码与 stdout 断言遵守通用契约，测后沉淀到
  `assets/probes/<前端模块>/`（与 docs/02-modules/<前端模块>/ 同名对齐）

以下仅展示页面冒烟和库加载，不是完整 E2E，不足以判定业务流程 PASS。
正式 E2E 应补齐登录、真实用户操作、最终业务结果及必要副作用断言。

```python
# /// script
# dependencies = ["playwright>=1.40,<2"]
# ///
"""页面冒烟与录屏示例；正式 E2E 需补齐业务操作与最终结果断言。
uv run check_order_flow.py --run-dir <workspace>/runs/<run-id> --attempt 1
"""
import argparse, json, sys, time
from pathlib import Path
workspace = Path(__file__).resolve().parents[3]  # assets/probes/<模块>/<脚本>
sys.path.insert(0, str(workspace / "assets" / "common"))
import lib
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--run-dir", required=True)
parser.add_argument("--attempt", type=int, required=True)
args = parser.parse_args()
run_dir = Path(args.run_dir).resolve()
run_dir.relative_to((workspace / "runs").resolve())  # 拒绝仓库内或空间外输出
if args.attempt < 1:
    parser.error("attempt 必须为正整数")
active_env = lib._cfg["activeEnv"]
if not isinstance(active_env, str) or Path(active_env).name != active_env or active_env in (".", ".."):
    parser.error("环境名必须是单个目录名")
video_dir = run_dir / "videos" / active_env / "page-smoke" / str(args.attempt)
video_dir.mkdir(parents=True, exist_ok=False)  # 重跑换 attempt，不覆盖旧证据
opts = lib.env.get("uiAutomation", {})
size = opts.get("videoSize", {"width": 1280, "height": 720})
steps, videos = [], []
with sync_playwright() as p:
    browser = p.chromium.launch(slow_mo=opts.get("slowMoMs", 500))
    context = None
    try:
        auth = workspace / "assets" / "common" / ".auth" / f"{active_env}.json"
        context = browser.new_context(
            viewport=size, record_video_dir=str(video_dir), record_video_size=size,
            **({"storage_state": str(auth)} if auth.is_file() else {}))
        recordings = []
        context.on("page", lambda opened: recordings.append(opened.video) if opened.video else None)
        page = context.new_page()
        started = time.monotonic()
        page.goto(lib.env["front"]["apps"]["operation"])
        page.locator(".order-row").first.wait_for(state="visible")  # 按实际页面替换
        steps.append({"step": "列表页面就绪", "page": "main",
                      "seconds": round(time.monotonic() - started, 2)})
        page.wait_for_timeout(opts.get("stepPauseMs", 1000))  # 状态就绪后留给人看
        print("L0 诊断：页面已展示；未验证完整业务流程", file=sys.stderr)
        # 正式 E2E：逐步操作/等待预期状态/记录时间点/停留/核对最终业务结果。
        # 输入需可见节奏时：locator.press_sequentially(text, delay=opts.get("typingDelayMs", 80))
    finally:
        try:
            if context is not None:
                context.close()  # 等待录像保存，包括异常路径
                for recording in recordings:
                    video_path = Path(recording.path())
                    if not video_path.is_file() or video_path.stat().st_size == 0:
                        raise RuntimeError("录屏证据缺失")
                    videos.append(str(video_path.relative_to(run_dir)))
        finally:
            browser.close()
            (video_dir / "steps.json").write_text(json.dumps(
                {"steps": steps, "videos": videos, "humanReview": "待核对"},
                ensure_ascii=False, indent=2), encoding="utf-8")
# 本示例仅 L0 冒烟；正式脚本的退出码取决于业务断言结果。
```

Python 探针头部内联依赖示例：

```python
# /// script
# dependencies = ["pymysql>=1.1,<2", "paho-mqtt>=2,<3", "pika>=1.3,<2"]
# ///
```

沉淀时依赖一律锁定版本范围，防上游 breaking change。
