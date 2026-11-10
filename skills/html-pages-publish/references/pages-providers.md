# 静态托管出口平台速查（pages-providers）

> 调研时间与方式：基于公开网络检索多方交叉验证（官方公告转载、CSDN/php.cn/360 摘要等）。
> 各平台规则可能变化，使用前建议在平台网页端复核当前入口。

## 结论速览

| 平台 | 现状 | 站点 URL 格式 | 部署方式 | 国内直连 | 适用范围 |
|---|---|---|---|---|---|
| **AgentR Pages** | 可用（AgentR 内置） | `http://127.0.0.1:8319/api/node/pages/<slug>/` | HTTP 接口直接上传，无需网页端操作 | ✅ 本机/局域网 | 本机/局域网永久链接 |
| Gitee Pages | **已停止服务**（2021-09 起停新开通，旧服务无法重新开启） | `https://<owner>.gitee.io/<repo>/` | 仓库"服务→Gitee Pages"手动更新 | — | 仅仓库托管 |
| GitCode Pages | 可用 | `https://<owner>.gitcode.io/<repo>/` | 仓库设置/服务 → Pages，选部署分支；推送后可能需手动点更新 | ✅ 稳定 | 公网 |
| GitHub Pages | 可用 | `https://<owner>.github.io/<repo>/` | Settings → Pages 选分支，推送自动部署 | ⚠️ 不稳定 | 公网 |
| 腾讯云 EdgeOne Pages | 可用（免费额度） | 平台分配默认域或自定义域 | 平台绑定 git 仓库自动构建部署 | ✅ 稳定 | 公网 |

## AgentR Pages（agentr-pages provider）

### 接口协议（Node 服务，经网关前缀 `/api/node`）

| 接口 | 说明 |
|---|---|
| `POST /pages/upload` | body `{slug, files:[{path, contentBase64}]}`，整体替换页面；返回 `{slug, files, totalBytes, committed, url}` |
| `GET /pages` | 页面列表 `[{slug, title, updatedAt}]` |
| `GET /pages/<slug>/<相对路径>` | 读取页面文件（inline，按扩展名 MIME，含字体/音视频） |
| `POST /pages/delete` | body `{slug}`，删除页面 |
| `GET /gateway-health`（网关） | 探测网关存活，返回 ok |

### 存储与版本

- 存储：`<storeDir>/pages/<slug>/`（与 agentr.sqlite 同级）；
- 该目录自动 `git init`（独立子仓，不污染 AgentR 主仓），每次上传/删除自动 commit
  （作者 AgentR Pages）；git 不可用时降级为仅存文件（返回 warning），不影响访问；
- 安全：slug 正则校验、路径防穿越（`..`/绝对路径/越界拒绝）、单次上传 ≤50MB/≤500 文件。

### 链接永久性边界

| 场景 | 链接是否有效 |
|---|---|
| AgentR 重启 | ✅（内容实时从磁盘读取，无 token） |
| 仓库/安装位置移动 | ✅（store 在用户数据目录） |
| 数据目录迁移/换电脑 | ⚠️ 需同步搬迁 `storeDir/pages/` |
| 公网 | ❌ 8319 为本机/局域网网关；公网用 gitcode provider |

## 多页面与导航约定

- **一个仓库 = 一个 Pages 站点**；站点内任意路径的静态文件都能按 URL 访问。
- 本 skill 的约定：
  - 每个页面一个子目录 `<slug>/index.html`，访问 `.../<repo>/<slug>/`；
  - 仓库根 `index.html` 为自动生成的导航页（`publish.py --update-index` 维护），
    即站点首页 `.../<repo>/`。
- 需要多个独立站点（独立首页/独立域名）时，建多个仓库并各自配一套 config。

## Gitee Pages 停服依据

- 官方公告（多方转载）：Gitee Pages 服务于 2021-09-01 前后逐步停止，
  "不再接受新开通申请，已开通的旧服务也无法重新开启"；
- 2022-2023 年起多个站长迁移记录（CSDN：gitee.io 终究还是下线了）。
- 代码托管功能本身不受影响：往 gitee 仓库 push 页面仍然有效，
  只是**没有官方静态托管出口**。

## GitCode Pages 开通步骤（推荐出口）

1. 在 gitcode.com 创建**公开**仓库（与 config.json 的 `repo_url` 一致）；
2. 仓库页面 → 设置/服务 → 找到 Pages 功能模块 → 选择部署分支
   （必须与 `config.json.branch` 一致）→ 保存开启；
3. 每次 `publish.py` 推送后，若页面未更新，回到同一页面手动点"更新/重建"；
4. 首次开启后入口 URL 形如 `https://<owner>.gitcode.io/<repo>/`。

## HTTPS 推送凭证（Windows）

- 首次 push 时 Git Credential Manager 会弹窗登录平台账号，凭据自动保存；
- 或使用访问令牌：`git remote set-url origin https://<token>@<平台域名>/<owner>/<repo>.git`
  （令牌在平台"私人令牌/Token"页面生成，需 repo 读写权限）；
- SSH 方式：`git remote set-url origin git@<平台域名>:<owner>/<repo>.git`
  并把公钥加入平台账号（本机当前未配置 gitee 公钥）。
