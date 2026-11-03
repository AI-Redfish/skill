# Windows GBK 编码坑（中文环境必读）

> 内容：Windows 中文 locale 下 Python 工具链的编码崩溃模式与修复。
> 何时读：遇到 `UnicodeDecodeError: 'gbk' codec`、子进程 stdout 为 None、中文输出乱码，或在 Windows 上运行/测试任何含中文 IO 的脚本前。

## 典型现象（本 skill 测试阶段实测）

1. **子进程 stdout 变 None**：父进程 `subprocess.run(..., text=True)`，子进程输出中文 UTF-8/GBK 与父进程解码不一致时，`_readerthread` 解码抛 `UnicodeDecodeError` → `stdout`/`stderr` 为 `None`，业务报错点却在 `json.loads(None)` 处，极具迷惑性
2. **官方脚本读文件崩**：`open()`/`Path.read_text()` 无 `encoding` 参数时按 locale（GBK）解码 UTF-8 文件 → 崩溃；若带 `errors="replace"` 则中文静默变乱码
3. **工具输出乱码**：脚本 `print` 中文到 stdout，Agent/终端按不同编码读取显示乱码

## 修复（按优先级）

1. **`PYTHONUTF8=1` 环境变量**（PEP 540 全局 UTF-8 模式）：一次解决所有无 `encoding` 参数的 `open()/read_text()`，包括改不了的上游脚本。运行第三方工具链时首选
2. **自写脚本**：`sys.stdout.reconfigure(encoding="utf-8")`（Python 3.7+），输出端固定 UTF-8
3. **subprocess 两端对齐**：`encoding="utf-8"` + 子进程 env 注入 `PYTHONIOENCODING=utf-8`，只改一边会崩
4. **JSON 输入文件**：`json.dump(..., ensure_ascii=True)` 纯 ASCII 输出，对任何编码免疫（适合给不可控的第三方脚本喂 JSON）

## 判定口诀

- 报错在 `json.loads`/`read_text` 且消息含 `gbk` → 编码不一致，不是数据问题
- `stdout` 类型是 `NoneType` 而进程退出码正常 → 读线程解码崩了，先查编码再查业务
- 同一代码「有时崩有时不崩」→ 检查两次运行的 `PYTHONIOENCODING`/`PYTHONUTF8` 环境差异
