# pc-manager — Windows 电脑管家（Skill）

复刻开源项目 [GrClean](https://github.com/graent/grclean)（Electron 电脑管家）的
全部核心功能，并移植 [optimizerDuck](https://github.com/itsfatduck/optimizerDuck)
（GPLv3）的 41 项系统调优目录，封装为 AI 编程助手技能：**24 个 PowerShell 脚本 +
AI 编排**，实现清理、优化、体检、调优四类共 24 项能力。功能设计与实现原理来自
对两个项目源码的逆向分析（见 `references/grclean-analysis.md` 与
`references/optimizerduck-tweaks.md`）。

## 快速使用

对 AI 助手说：

> 电脑越来越卡，帮我体检一下，然后清理垃圾和微信缓存（聊天记录别动）

AI 会按 SKILL.md 的标准工作流：扫描（只读）→ 展示分级清单 → 按确认执行 → 汇报。

## 目录结构

```
pc-manager/
├── SKILL.md                 # 主文档（AI 流程与安全红线）
├── scripts/                 # 24 个功能脚本 + common.psm1 安全基础模块（UTF-8 BOM）
├── references/              # 逆向分析报告 / 功能速查 / 安全防线（按需加载）
├── tests/                   # Python 单测（unittest，fixture 隔离）
├── evals/evals.json         # 端到端用例
└── README.md
```

## 安全模型（继承 grclean 纵深防御）

- 扫描/删除分离；删除只认扫描会话 id（防路径注入）
- 受保护路径 fail-safe 拦截（Windows / Program Files / 盘根 / 用户主目录根）
- 默认移入回收站；`-Purge` 才永久删除；danger 项需 `-Force`
- 微信/QQ 聊天记录（.db/.sqlite）机制性锁死，任何参数不可删
- 注册表/右键菜单删除前自动备份；调优项应用前自动备份且可逐项回滚；
  全部变更写审计日志（`%LOCALAPPDATA%\pc-manager\audit.jsonl`）

详见 `references/safety.md`。

## 运行要求

- Windows 10/11，Windows PowerShell 5.1+（系统自带，零依赖）
- 部分操作需管理员权限（脚本会如实报错提示，不自动提权）

## 开发

```bash
python -m unittest discover -s tests -v          # 单测（约 1 分钟）
$env:PC_MANAGER_SLOW_TESTS='1'; python -m unittest discover -s tests -v   # 含慢速体检
```

修改脚本后注意：`.ps1/.psm1` 必须保存为 **UTF-8 with BOM**（PowerShell 5.1 对
无 BOM 的 UTF-8 按 ANSI 解析，中文注释会导致语法错误）。

## 许可说明

本 skill 为功能复刻：清理部分基于对 grclean 公开源码的逆向分析实现，与 grclean
无代码拷贝关系（grclean 本身禁止商用与二次分发，本 skill 仅复刻其公开的
功能设计思路）；调优部分参数级移植自 optimizerDuck（GPLv3），若分发衍生代码
请同样遵守 GPLv3。
