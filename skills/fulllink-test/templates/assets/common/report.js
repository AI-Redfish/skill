/**
 * 断言收集与报告渲染（模板，随 init 落位到 <workspace>/assets/common/report.js）
 *
 * 用法：
 *   const { check, summary, writeReport } = require('./report.js');
 *   check('队列有消费者', s.consumers > 0, `consumers=${s.consumers}`);  // 收集
 *   writeReport('/path/runs/<主题>/report-assert.md');                  // 落盘
 *   process.exitCode = summary().failed > 0 ? 1 : 0;                     // 非0=FAIL
 * 证据要求见 skill 的 contracts/report-contract.md：L0 证据不算 PASS。
 */
const fs = require('fs');
const path = require('path');

const results = [];

/** 收集一条断言；ok=false 时 evidence 必须可复查（messageId/SQL 前后值/行数） */
function check(name, ok, evidence = '') {
  results.push({ name, ok: !!ok, evidence: String(evidence) });
  const mark = ok ? 'PASS' : 'FAIL';
  console.log(`[${mark}] ${name}${evidence ? ` — ${evidence}` : ''}`);
  return !!ok;
}

function summary() {
  const failed = results.filter(r => !r.ok).length;
  return { total: results.length, passed: results.length - failed, failed };
}

/** 渲染成 markdown 断言表（嵌入 report.md 的"结果矩阵"节） */
function render() {
  const s = summary();
  const rows = results.map((r, i) =>
    `| ${i + 1} | ${r.name} | ${r.ok ? 'PASS' : 'FAIL'} | ${r.evidence.replace(/\|/g, '\\|')} |`);
  return [
    `共 ${s.total} 项：PASS ${s.passed} / FAIL ${s.failed}`, '',
    '| # | 测试点 | 结果 | 证据 |', '|---|---|---|---|', ...rows
  ].join('\n');
}

function writeReport(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, render() + '\n', 'utf8');
  return filePath;
}

module.exports = { check, summary, render, writeReport };
