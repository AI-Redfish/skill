# html-pages-publish

把用户描述的想法生成为自包含静态 HTML 页面，同步推送到代码托管仓库
（gitee/gitcode/github）配合 Pages 公网访问，或经接口上传到 AgentR 共享 store
获得本机/局域网永久链接；一个仓库托管多个页面，根目录自动维护导航首页。

## 快速开始

### 方式一：发布到 AgentR（本机/局域网永久链接）

前提：AgentR 已包含 pages 模块（`node/src/modules/pages/`），且 AgentR 正在运行。

```bash
# 1) 初始化（自动探测网关连通性）
python scripts/publish.py --init --provider agentr-pages --gateway-base http://127.0.0.1:8319

# 2) 发布页面（workspace/my-page/ 下含 index.html）
python scripts/publish.py --page my-page --src workspace/my-page --update-index
# → 输出 http://127.0.0.1:8319/api/node/pages/my-page/index.html（永久有效，无 token）

# 3) 管理
python scripts/publish.py --list
python scripts/publish.py --remove my-page --update-index
```

页面存储在 `<storeDir>/pages/`（与 agentr.sqlite 同级），自带独立 git 版本记录；
AgentR 重启后链接不变；设置页开启"允许 IP 访问"后局域网设备可直接打开。

### 方式二：发布到 git 仓库（公网出口）

```bash
# 1) 首次初始化（生成 scripts/config.json 并克隆部署仓库）
python scripts/publish.py --init --repo-url https://gitcode.com/<owner>/<repo>.git \
    --provider gitcode --branch master --clone-dir D:/pages-repo

# 2) 发布页面
python scripts/publish.py --page my-page --src workspace/my-page --update-index
```

## 重要提示

**Gitee Pages 已停止服务**（2021-09 起，不再接受新开通）。
需要公网访问请选 `provider=gitcode`（推荐，国内直连）或 `provider=github`
（国内直连不稳定）；`provider=gitee` 仅同步仓库。

详见 `references/pages-providers.md` 与 `SKILL.md`。

## 测试辅助

`tests/mock_agentr.py` 是 AgentR Pages 接口的 mock 网关，可在不启动 AgentR 的
情况下端到端验证 skill 协议：

```bash
python tests/mock_agentr.py 18319 D:/tmp/pages-store &
python scripts/publish.py --init --provider agentr-pages --gateway-base http://127.0.0.1:18319
```
