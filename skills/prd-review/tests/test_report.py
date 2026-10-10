"""Verify offline flow rendering and that the report preserves overview order."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'report.py'
spec = importlib.util.spec_from_file_location('prd_report', SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    def test_offline_flow_is_svg_with_same_nodes_and_text_fallback(self):
        nodes = ['员工提交', '系统校验', '负责人审核', '财务付款', '员工查看结果']
        markup = report.render_flow('text', [' → '.join(nodes)])
        svg = markup[markup.index('<svg'):markup.index('</svg>') + 6]
        tree = ET.fromstring(svg)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        self.assertEqual(len(tree.findall('s:rect', ns)), len(nodes))
        texts = [''.join(node.itertext()) for node in tree.findall('s:text', ns)]
        self.assertEqual(texts, nodes)
        self.assertIn(' → '.join(nodes), markup)
        self.assertIn('role="img"', markup)
        self.assertNotIn('src=', markup)

    def test_code_and_unsupported_diagrams_stay_verbatim(self):
        for language, lines in [('python', ['a → b → c']),
                                ('text', ['a → b']),
                                ('text', ['a → b → c', 'branch']),
                                ('mermaid', ['flowchart LR', 'A --> B']),
                                ('text', ['a → → b → c'])]:
            self.assertIsNone(report.render_flow(language, lines))
            source = '```' + language + '\n' + '\n'.join(lines) + '\n```'
            body, _ = report.render_markdown(source)
            self.assertIn('<pre', body)
            self.assertNotIn('<svg', body)

    def test_external_labels_are_escaped_in_svg_and_attributes(self):
        markup = report.render_flow('text', ['<script>alert(1)</script> → "校验" → 完成 & 通知'])
        self.assertNotIn('<script>', markup)
        self.assertIn('&lt;script&gt;', markup)
        self.assertIn('&quot;校验&quot;', markup)
        svg = markup[markup.index('<svg'):markup.index('</svg>') + 6]
        ET.fromstring(svg)

    def test_long_node_wraps_without_losing_content(self):
        label = '这是用于验证文字换行后核心业务含义仍然完整的流程节点'
        markup = report.render_flow('plaintext', [label + ' → 校验 → 完成'])
        svg = ET.fromstring(markup[markup.index('<svg'):markup.index('</svg>') + 6])
        text = svg.find('{http://www.w3.org/2000/svg}text')
        self.assertEqual(''.join(text.itertext()), label)

    def test_generated_report_starts_with_overview_before_scope_and_issues(self):
        source_text = '''# 员工报销 PRD 问题审查报告

## 需求概览

员工提交报销申请，负责人审核后由财务付款，员工查看结果。

```text
员工提交 → 系统校验 → 负责人审核 → 财务付款 → 员工查看结果
```

## 1. 分析范围

只审查报销 PRD。

## 3. 合理性问题

P2：PRD 未说明审核不通过时如何处理。
'''
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / '报销.md'
            target = source.with_suffix('.html')
            source.write_text(source_text, encoding='utf-8')
            report.generate(source, target)
            page = target.read_text(encoding='utf-8')
        body = page.split('<main>', 1)[1].split('</main>', 1)[0]
        self.assertLess(body.index('需求概览'), body.index('1. 分析范围'))
        self.assertLess(body.index('1. 分析范围'), body.index('3. 合理性问题'))
        self.assertIn('<svg', body)
        self.assertIn('P2：PRD 未说明', body)
        self.assertNotIn('cdn', page.lower())
        self.assertNotIn('<script src=', page)


if __name__ == '__main__':
    unittest.main()
