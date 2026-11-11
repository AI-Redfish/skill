---
name: html-pages-publish
description: 把用户描述的想法一键生成为自包含静态 HTML 页面，并同步推送到用户的代码托管仓库（gitee/gitcode/github），配合 Pages 服务暴露公网访问；也可通过 HTTP 接口上传到 AgentR 共享 store，获得本机/局域网永久访问链接，支持一个仓库托管多个页面并自动维护根导航页。当用户说「帮我做个页面/网页并发布出去」「生成 HTML 同步到 gitee/gitcode 仓库」「把页面部署到 Pages 让我能公网访问」「发布到 AgentR/在 AgentR 里访问这个页面」「更新/删除已发布的某个页面」「给页面仓库建导航首页」时使用本 skill。不处理需要后端/数据库的动态网站，不处理站点构建框架（Jekyll/VitePress 等）的编译流程。
compatibility: 脚本 Python 3.9+ 纯标准库（python/python3 直跑，零安装）；需 git ≥2.20 且已配置对目标仓库的推送凭证（HTTPS 凭证或 SSH 公钥）；Windows/macOS/Linux 均可。
metadata:
  author: AI-Redfish
  version: "1.0.0"
---

# html-pages-publish — AI 生成 HTML 页面并同步到仓库 Pages 公网访问

一条流水线：**描述 → 生成自包含 HTML → 本地预览确认 → 脚本同步到部署仓库 → 输出公网 URL**。

```
问需求(slug/入口) → 生成页面到本地暂存目录 → 用户预览确认
   → python scripts/publish.py --page <slug> --src <暂存目录>/<slug> --update-index
   → 输出站点入口 URL 与本次页面 URL（+出口平台注意事项）
```

## 关键事实与平台选择（必须先读，最高优先级）

1. **两条出口，按用户需求选**：
   - **公网访问** → git 类 provider（gitcode/github/gitee），走仓库 + Pages 服务；
   - **本机/局域网永久链接** → `provider=agentr-pages`，页面经 HTTP 接口上传到 AgentR
     共享 store（`<storeDir>/pages/`，自带独立 git 版本记录），访问链接形如
     `http://127.0.0.1:8319/api/node/pages/<slug>/index.html`，**无 token、重启不变**；
     前提：本机正在运行 AgentR（`D:/develop/GitNote/RedfishOpenSource/AgentR/restart.bat`）。
2. **Gitee Pages 已停止服务**（2021-09 起，来源：gitee 官方公告，多方转载确认）：
   不再接受新开通申请，已开通的旧服务也无法重新开启。
   - 因此 `provider=gitee` 时**只做仓库托管**，脚本会输出停服警告；
   - 除非用户明确说"我的 gitee 仓库早已开通过 Pages 且仍在线"，否则应主动推荐
     用户改用 `provider=gitcode`（GitCode Pages，国内可直连，机制与 GitHub Pages 类似）
     或 `provider=github`（国内直连不稳定）。
3. **多页面机制**（回答"一个仓库可以有多个页面吗"）：
   - Pages 模式都是 **一个仓库/一个 store = 一个站点**，但**站点内可含任意多个页面**：
     git 类按仓库子目录路径访问（`.../<repo>/<slug>/`），AgentR 按
     `/api/node/pages/<slug>/index.html` 访问；
   - git 类的部署目录根部 `index.html` 是站点首页，本 skill 用它做**自动导航页**；
     AgentR 模式的导航页是 `nav` 页面（同样自动维护）；
   - 想要多个**独立域名**的站点才需要多个仓库。
4. 部署分支：`config.json` 里的 `branch` 必须与 Pages 服务在网页端绑定的分支一致（仅 git 类）。
5. 仓库需为**公开仓库**（Pages 类服务通用要求）；私有仓库无法被公网 Pages 暴露（AgentR 不受限）。

## 双闭环流程（最高优先级，优先于其他默认行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环
1. 回答前先提问，**每次只问一个问题**，根据回答继续追问
2. 提问围绕：页面主题与受众、期望的内容结构、风格偏好、页面名（slug）、
   是否新页面还是更新已有页面、成功标准
3. 对"用户真正想要什么"有 95% 信心才停止提问；未达 95% 只提问澄清，
   不给最终方案（用户消息已足以达到 95% 信心时可直接执行，
   但最终输出必须列出关键假设）

### 第二闭环：输出审查闭环
1. 形成答案后不直接输出，先自查：页面是否符合描述？链接/资源路径是否为相对路径？
   发布命令参数是否正确？URL 是否拼接正确？
2. 发现问题→自行修正→再次审查，重复"审查—修正—再审查"，
   直到对输出结果至少有 95% 的准确性信心

### 最终输出要求
1. 先一句话复述用户真实需求
2. 再给出最终方案：明确、可执行、可直接使用
3. 说明关键假设、剩余不确定性，以及为什么已达到 95% 信心；
   不确定处明确标注，不假装确定

## 首次使用初始化（必须最先完成）

配置文件 `scripts/config.json` 不存在时，按顺序完成：

### 情形 A：provider=agentr-pages（AgentR 本机/局域网永久链接）
1. 确认 AgentR 正在运行（未运行则提示用户先执行 `D:/develop/GitNote/RedfishOpenSource/AgentR/restart.bat`）；
2. 生成调用：
   `python <skill_dir>/scripts/publish.py --init --provider agentr-pages --gateway-base http://127.0.0.1:8319`
   （init 会自动探测网关连通性；本仓库用户默认 gateway 即此地址）；
