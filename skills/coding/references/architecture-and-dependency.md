# 模块架构与依赖约束（吸收 bps-business-application-architecture）

## 1. 三条铁律

1. 禁止 `common/*` 反向依赖 `application/*`
2. 禁止新增 `service -> service` 编译期依赖
3. 禁止把 `allow-circular-references: true` 当作设计完成

## 2. 默认模块拆分与依赖方向

```text
application/<biz>/
├── <biz>-api                # Feign 契约 / RPC 接口 / DTO 入口
└── <biz>-service            # 运行时 Spring Boot 服务

common/business/common-<biz>-dto   # DTO/VO/常量/轻量枚举（只依赖 common-core）
common/domain/common-<biz>         # Model/Mapper/XML/Domain Service（依赖 dto + dbutil + core）
```

```text
Controller -> Domain Service -> Mapper/XML
         \-> Feign Client -> other-service-api
```

设计顺序：业务边界 → 共享契约 → 领域归属 → 服务形态 → 最后才配 POM。

## 3. 反模式清单（命中即整改）

| 反模式 | 正确做法 |
|---|---|
| `common-domain -> xxx-api` 反向依赖 | 共享 DTO 下沉 `common/business/common-xxx-dto` |
| `a-service -> b-service` 服务直连 | 走 `b-api` + `common-b-dto`；必要时本地 Facade |
| `Helper/Util` 注入 ServiceImpl | Helper 只查询/转换；执行放 Executor；编排放 Facade/Orchestrator |
| 自注入只为触发事务代理 | 拆事务 Facade + 领域 Service；次选注入接口代理 |
| `@Lazy` 打断环后不管 | 改单向调用/事件/协调服务；`@Lazy` 只是过渡 |

循环依赖治理优先级：P0 真实多 Bean 环 > P1 双向 Service 依赖 > P2 `@Lazy` 打断环 > P3 自注入。

## 4. POM 要点

- `common-*-dto`：保持轻量，仅 `common-core`。
- `common-<biz>`：dto + dbutil + core，按需补低层公共能力，绝不依赖 `application/*`。
- `<biz>-api`：dto + openfeign 契约层依赖。
- `<biz>-service`：api + common-<biz> + nacos/feign 运行时 starter。

场景 B（只补远程契约）：只扩展 `*-api`，DTO 下沉 `common-*-dto`。
场景 C（历史 `service -> service`）：短期收敛调用方向 + DTO 下沉；中期改 `service -> api` + Feign/事件/编排器。

## 5. 每次边界调整必须自答

是否新增/消除了 `service -> service`、双向注入、自注入、`allow-circular-references` 风险？模块拓扑详见 `<仓库>/.share/skills/bps-business-application-architecture/references/module-topology-and-cycle-risk.md`。
