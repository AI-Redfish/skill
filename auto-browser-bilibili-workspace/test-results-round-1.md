# 测试结果 round 1 — auto-browser-bilibili

测试范围：静态验证 + 冒烟 + 错误路径实跑。**端到端抓取实测按用户决定暂缓**，
报告标注"未验证依赖真实浏览器会话与有效链接的部分"。

| # | 用例 | 类型 | 结果 |
| --- | --- | --- | --- |
| 1 | py_compile 三脚本 | 静态 | ✅ 通过 |
| 2 | 内嵌提取 JS `node --check` | 静态 | ✅ 通过 |
| 3 | `--help` 冒烟（不触发依赖安装） | 冒烟 | ✅ 通过（exit 0） |
| 4 | `browser_session.py status` 只读探测 | 冒烟 | ✅ JSON 正确（state=free） |
| 5 | 无参数 → bad-args | 错误路径 | ✅ JSON 结构正确，exit=2 |
| 6 | 非规划域名 --url → bad-url | 错误路径 | ✅ 校验提前，未启动浏览器，exit=2 |
| 7 | `--merge` 空目录 → no-streams | 错误路径 | ✅ exit=0，reason 正确 |

evals/evals.json：5 用例（2 正向、1 元数据负向、2 拒绝负向），供后续端到端触发评估。

未验证（依赖真实环境）：页面提取、DASH 下载、ffmpeg 合并、登录态画质。
