# auto-browser 系列共享参考实现（会话管理与公共工具）

> 内容：auto-browser 系列各 skill 重复使用的浏览器 CDP 会话管理与公共工具的
> 单一参考说明。何时读：新建 `auto-browser-<x>` 系列 skill 时，按本文约定复制
> 并适配 `_common.py` 与 `browser_session.py`，不再重新设计接口。
> 来源：auto-browser-invoice v0.1.0 首创接口；2026-11 在沉淀
> auto-browser-bilibili / auto-browser-redbook 时确认沿用。适用范围：仅本库
> （D:\develop\GitNote\AI-Redfish\skill\skills）内 auto-browser 系列。

## 参考副本（以文件为准，本文只列约定）

| skill | 端口默认值 | scripts 路径 |
| --- | --- | --- |
| auto-browser-invoice | 9333 | `auto-browser-invoice/scripts/` |
| auto-browser-bilibili | 9341 | `auto-browser-bilibili/scripts/` |
| auto-browser-redbook | 9342 | `auto-browser-redbook/scripts/` |

新建 skill 从任一副本复制后改：log 前缀、`DEFAULT_PORT`（递增取空闲端口，
避免与其他系列实例冲突）、业务脚本名。

## `_common.py` 固定接口（纯标准库，无 CLI）

| 函数 | 职责 |
| --- | --- |
| `setup_utf8()` | Windows GBK 控制台强制 UTF-8，防中文乱码 |
| `log(msg)` | 日志到 stderr，前缀 `[auto-browser-<x>]` |
| `emit_json(data)` | 结果 JSON 到 stdout，`ensure_ascii=False` |
| `fail(code, message, hint)` | 统一错误 JSON 结构 |
| `find_browser()` | 探测 Chrome（优先）/Edge 候选路径 |
| `cdp_url(port)` | `http://localhost:<port>`（Chrome 155+ 拒绝 127.0.0.1 的 Host） |
| `cdp_alive(port)` | GET /json/version 探测，可用返回 dict |
| `port_state(port)` | 三态：`cdp` / `busy` / `free` |
| `slugify(title)` | 目录名：去非法字符、空白换 `-`、截 30 字符 |
| `local_date_str()` / `now_stamp()` | 本地时区日期 YYYYMMDD / 时间戳 |

按需追加平台工具（如 redbook 的 `https_url()`），不删除既有接口。

## `browser_session.py` 行为约定（playwright PEP 723 依赖）

- 子命令：`ensure` / `status` / `close`；JSON 到 stdout，日志到 stderr；
  退出码 0 成功 / 2 失败
- 启动参数仅最小集：`--remote-debugging-port` + `--user-data-dir` +
  `--no-first-run` + `--no-default-browser-check` + `--start-maximized`；
  **绝不注入** `--enable-automation` 等自动化标记，**绝不用 headless**
- Chrome 136+ 默认 profile 静默禁用调试端口 → 必须独立
  `<skill>/profiles/chrome` 作为 user-data-dir（登录态随之持久化）
- 会话记录 `<profile-dir>/.cdp-session.json`（pid/browser/port/started_at）
- `ensure`：端口 `free` → 启动并等 CDP 就绪（60s）；`cdp` → 直接复用
  （`action=attached`）；`busy`（非 CDP 进程占用）→ 报错建议换端口
- `close`：只杀自己记录的 pid（Windows 用 `taskkill /PID <pid> /T /F` 连
  子进程树），**绝不杀用户自己开的浏览器**

## 系列主脚本约定（clip 类）

- 依赖在 main 内延迟 import（`--help` 不触发第三方依赖安装）
- 输出契约：成功 `{"status": "ok", ...}`；失败 `fail()` 结构 + 退出码 2
- 输出目录默认 `<cwd>/clips/<Platform>/<YYYYMMDD>/<slug>-<NN>/`，同天同标题
  文件系统实查递增序号
- note.md front matter：`platform/type/title/author/url/captured_at/path/tags`
  字符串统一 JSON 双引号写法（YAML 兼容）
- 边界：只处理用户主动指定的单篇/当前页；不滚动、不批量、不自动浏览（风控）

## 新建系列 skill 步骤

1. 复制任一参考 skill 的 `_common.py` + `browser_session.py`，改前缀与端口
2. 新写业务 clip 脚本：平台提取函数（JS 注入字符串）+ 下载（带 Referer/UA）+
   note.md 构建，套用上方约定
3. SKILL.md front matter 对齐系列格式（description 含 WHEN/WHEN NOT、
   compatibility、metadata），正文含已知坑与 playbook 引用
4. 验证：`python -m py_compile` 全部脚本；内嵌 JS 用 `node --check` 语法检查；
   `--help` 冒烟；`browser_session.py status` 只读探测
