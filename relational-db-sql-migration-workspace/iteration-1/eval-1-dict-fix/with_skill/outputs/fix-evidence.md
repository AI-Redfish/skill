# 修复证据（真实仓库数据）
- 预检: bash scripts/ci/check-dict-timestamp.sh files-from → 136 文件中 28 个含字典表操作，228 处违规
- dry-run: fix_dict_timestamp.py 命中 228 处 = 预检条数
- --apply: 12 文件 228 处替换为 CURRENT_TIMESTAMP（e2e-apply.json）
- 验证: 预检复跑 ✅ 0 违规; 逐 hunk 配对 116 行通过; diff 116+/116- 对称; 行尾 CRLF/LF 保持
