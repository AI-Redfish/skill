# 批量修复证据
- 文件清单: /tmp/port-test/files.txt（12 个 6.0.8.1 归档脚本）
- 命中统计: mysql 114 处 + kingbase 114 处 = 228 处
- 行尾守卫: file 比对，LF×4 / CRLF×8 与改动前一致
- 提交: 用户以 39824e6 "feature：SQL修复" 提交（116+/116-）