3. 无需仓库/分支/克隆，完成后即可直接发布。

### 情形 B：git 类 provider（公网出口）
1. 向用户确认：部署仓库地址（gitee/gitcode/github 的 HTTPS 或 SSH URL）、
   出口平台 provider、部署分支、本地克隆目录；
2. 生成调用：
   `python <skill_dir>/scripts/publish.py --init --repo-url <仓库URL> --provider <gitcode|github|gitee|edgeone|custom> --branch <分支> --clone-dir <本地目录>`；
   注意 `--clone-dir` 必须是该操作系统的**原生绝对路径**（Windows 形如 `D:/pages/<repo>`，
   不要写 Git Bash/WSL 的 `/mnt/...` 风格路径，否则 Python 读配置时会解析错位）；
3. 用户在网页端完成该平台 Pages 服务的首次开通（gitcode/github：仓库设置 → Pages
   → 选择同一分支保存；gitee：已停服，见上）；
4. 确认推送凭证可用：脚本 push 失败时按其输出提示处理
   （HTTPS：Windows Git Credential Manager 弹窗登录/保存令牌；SSH：先配公钥）。

## 页面生成规范（AI 生成 HTML 必须遵守）

1. **单文件自包含**：每个页面是 `<暂存目录>/<slug>/index.html` 一个文件，
   CSS/JS 全部内联；UTF-8 编码；`<html lang="zh-CN">` + viewport meta；
2. **相对路径**：页面内引用的一切资源用相对路径；图片/字体等额外文件
   放 `<暂存目录>/<slug>/` 内对应子目录（脚本会整目录同步）；
   允许用公共 CDN（需在交付说明里注明"断外网时该资源降级"）；
3. **无构建步骤**：不引入需要 npm/webpack 等编译的框架，用原生 HTML/CSS/JS 或
   CDN 版库；静态展示优先，不做需后端的交互；
4. **slug 命名**：小写字母/数字/短横线，1~64 位，字母或数字开头
   （脚本会校验）；同一 slug 再次发布=更新该页面；
5. **内容质量**：结构完整（标题/正文/页脚）、移动端可用、无乱码、
   无死链；生成的页面先本地预览再发布。

## 发布工作流（标准步骤）

1. 生成页面到本地暂存目录 **`<工作目录>/.agents/out/html-pages-publish/workspace/<slug>/index.html`**
   （非 git 托管产物目录：本地暂存不入任何仓库；**发布后的页面需要被 git 管理**——
   由脚本推送到部署仓库）；不要把暂存页放进 skill 目录或业务仓库；
2. 请用户预览确认（`file://` 直接打开，或
   `python -m http.server -d <目录>` 后给 `http://localhost:8000`）；
3. 用户确认后执行发布（按 provider 二选一）：
   - AgentR：`python <skill_dir>/scripts/publish.py --page <slug> --src <工作目录>/.agents/out/html-pages-publish/workspace/<slug> --update-index`
     （自动上传 + 刷新 nav 导航页 + 输出永久链接与局域网地址）；
   - git 类：同一条命令，自动同步到部署仓库并输出公网 URL；
4. 向用户输出：站点入口 URL、本次页面 URL、出口平台注意事项
   （脚本会打印）；
5. 更新已有页面：同名 slug 重新生成并再次执行第 3 步；
   删除页面：`--remove <slug> --update-index`；
   查看列表：`--list`（AgentR 模式从接口实时获取）。

## 输出精简约束与产物 git 托管指定（所有落盘产物与答复通用）

1. **只落盘有用的**：只把用户会直接使用的产物写到磁盘；过程稿、中间草稿、重复副本、无人引用的说明文件一律不落盘。
2. **中间产物隔离**：本地预览稿、调试副本收进 `<工作目录>/.agents/out/html-pages-publish/`（非 git 托管产物目录）。
3. **落盘前自问**：写文件前先问"用户会直接使用它吗"；不会就不写，改为文字说明。
4. **答复同理**：汇报只讲结论、URL、路径与待办，不复述中间过程与脚本日志。
5. **产物 git 托管指定**：本地暂存页面不需要被 git 管理，放 `<工作目录>/.agents/out/html-pages-publish/workspace/`；发布到部署仓库的页面**需要被 git 管理**（由脚本推送）。

## 常见故障与处理

| 症状 | 处理 |
|---|---|
| 无法连接 AgentR 网关 | 先启动 AgentR（restart.bat）；检查 gateway_base；探测 `GET /gateway-health` 应返回 ok |
| 上传返回 400 非法页面名/路径 | slug 用小写字母/数字/短横线；页面内避免绝对路径资源 |
| 页面 404 | git 类：Pages 服务未开启/分支不一致/未点更新；AgentR：确认 AgentR 在运行 |
| gitee.io 地址不可访问 | Gitee Pages 已停服，换 provider=gitcode 或 agentr-pages |
| push 失败鉴权错误 | HTTPS：更新凭证管理器中保存的令牌；SSH：检查公钥已加入平台账号 |
| push 失败非快进 | 先 `git pull --rebase` 部署仓库再重试 |
| 中文乱码 | 确认页面 `<meta charset="UTF-8">` 且文件以 UTF-8 无 BOM 保存 |

## 参考与机制细节

出口平台对比、URL 格式、开通步骤、AgentR Pages 接口协议详见 `references/pages-providers.md`。
