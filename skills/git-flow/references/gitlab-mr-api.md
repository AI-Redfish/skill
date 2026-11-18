# GitLab MR 创建（无 CLI / 无 PRIVATE-TOKEN 场景）

## 内容与何时读
内网 GitLab 实例既无 glab CLI、用户也未提供 PRIVATE-TOKEN 时，用「浏览器 web session + CSRF token + JSON body」调 GitLab API v4 创建 MR。适用于本 skill「代码托管平台工作流」中的 GitLab MR 写入任务。

## 前置
- 用户已浏览器登录目标 GitLab，并能提供：登录 cookie（含 `_gitlab_session`）与页面 CSRF token。
- CSRF token 获取：已登录页面 DevTools → Network 任一请求的 `X-CSRF-Token` 请求头，或页面 `meta[name=csrf-token]`。
- 目标仓库 project id：项目首页/设置页可见，或 `GET /api/v4/projects?search=<name>` 查询。

## 操作步骤
1. 核对 source_branch、target_branch 已存在于远端（`git ls-remote` 或 API）。
2. 发起创建（以下均为占位符，不落盘凭据）：

```bash
curl -s -X POST "$GITLAB/api/v4/projects/$PROJECT_ID/merge_requests" \
  -H "Content-Type: application/json" \
  -b "$COOKIES" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"source_branch":"<源分支>","target_branch":"<目标分支>","title":"<标题>","remove_source_branch":false}'
```

3. 成功判据：HTTP 201，响应含 `iid` 与 `web_url`；向用户交付 MR 链接与 iid。
4. 失败对照：401/403 → session 过期或 CSRF 不匹配，请用户重新提供；409 → MR 已存在，回查现有 MR 而不是重建；400 → 核对分支名与 JSON 字段。

## 注意事项
- cookie 与 CSRF 是登录态凭据：只进环境变量或本次命令参数，不写入文件、日志、URL 或汇报文本。
- 该方式依赖实例启用了 session 认证；实例禁用时阻塞，向用户说明并索取 PRIVATE-TOKEN 或改用 CLI。
- 创建后回读 `GET /api/v4/projects/$PROJECT_ID/merge_requests/$IID` 确认状态为 opened，不编造结果。
- 适用范围：内网自建 GitLab（实测于 GitLab API v4，HTTP 实例）。不同 GitLab 大版本的 CSRF 校验行为可能不同，失败时以官方文档为准。
