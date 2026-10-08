/**
 * fulllink-test 工作空间公共库（模板，随 init 落位到 <workspace>/assets/common/lib.js）
 *
 * 用法：const lib = require('./lib.js')
 * 依赖：工作空间侧 npm install amqplib mysql2 mqtt（package.json 在工作空间内维护）
 * 约定：
 *   - 凭据从同目录 env.secret.json 读取（gitignore），env.json 只放地址/名称
 *   - 长整型 ID（tenantId 等）一律按字符串处理（bigNumberStrings）
 *   - 断言统一走 report.js 的 check()，探针脚本退出码非 0 = FAIL
 */
const fs = require('fs');
const path = require('path');

/** 深合并 secret 覆盖普通配置（仅对象递归，其他类型直接覆盖） */
function deepMerge(base, override) {
  const out = Object.assign({}, base);
  for (const k of Object.keys(override || {})) {
    if (base && typeof base[k] === 'object' && !Array.isArray(base[k]) &&
        override[k] && typeof override[k] === 'object' && !Array.isArray(override[k])) {
      out[k] = deepMerge(base[k], override[k]);
    } else if (override[k] !== undefined) {
      out[k] = override[k];
    }
  }
  return out;
}

function readJson(p) {
  return JSON.parse(fs.readFileSync(path.join(__dirname, p), 'utf8'));
}

const _cfg = readJson('env.json');
let _secret = { envs: {} };
try { _secret = readJson('env.secret.json'); } catch (e) { /* 未配置凭据属正常降级 */ }

/** 当前激活环境的完整配置（env.json 与 env.secret.json 合并后） */
const env = deepMerge(_cfg.envs[_cfg.activeEnv], (_secret.envs || {})[_cfg.activeEnv]);
const fixtures = _cfg.fixtures || {};

// ---------- DB ----------
function openDb(profile = env) {
  if (!profile.db || !profile.db.password) {
    throw new Error('DB 凭据未配置：请在 env.secret.json 的 envs.<activeEnv>.db.password 填入');
  }
  const mysql = require('mysql2/promise');
  // bigNumberStrings：tenant_id 等超过 JS 安全整数的 ID 一律按字符串处理
  return mysql.createConnection({
    host: profile.db.host, port: profile.db.port, user: profile.db.user,
    password: profile.db.password, database: profile.db.database,
    supportBigNumbers: true, bigNumberStrings: true, charset: 'utf8mb4'
  });
}

// ---------- RabbitMQ ----------
function connectAmqp(profile = env) {
  const amqp = require('amqplib');
  const url = `amqp://${encodeURIComponent(profile.rabbitmq.user)}:${encodeURIComponent(profile.rabbitmq.password)}@${profile.rabbitmq.host}:${profile.rabbitmq.port}`;
  return amqp.connect(url);
}

/** RabbitMQ Management HTTP API（只读） */
function mgmtGet(p, timeoutMs = 5000, profile = env) {
  const http = require('http');
  return new Promise((resolve, reject) => {
    const u = new URL(profile.rabbitmq.managementUrl + p);
    const req = http.get({
      hostname: u.hostname, port: u.port, path: u.pathname + u.search,
      auth: `${profile.rabbitmq.user}:${profile.rabbitmq.password}`
    }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(new Error(`mgmt ${p} 非JSON: ${d.slice(0, 120)}`)); }
      });
    });
    req.setTimeout(timeoutMs, () => { req.destroy(); reject(new Error(`mgmt ${p} 超时`)); });
    req.on('error', reject);
  });
}

/** 查询指定队列当前状态（depth/unacked/consumers） */
async function queueState(queue) {
  const q = await mgmtGet(`/api/queues/%2F/${encodeURIComponent(queue)}`);
  return { messages: q.messages || 0, ready: q.messages_ready || 0, unacked: q.messages_unacknowledged || 0, consumers: q.consumers || 0 };
}

// ---------- MQTT ----------
function connectMqtt(profile = env) {
  const mqtt = require('mqtt');
  return mqtt.connectAsync(`mqtt://${profile.mqtt.host}:${profile.mqtt.port}`, {
    username: profile.mqtt.username, password: profile.mqtt.password,
    connectTimeout: 8000, reconnectPeriod: 0   // 探针场景不自动重连，失败要快速暴露
  });
}

// ---------- 工具 ----------
/** 19 位数字消息ID（与后端 16~19 位习惯一致），对账的锚点 */
function newMessageId() {
  return Date.now() + String(Math.floor(Math.random() * 1e6)).padStart(6, '0');
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

module.exports = {
  env, fixtures, deepMerge,
  openDb, connectAmqp, mgmtGet, queueState, connectMqtt,
  newMessageId, sleep
};
