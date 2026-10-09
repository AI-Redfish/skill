# assets/probes/ — 沉淀测试脚本（按功能模块分目录，**Python/uv 优先**）

从 `runs/<主题>/tmp/`（本轮临时脚本目录）沉淀出的可复用脚本。
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
测试执行期间业务仓库内容只读：不改代码、配置、锁文件或自带测试，不在仓库中
安装/构建/写缓存；脚本、截图、trace、日志等放仓库外的工作空间，缺陷只记报告。

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
7. 每个探针头部注释写清：**用途、运行方式、依赖**（多文件探针配 README）

## 运行示例

```bash
# 后端/中间件探针（首选：uv 自动按内联依赖装环境）
uv run assets/probes/monitor-iot/check_fanout.py

# 前端页面 e2e（Vue 等优先 playwright；首次先装浏览器）
uv run playwright install chromium
uv run assets/probes/order-operation/check_order_flow.py

# Node 探针（仅在 Python 不适合时）
node assets/probes/monitor-iot/check_consume.js
```

## 前端 playwright 探针要点（前后端项目）

- 头部 PEP 723 内联 `playwright` 依赖；页面目标地址从环境台账/env.json 取，不写死；
  测试账号等敏感输入从 env.secret.json 对应环境读
- 断言页面元素/交互流转，关键数据断言配合 MCP（websocket_read/http_send）或
  mysql_query 取证；退出码与 stdout 断言遵守通用契约，测后沉淀到
  `assets/probes/<前端模块>/`（与 docs/02-modules/<前端模块>/ 同名对齐）

以下仅展示页面冒烟和库加载，不是完整 E2E，不足以判定业务流程 PASS。
正式 E2E 应补齐登录、真实用户操作、最终业务结果及必要副作用断言。

```python
# /// script
# dependencies = ["playwright>=1.40,<2"]
# ///
"""例：订单列表页加载与新建入口 —— uv run check_order_flow.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "common"))
import lib, report
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(lib.env["front"]["apps"]["operation"])   # 地址来自台账/env.json
    report.check("列表加载出数据行", page.locator(".order-row").count() > 0,
                 f"rows={page.locator('.order-row').count()}")
    browser.close()
sys.exit(1 if report.summary()["failed"] else 0)
```

Python 探针头部内联依赖示例：

```python
# /// script
# dependencies = ["pymysql>=1.1,<2", "paho-mqtt>=2,<3", "pika>=1.3,<2"]
# ///
```

沉淀时依赖一律锁定版本范围，防上游 breaking change。
