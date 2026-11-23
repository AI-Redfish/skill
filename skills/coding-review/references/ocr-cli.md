# ocr CLI 集成指南（阿里 open-code-review）

何时读：用户要求变更审查、diff 审查、增量复查、提交前自查，或明确要求使用 ocr / open-code-review 时。全量静态审查不用本文，走 references/bps-security.md。

来源：[alibaba/open-code-review](https://github.com/alibaba/open-code-review)（Apache-2.0），阿里内部 AI 代码审查助手开源版。本 skill 集成其 CLI 文件筛选与规则解析能力（确定性工程），审查分析由宿主 agent 执行（委托模式），无需为 ocr 单独配置 API key。

## 安装与前置

```bash
npm install -g @alibaba-group/open-code-review   # 提供 ocr 命令
```

- 要求 Git >= 2.41。
- `ocr` 未安装且环境不允许安装时：降级为纯 git diff + 本规范流程（文件筛选用 `git --no-pager diff --name-only`），并向用户说明缺少 ocr 的确定性筛选与规则匹配能力。
- 不要在正常路径上先探测 `command -v ocr` 或 `ocr --version`，直接调用，失败再按故障处理节走。

## 模式选择

| | 委托模式（推荐） | 原生模式 |
|---|---|---|
| 谁执行分析 | 宿主 agent（本 skill 的执行者） | ocr 自己调 LLM |
| 凭证 | 复用宿主已有模型，无需配置 | 需 `ocr config provider` 配置 API key |
| 适用 | 常规变更审查 | 用户明确要求 ocr 原生流水线且已配置 key |

用户未指明时用委托模式。原生模式用法见官方文档 https://open-codereview.ai/docs ，核心命令 `ocr review --audience agent -b "业务背景"`。

## 委托模式工作流（六步）

### Step 1：preview——确定性文件筛选

```bash
ocr delegate preview --format json [--from <ref> [--to <ref>]] [--commit <hash>] [--exclude <patterns>]
```

输出：mode（workspace / range / commit）、from/to/commit/merge_base 元数据、reviewable 文件清单（含 status、增删行数）、排除文件及原因。

常用调用：

| 场景 | 命令 |
|------|------|
| 工作区改动（暂存+未暂存+未跟踪） | `ocr delegate preview` |
| 当前分支对 main | `ocr delegate preview --from main` |
| 分支对比 | `ocr delegate preview --from main --to feature` |
| 单提交 | `ocr delegate preview -c abc123` |

有需求上下文时加 `-b "业务背景"` 提升审查质量。

### Step 2：rule——规则获取

```bash
ocr delegate rule --format json [--from <ref>] [--commit <hash>] <path1> <path2> ...
```

传入 Step 1 的 reviewable 文件路径；flags 必须与 Step 1 一致。输出按规则内容分组（共享同一规则的文件归为一组）。大变更可分批获取。

### Step 3：diff——获取变更内容

按 Step 1 返回的 mode 选命令，所有 git 调用加 `--no-pager`：

```bash
# range 模式（用 preview 返回的 merge_base）
git --no-pager diff --no-ext-diff --no-textconv --no-color <merge_base>..<to> -- "<path>"
# commit 模式
git --no-pager show --no-ext-diff --no-textconv --no-color <commit> -- "<path>"
# workspace 模式：已跟踪文件用 diff HEAD；未跟踪文件直接读全文
git --no-pager diff --no-ext-diff --no-textconv --no-color HEAD -- "<path>"
```

- 大 diff 加 `--output="<绝对路径>"` 落盘后分块读取，读完删除；路径选仓库外，先建父目录。
- Git 失败或超时：重试一次，仍失败则该文件记 skipped 并附错误。
- 上下文追查：`git --no-pager log --oneline -- "<path>"`、`git --no-pager blame -- "<path>"`、`git --no-pager show "<ref>:<path>"`。

### Step 4：逐文件审查

1. 以 `(path, status)` 为身份建 checklist（workspace 模式同一 path 可能出现两次：先删后重建）。
2. 每个文件：取 diff → 对照所属规则组 → 按两段式规则审查 → 标记 reviewed 或 skipped（附原因）。
3. 大变更按共享规则和 diff 大小分批，**禁止找到第一个高危就停**（覆盖率是硬约束，见 SKILL.md 总则）。
4. 命中可疑模式时用 file_read / 代码搜索追调用链再下结论。
5. 仅被 preview 标记为 deleted 的文件：可用旧侧内容作上下文追证据，不计入 reviewed。

### Step 5：结构化输出

每个发现固定字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| path | 是 | 相对文件路径 |
| content | 是 | 问题描述 |
| start_line / end_line | 否 | 新文件中的行号范围 |
| category | 否 | bug / security / performance / maintainability / test / style / documentation / other |
| severity | 否 | critical / high / medium / low |

### Step 6：覆盖率核对与报告

- 报告前核对 checklist：每个 previewed 文件必须落为 reviewed 或 skipped；汇总含 `total_files / reviewed_files / skipped_files / coverage_rate`。
- 按严重度分组报告：Critical/High 必报；Medium 带上下文报；Low 仅在明确有价值时报。
- 复核确认的误报静默丢弃，不进报告。
- 实质行为变化（即使有意为之且无缺陷，如删除公共参数导致旧调用方脚本失败）单独说明：受影响工作流、前后行为、证据位置；与严重度发现分开表述，不重复。

## BPS 项目自定义规则（可选）

ocr 规则解析优先级：`--rule <path>` > 仓库 `.opencodereview/rule.json` > 用户级 `~/.opencodereview/rule.json` > 内置。首个命中的用户规则默认替换内置规则；需要同时生效时加 `merge_system_rule: true`。

在 BPS 仓库根建 `.opencodereview/rule.json` 注入本 skill 的两段式规则（示例）：

```json
{
  "rules": [
    {
      "path": "**/*Mapper*.xml",
      "rule": "检查 ${} 直拼：条件值直拼必须报告（高危）；列名拼接须确认 Java 侧经 MyModelUtil.mapToColumnName/MyOrderParam.buildOrderBy 映射，已映射不报；'${item}' IN 直拼须追调用方来源，内部集合不报，前端输入直达报中高危。忽略 pom/logback 占位符。",
      "merge_system_rule": true
    },
    {
      "path": "**/*.java",
      "rule": "检查生产代码 RedisTemplate 调用 .keys(（必须报告）、两参 set( 永久 key（报告前确认 key 集合是否有限）、事务方法内 Feign/MQ 调用（报告）。不报：multiGet 批量读、环境变量名常量、有限注册表类永久 key。",
      "merge_system_rule": true
    }
  ]
}
```

预览某文件会命中哪条规则：`ocr rules check <path>`。

## 故障处理

- `command not found: ocr`：环境允许则 `npm install -g @alibaba-group/open-code-review` 后重试同命令；不允许则说明前置条件并停止，**不要**改用 `ocr review` 或索要 API key。
- `unknown flag: --format`：CLI < v1.9.0。去掉该 flag 用文本输出继续本次审查，保留 mode/ref/文件/规则信息；不要把文本输出硬解析为 JSON 或虚构字段。其他错误的 `unknown flag` 不适用此条：报告并停止。
- `ocr review` 报 LLM 连接错误（仅原生模式）：确认 provider 配置，或征得用户同意转委托模式。
- 大 diff 单文件超过 prompt 预算约 80% 会在调 LLM 前被跳过（原生模式）；委托模式下分块读 diff 文件。
- 中断恢复：`ocr session list` 查会话，`ocr review --resume <id>` 续跑（workspace 模式不支持 resume）。
