# runs 记录与查找规范

> runs/ 是每轮测试的记录区，含计划、结果、证据、录像及临时运行产物。
> 每轮测试读本文件；创建计划前建立记录，完成/阻断/中止后更新记录与索引。

## 目录与命名

```text
runs/
├── INDEX.md                         # 所有轮次，按开始时间倒序，不截断历史
├── by-module/
│   ├── order.md                     # 订单模块的全部轮次（含跨模块测试）
│   └── monitor-iot.md               # 同名于 docs/02-modules/<模块>/
├── 20261008-143025-123456__order__订单回归/
│   ├── run.json                     # 本轮唯一编号、精确时间与结构化元数据
│   ├── plan.md
│   ├── report.md
│   ├── report.html
│   ├── report-assert.md             # 可选断言明细
│   ├── evidence/<环境>/<模块>/<场景>/ # 日志、截图、trace 等持久证据
│   ├── videos/<环境>/<场景>/<尝试>/   # UI 录像与步骤时间线
│   └── tmp/                         # 临时脚本、隔离构建和运行副本
└── 20261008-161200-654321__cross-module__属性上报回归/
    └── ...
```

- `<run-id>` = `YYYYMMDD-HHMMSS-ffffff__<模块标识>__<主题>`，时间取本轮开始时本机
  时间、精确到微秒；run.json 时间必须是带 UTC 偏移的 ISO 8601，避免时区歧义。
- 单模块用知识层的模块名；多个模块用 `cross-module`，完整模块集合在 run.json
  和计划/报告头部列出；影响分析未完成用 `unclassified`，确定范围后更新模块集合，
  已创建 run-id/目录不改名。模块名既可英文也可中文，主题简短且有业务含义。
- 路径字符由工具规范化，禁止目录分隔符/路径穿越；目录创建独占，不复用或覆盖
  已有目录。同模块同主题再次运行仍创建新 run-id；单轮内失败重试留各尝试证据。
- 每轮内部固定文件名 plan.md/report.md/report.html，由外层目录识别时间、模块和主题。
  不把报告、截图或日志散放 runs/ 根目录，也不把永久证据放 tmp/。
- 下文及其他 skill 文档里的 `runs/<run-id>/` 均指此目录；不包含独立业务项目层级。

## 工具操作（Python 标准库，仓库之外）

```bash
# 首轮建立记录；module/environment 可重复传入，模块名与知识层对齐
python3 <skill_dir>/scripts/run_records.py create --workspace <空间> \
  --module order --topic 订单回归 --environment 147 --mode existing

# 跨模块；新一轮复跑通过 rerun-of 关联之前的 run-id，不写回旧报告
python3 <skill_dir>/scripts/run_records.py create --workspace <空间> \
  --module monitor-iot --module monitor-forward --topic 属性上报回归 \
  --environment 147 --mode local --rerun-of <旧run-id>

# 测试执行前按已有的确认结果填写 run.json（仓库/分支/commit/path、黑盒版本等）
# 执行后更新结果与人工核对状态；多模块不改目录，只更新 module 参数/元数据
python3 <skill_dir>/scripts/run_records.py update --run-dir <本轮目录> \
  --status completed --summary 自动断言通过，UI录像待核对 --human-review pending

# 失败准备也要登记结果（报告仍生成）：status blocked；取消/中止用 aborted
python3 <skill_dir>/scripts/run_records.py update --run-dir <本轮目录> \
  --status blocked --summary RabbitMQ连接失败，等待用户处理

# 历史查找索引重建（生成索引，不移动或重写既有测试报告）
python3 <skill_dir>/scripts/run_records.py reindex --workspace <空间>
```

create/update 都自动重建总索引与模块索引。计划未执行状态为 planned，执行时更新
running；状态为 completed/blocked/aborted 时记录结束时间。completed 仅表示自动
执行结束，不代表通过：结论与 PASS/FAIL/BLOCKED/MANUAL 数量、人工状态另记。
无需全链路测试时状态为 not-required，并保留范围分析依据。

run.json 必填字段：schemaVersion、runId、startedAt、finishedAt、modules、topic、
environments、executionMode、status、summary、humanReview、rerunOf、repositories、
components、counts。repositories 每项含登记名、实际 path、branch、commit、baseline；
components 每项含黑盒登记名、path/服务入口和版本；counts 存各结果数量（未知用 null）。
人工状态：not-applicable/pending/reviewed/issues/missing-evidence；仅有实际人工反馈
才能登记 reviewed。字段不存凭据或完整请求中的敏感数据。开始/结束时间与报告保持一致。

## 索引与报告

- INDEX.md：开始/结束时间（含时区）、模块、主题、环境/运行方式、执行状态、结论、
  人工核对状态、run-id、计划/Markdown/HTML/录像链接。各文件尚未生成显示“未生成”，
  不创建假链接。按模块索引使用同样字段，跨模块轮次在相关模块各有一行，但报告一份。
- 文件链接为相对路径，需保留视频、证据与报告目录关系。先在索引定位本轮，再看
  report.html、录像或 evidence/，无需打开所有报告猜测来源。
- 计划和报告标题写“模块集合｜主题”，头部写 run-id、开始/结束时间、环境、方式及
  仓库分支/commit；结果矩阵逐项标模块和稳定测试点编号，跨模块列涉及模块。
  每点记录实际方式、数据快照、预期/实测，预定 UI 未完成解释原因与替代检查，
  数据证据按 evidence/<环境>/<模块>/<编号>/attempt-<序号>/ 留存，详见报告契约。
- 复跑读取 run.json 的已记录范围，不根据目录名猜分支/环境；新轮次设置 rerunOf，
  不覆盖旧结果。人工核对反馈更新原轮次时，同步 run.json/Markdown/HTML 与索引。
- 旧目录没有 run.json 时，reindex 在总索引的“旧记录（元数据未登记）”单列原路径及
  存在的报告，模块/时间标未知，不用文件修改时间冒充测试时间，不自动改名或迁移。
  用户或现有报告能提供可靠信息时，在原目录补 run.json 后重建索引即可。
