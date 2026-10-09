#!/usr/bin/env python3
"""fulllink-test 工作空间公共库（Python 版模板，随 init 落位到 <workspace>/assets/common/lib.py）

用法（探针脚本内）：
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
    import lib
运行：推荐 uv run——探针脚本头部用 PEP 723 内联声明依赖，uv 自动安装：
    # /// script
    # dependencies = ["pymysql>=1.1,<2", "paho-mqtt>=2,<3", "pika>=1.3,<2"]
    # ///
    然后执行：uv run probes/<功能域>/check_xxx.py
    （也可自行 pip install 后用 python 运行；依赖只装在工作空间侧）
约定：
  - 凭据从同目录 env.secret.json 读取（gitignore），env.json 只放地址/名称
  - 长整型 ID（tenantId 等）一律按字符串处理（本库返回值保持 str，不做 int 转换）
  - 断言统一走 report.py 的 check()，探针脚本退出码非 0 = FAIL
  - 第三方库全部懒加载：探针用到哪个中间件才需要装哪个依赖
"""
from __future__ import annotations
import json
import os
import random
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_json(name: str) -> dict:
    with open(os.path.join(_HERE, name), encoding="utf-8") as f:
        return json.load(f)


def deep_merge(base: dict, override: dict | None) -> dict:
    """深合并 secret 覆盖普通配置（仅 dict 递归，其他类型直接覆盖）。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


_cfg = _read_json("env.json")
try:
    _secret = _read_json("env.secret.json")
except (OSError, json.JSONDecodeError):
    _secret = {"envs": {}}  # 未配置凭据属正常降级

_active = _cfg.get("activeEnv")
env = deep_merge((_cfg.get("envs") or {}).get(_active, {}),
                 (_secret.get("envs") or {}).get(_active, {}))
fixtures = _cfg.get("fixtures") or {}


# ---------- DB（pymysql，懒加载） ----------
def open_db(profile: dict | None = None):
    """打开 MySQL 连接；行值经 DictCursor 返回，长整型 ID 保持字符串语义。"""
    profile = profile or env
    db = profile.get("db") or {}
    if not db.get("password"):
        raise RuntimeError("DB 凭据未配置：请在 env.secret.json 的 envs.<activeEnv>.db.password 填入")
    import pymysql  # 懒加载：不用 DB 的探针无需安装
    return pymysql.connect(
        host=db.get("host"), port=int(db.get("port", 3306)),
        user=db.get("user"), password=db["password"], database=db.get("database"),
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


# ---------- RabbitMQ（pika，懒加载） ----------
def connect_amqp(profile: dict | None = None):
    import pika  # 懒加载：不用 MQ 的探针无需安装
    profile = profile or env
    mq = profile.get("rabbitmq") or {}
    if not mq.get("password"):
        raise RuntimeError("RabbitMQ 凭据未配置：请在 env.secret.json 填入 rabbitmq.password")
    return pika.BlockingConnection(pika.ConnectionParameters(
        host=mq.get("host"), port=int(mq.get("port", 5672)),
        credentials=pika.PlainCredentials(mq.get("user", ""), mq["password"]),
    ))


# ---------- RabbitMQ Management（HTTP API，纯标准库） ----------
def mgmt_get(path: str, timeout: int = 10, profile: dict | None = None) -> dict:
    """RabbitMQ Management HTTP API 只读查询（如队列深度/消费者数）。"""
    import base64
    import urllib.request
    profile = profile or env
    mq = profile.get("rabbitmq") or {}
    if not mq.get("managementUrl"):
        raise RuntimeError("rabbitmq.managementUrl 未配置（env.json envs.<环境>.rabbitmq.managementUrl）")
    if not mq.get("password"):
        raise RuntimeError("RabbitMQ 凭据未配置：请在 env.secret.json 填入 rabbitmq.password")
    req = urllib.request.Request(mq["managementUrl"].rstrip("/") + path)
    token = base64.b64encode(f'{mq.get("user", "")}:{mq["password"]}'.encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def queue_state(queue: str, profile: dict | None = None) -> dict:
    """查询指定队列当前状态（depth/unacked/consumers）——对账与冒烟常用。"""
    from urllib.parse import quote
    q = mgmt_get(f"/api/queues/%2F/{quote(queue, safe='')}", profile=profile)
    return {"messages": q.get("messages", 0), "ready": q.get("messages_ready", 0),
            "unacked": q.get("messages_unacknowledged", 0), "consumers": q.get("consumers", 0)}


# ---------- MQTT（paho-mqtt>=2，懒加载） ----------
def connect_mqtt(profile: dict | None = None):
    import paho.mqtt.client as mqtt  # 懒加载
    profile = profile or env
    m = profile.get("mqtt") or {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if m.get("username"):
        client.username_pw_set(m["username"], m.get("password"))
    client.connect(m.get("host"), int(m.get("port", 1883)), keepalive=60)
    return client  # 收发前 client.loop_start()，结束 loop_stop() + disconnect()


# ---------- 工具 ----------
def new_message_id() -> str:
    """19 位数字消息ID（与后端 16~19 位习惯一致），对账锚点；一律按字符串处理。"""
    return f"{int(time.time() * 1000)}{random.randint(0, 999999):06d}"
