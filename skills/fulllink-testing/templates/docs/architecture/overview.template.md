# 总体架构（01-architecture/overview.md）

> status: draft | reviewed
> 用途：全局架构说明——系统拓扑、各仓库职责、技术栈、部署单元、外部依赖。
> 相当于项目级技术文档总纲；代码考古来自 repos/ 下各仓库，不确定标"未知"。

## 系统拓扑

```text
<仓库/应用> ──调用方式（HTTP/MQ/MQTT）──> <仓库/应用>
例：bps-web ──HTTP──> basic-platform-service ──MQ──> 下游系统
```

## 仓库职责（repos/）

| 仓库 | 角色 | 技术栈 | 职责说明 |
|---|---|---|---|
| basic-platform-service | backend（primary） | Java/SpringCloud | 基础平台服务：设备、监控、订单 |
| bps-web | frontend | Vue | 前端主应用 |

## 部署单元

| 服务 | 来源仓库 | 部署形态 | 健康检查 | 指纹获取 |
|---|---|---|---|---|
| monitor | basic-platform-service | jar ×2 实例 | /actuator/health | /actuator/git-commit-id |

## 外部依赖

<第三方系统、硬件协议、注册中心、对象存储等；说明数据边界>

<!-- 填写规则：
1. 拓扑图覆盖"仓库级"节点即可，模块级关系写在 module-map.md，实体流转写在 data-flow.md
2. 内容来自代码考古与环境台账，禁止凭记忆/猜测填写 -->
