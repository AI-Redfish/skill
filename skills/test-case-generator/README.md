# test-case-generator

需求驱动的功能测试用例生成器：从需求文档（PRD）与技术/设计文档生成
Markdown 格式的功能测试用例集，自动建立 AC 验收标准映射，
覆盖正例、反例、边界、权限四类维度。

## 使用

对 AI 助手说：
- 「根据 <PRD路径> 和 <技术文档路径> 生成测试用例」
- 「检查这份用例文档是否覆盖了 PRD 的所有 AC」

## 目录

```
test-case-generator/
├── SKILL.md                        # 主流程（五步：输入收集→需求解析→用例设计→落盘→脚本校验）
├── references/
│   ├── case-design-guide.md        # 用例设计方法（四维度展开/状态类/双端/历史兼容）
│   └── output-format.md            # 用例文档模板与解析契约（列定义与校验规则对应）
├── scripts/
│   └── validate_cases.py           # 结构校验 + AC 覆盖率统计（纯标准库）
├── tests/
│   └── test_validate_cases.py      # 脚本单测（unittest）
└── evals/
    └── evals.json                  # 端到端触发用例（官方 schema）
```

## 校验脚本单独使用

```bash
# 只做结构校验
python scripts/validate_cases.py --cases 用例文档.md
# 结构校验 + AC 覆盖率
python scripts/validate_cases.py --cases 用例文档.md --prd PRD.md
# 退出码：0=通过；1=存在 error 级问题；2=文件/参数错误
```

校验规则：E001 编号重复 / E002 编号格式 / E003 必填列空 / E004 优先级非法 /
E005 用例类型非法 / E006 无用例表 / W001 未关联 AC / W002 预期结果疑似模糊。

## 运行单测

```bash
python tests/test_validate_cases.py
```
