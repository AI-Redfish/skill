# assets/probes/ — 沉淀探针脚本（语言不限）

从 `runs/<主题>/scratch/` 沉淀出的可复用探针，按功能域分目录存放：

```
probes/
├── iot-property/          # 功能域
│   ├── check_fanout.py    # Python 探针（uv run）
│   └── check_consume.js   # Node 探针（node 直接运行）
└── order/
    └── check_side_effect.sh
```

## 通用契约（任何语言必须遵守）

1. **退出码**：0 = 全部断言通过；非 0 = 存在失败
2. **输出**：断言明细到 stdout（JSON 优先，含 name/ok/evidence），日志到 stderr
3. **凭据**只从 `assets/common/env.secret.json` 读取（经 lib.js / lib.py 合并 env.json），不硬编码
4. **长整型 ID** 一律按字符串处理（Node 走 lib.js 的 bigNumberStrings；Python 值天然保持 str）
5. **依赖装在工作空间侧**，永不装进 skill 目录：
   - Node → 空间根 `package.json` + `npm install`，脚本内 `require('../common/lib.js')`
   - Python → 探针头部写 PEP 723 内联依赖（`# /// script` 块），`uv run <脚本>` 执行，
     脚本内 `sys.path` 加入 `common/` 后 `import lib`
   - 其他语言同理：依赖清单与运行方式写进脚本头部注释
6. 每个探针头部注释写清：**用途、运行方式、依赖**（多文件探针配 README）

## 运行示例

```bash
# Node 探针（依赖已在空间根 npm install）
node probes/iot-property/check_consume.js

# Python 探针（uv 自动按内联依赖装环境）
uv run probes/iot-property/check_fanout.py

# Shell 探针
bash probes/order/check_side_effect.sh
```

Python 探针头部内联依赖示例：

```python
# /// script
# dependencies = ["pymysql>=1.1", "paho-mqtt>=2", "pika>=1.3"]
# ///
```
