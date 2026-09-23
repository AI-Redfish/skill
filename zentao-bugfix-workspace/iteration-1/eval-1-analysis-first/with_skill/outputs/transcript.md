# eval-1 执行记录（脚本级离线）
python3 run_eval1_offline.py → {"pass_rate": 1.0, "passed": 6, "failed": 0, "total": 6}
流转：scaffold_analysis 生成骨架（含分析先行提示 + （待填写）标记）→ analysis_complete_status=yes
→ 模拟 AI Edit 补全（填入根因证据 文件:行号）→ analysis_complete_status=no → 删除文件 → missing。
