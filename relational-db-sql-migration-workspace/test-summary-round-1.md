# 测试结论 — Round 1

## 脚本单测（tests/test_fix_dict_timestamp.py）
- 结果：20/20 通过（test-run-1.log，exit 0）
- 覆盖：正常路径（REPLACE VALUES/INSERT SELECT+UNION/UPDATE SET 别名/ON DUPLICATE/稀疏列 7、9）、
  回归（Kingbase UPDATE..SET..FROM 保留 FROM 子句、语句边界不越界）、
  边界（运行时函数/NULL/引号数字不命中、裸整型命中、双引号标识符、非字典表跳过、
  无列清单与 INSERT..SET 范围外、CRLF+中文 UTF-8 字节保持、幂等、无重叠断言）、
  错误路径（文件缺失退出码 2、dry-run=1、apply=0）。

## 端到端（真实仓库数据）
- 数据：12 个 6.0.8.1 归档文件，`git show HEAD~1:` 重建修复前原始字节
  （8 个 CRLF 文件按原行尾风格 smudge）。
- 结果：fix_dict_timestamp.py --apply total=228（e2e-apply.json），输出与已验证
  的修复结果逐字节一致（cmp 12/12 通过）；行尾保持不变。
- 幂等 smoke：对当前已提交（已修复）仓库 dry-run total=0，退出码 0。

## 降级项
- 官方 run_eval 触发评估需 agent 运行环境（模型调用），本轮以 evals.json
  静态用例（4 正向 1 负向）+ 单测代替；未验证依赖该环境的部分在测试报告标注。
- 无凭据类环境信息（纯静态 SQL 技能），env_utils 未使用。
