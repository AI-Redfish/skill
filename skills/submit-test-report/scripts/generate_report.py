#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
generate_report.py — 基于《需求提测确认接收单》模板生成提测单。

原理：复制模板 docx，仅重写 word/document.xml 中的关键文本，
其余全部部件（样式/编号/主题/字体表等）原样复制，保证版式与模板完全一致。
只做"文本替换 + 行/段克隆"，不引入任何新格式。

用法：
  python generate_report.py --fields fields.json [--out 输出.docx] [--template 模板.docx]
  python generate_report.py --dump 某文件.docx        # 打印 docx 内全部文本（用于生成后自查）

省略 --out 时，默认输出到当前用户桌面，文件名：需求提测确认接收单-{iteration}.docx
（桌面路径优先读注册表 User Shell Folders\Desktop，兼容 OneDrive 重定向）。

docs 中的需求/设计/技术文档必须为本地文件路径，脚本自动复制到
「需求提测确认接收单-{iteration}-附件」文件夹（与 docx 同目录），
docx 内只写“见附件：文件名”，不放链接；无文档填“无：<原因>”。

fields.json 结构见同目录 fields.example.json。
仅依赖 Python 3.8+ 标准库。
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % W_NS
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

NSMAP = {
    "wpc": "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "o": "urn:schemas-microsoft-com:office:office",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "v": "urn:schemas-microsoft-com:vml",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "w": W_NS,
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w10": "urn:schemas-microsoft-com:office:word",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wpi": "http://schemas.microsoft.com/office/word/2010/wordprocessingInk",
    "wne": "http://schemas.microsoft.com/office/word/2006/wordml",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpsCustomData": "http://www.wps.cn/officeDocument/2013/wpsCustomData",
}
for _p, _u in NSMAP.items():
    ET.register_namespace(_p, _u)

DEFAULT_RPR_XML = (
    '<w:rPr xmlns:w="%s"><w:rFonts w:hint="eastAsia" w:eastAsia="宋体"/></w:rPr>' % W_NS
)

TEST_STAGE_OPTIONS = [
    "冒烟测试",
    "功能测试",
    "回归测试",
    "联调/集成测试",
    "线上验收",
    "IPD 测试",
    "其他：________",
]
SELF_TEST_OPTIONS = {"通过": "通过（主流程 + 本版本变更点均已自测）", "有条件通过": "有条件通过（见已知问题）", "未完成": "未完成（不得提测）"}


# ---------------------------------------------------------------- 基础工具
def normalize(s):
    """比较用：去首尾空白并压缩连续空白。"""
    return re.sub(r"\s+", " ", (s or "")).strip()


def para_text(p):
    return "".join(t.text or "" for t in p.iter(W + "t"))


def cell_text(tc):
    return " | ".join(para_text(p) for p in tc.findall(W + "p"))


def _runs_with_parents(p):
    out = []
    for parent in p.iter():
        for r in parent.findall(W + "r"):
            out.append((parent, r))
    return out


def set_para_text(p, text):
    """将段落文本替换为 text：保留原格式（取第一个含 w:t 的 run 的 rPr），
    删除其余 run 及拼写标记；无可用 run 时按模板数据行惯例新建宋体 run。"""
    text = (text or "").replace("\r\n", " ").replace("\n", " ")
    pairs = _runs_with_parents(p)
    donor_rpr = None
    for _parent, r in pairs:
        rpr = r.find(W + "rPr")
        if rpr is not None and r.find(W + "t") is not None:
            donor_rpr = copy.deepcopy(rpr)
            break
    for parent, r in pairs:
        parent.remove(r)
    for el in list(p):
        if el.tag in (W + "proofErr", W + "hyperlink"):
            p.remove(el)
    run = ET.SubElement(p, W + "r")
    if donor_rpr is not None:
        run.append(donor_rpr)
    else:
        run.append(ET.fromstring(DEFAULT_RPR_XML))
    t = ET.SubElement(run, W + "t")
    if text != text.strip():
        t.set(XML_SPACE, "preserve")
    t.text = text


def set_cell_text(tc, value):
    """设置单元格文本。value 可为 str 或 list[str]（每项一个段落，段格式克隆自首段）。"""
    lines = list(value) if isinstance(value, (list, tuple)) else [value]
    if not lines:
        lines = [""]
    lines = [str(x) for x in lines]
    ps = tc.findall(W + "p")
    first = ps[0]
    for extra in ps[1:]:
        tc.remove(extra)
    set_para_text(first, lines[0])
    prev = first
    for line in lines[1:]:
        newp = copy.deepcopy(first)
        set_para_text(newp, line)
        tc.insert(list(tc).index(prev) + 1, newp)
        prev = newp


def cells(tr):
    return tr.findall(W + "tc")


def find_table(body, signature):
    """按"首行前两格文本"签名定位表格。signature=(cell0, cell1或None)。"""
    for tbl in body.iter(W + "tbl"):
        rows = tbl.findall(W + "tr")
        if not rows:
            continue
        tcs = cells(rows[0])
        texts = [normalize(cell_text(tc)) for tc in tcs]
        if not texts:
            continue
        c0, c1 = signature
        if texts[0] == c0 and (c1 is None or (len(texts) > 1 and texts[1] == c1)):
            return tbl
    return None


def find_row_by_label(tbl, label):
    target = normalize(label)
    for tr in tbl.findall(W + "tr"):
        tcs = cells(tr)
        if tcs and normalize(cell_text(tcs[0])) == target:
            return tr
    return None


def set_value_row(tbl, label, value):
    """设置"标签 | 值"两格表行中第二格内容。返回是否成功。"""
    tr = find_row_by_label(tbl, label)
    if tr is None:
        return False
    tcs = cells(tr)
    if len(tcs) < 2:
        return False
    set_cell_text(tcs[1], value)
    return True


def fill_data_table(tbl, rows_data, n_cols):
    """用 rows_data 重写数据表（第 0 行为表头）：以模板第 1 行为格式原型克隆。"""
    rows = tbl.findall(W + "tr")
    header, data_rows = rows[0], rows[1:]
    if not data_rows:
        return
    proto = copy.deepcopy(data_rows[0])
    for r in data_rows:
        tbl.remove(r)
    anchor = header
    for item in rows_data:
        newr = copy.deepcopy(proto)
        tcs = cells(newr)
        for i in range(n_cols):
            if i < len(tcs):
                set_cell_text(tcs[i], item[i] if i < len(item) else "")
        tbl.insert(list(tbl).index(anchor) + 1, newr)
        anchor = newr
    if not rows_data:  # 保底：至少留一个空行
        empty = copy.deepcopy(proto)
        for tc in cells(empty):
            set_cell_text(tc, "")
        tbl.insert(list(tbl).index(header) + 1, empty)


# ---------------------------------------------------------------- 主流程
DOC_ROW_LABELS = [
    ("requirement", "需求 / 原型文档"),
    ("design", "系统分析 / 设计文档"),
    ("tech", "技术方案 / 接口文档"),
]


def prepare_attachments(fields, out):
    """把 docs 中的本地文档复制为附件文件夹，并生成 docx 单元格展示文本。
    重写 fields["_docs_cells"]：{行标签: [段落文本...]}。返回附件文件夹路径。"""
    docs = fields.get("docs") or {}
    iteration = fields["iteration"].strip()
    parsed = {}
    for key, label in DOC_ROW_LABELS:
        raw = docs.get(key, "")
        items = [raw] if isinstance(raw, str) else list(raw)
        texts, paths = [], []
        for it in items:
            s = str(it).strip()
            if not s:
                continue
            if s.lower().startswith(("http://", "https://")):
                raise SystemExit(
                    "docs.%s 为链接。按提测规范需以附件方式提供：请改为本地文档路径；无文档填“无：<原因>”。" % key
                )
            if s.startswith("无"):
                texts.append(s)
                continue
            p = Path(s)
            if not p.exists():
                raise SystemExit("docs.%s 附件文件不存在：%s" % (key, s))
            paths.append(p)
        if not paths and not texts:
            raise SystemExit('docs.%s 不可留空：填本地文档路径，或填「无：<原因>」。' % key)
        parsed[label] = (texts, paths)

    folder = out.parent / ("需求提测确认接收单-%s-附件" % iteration)
    folder.mkdir(parents=True, exist_ok=True)
    cells, used = {}, set()
    for key, label in DOC_ROW_LABELS:
        texts, paths = parsed[label]
        if paths:
            names = []
            for p in paths:
                dst = folder / p.name
                i = 1
                while dst.name in used:
                    dst = folder / ("%d_%s%s" % (i, p.stem, p.suffix))
                    i += 1
                used.add(dst.name)
                shutil.copyfile(str(p), str(dst))
                names.append(dst.name)
            lines = ["见附件：" + "、".join(names), "（附件随提测单一并提供：同目录「%s」文件夹）" % folder.name]
        else:
            lines = texts
        cells[label] = lines
    fields["_docs_cells"] = cells
    return folder


def default_output_path(iteration):
    """默认输出位置：当前用户桌面 / 需求提测确认接收单-{iteration}.docx"""
    desktop = None
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "Desktop")
                desktop = os.path.expandvars(val)
        except Exception:
            desktop = None
        if not desktop:
            profile = os.environ.get("USERPROFILE")
            if profile:
                desktop = os.path.join(profile, "Desktop")
    else:
        home = os.path.expanduser("~")
        if home:
            desktop = os.path.join(home, "Desktop")
    if not desktop or not os.path.isdir(desktop):
        desktop = os.getcwd()
    return Path(desktop) / ("需求提测确认接收单-%s.docx" % iteration)


def build_document_xml(fields):
    root = ET.fromstring(fields["_document_xml_bytes"])
    body = root.find(W + "body")

    basic = fields.get("basic", {})
    roles = fields.get("roles", {})
    env = fields.get("env", {})
    docs = fields.get("docs", {})
    self_test = fields.get("self_test", {})
    applied = []

    # 一、基础信息
    t1 = find_table(body, ("需求号 / 迭代名称", None))
    if t1 is None:
        raise SystemExit("未找到【一、基础信息】表，模板可能已被改动")
    base_version = basic.get("baseline_version", "").strip()
    mapping1 = [
        ("需求号 / 迭代名称", fields.get("iteration", "")),
        ("提测版本号", basic.get("test_version", "")),
        ("基线版本号", (base_version + "（相对本次变更的上一可测版本）") if base_version else ""),
        ("提测时间", basic.get("submit_date", "")),
        ("期望测试开始时间", basic.get("expect_start", "")),
        ("期望测试结束时间", basic.get("expect_end", "—")),
    ]
    for label, value in mapping1:
        if not set_value_row(t1, label, value):
            raise SystemExit("基础信息表缺少行：%s" % label)
    applied.append("一、基础信息（%d 项）" % len(mapping1))

    # 二、角色信息
    t2 = find_table(body, ("开发负责人", None))
    if t2 is None:
        raise SystemExit("未找到【二、角色信息】表")
    mapping2 = [
        ("开发负责人", roles.get("dev_owner", "")),
        ("产品经理", roles.get("product_manager", "")),
        ("研发项目经理", roles.get("project_manager", "")),
        ("测试接收人 / 测试责任人", roles.get("test_owner", "")),
        ("参与人员", roles.get("participants", "")),
    ]
    for label, value in mapping2:
        if not set_value_row(t2, label, value):
            raise SystemExit("角色信息表缺少行：%s" % label)
    applied.append("二、角色信息（%d 项）" % len(mapping2))

    # 三、测试信息：测试阶段勾选 + 系统/端表
    stages = fields.get("test_stages", []) or []
    stage_set = {normalize(s) for s in stages}
    for p in body.iter(W + "p"):
        txt = para_text(p)
        if "冒烟测试" in txt and "功能测试" in txt:
            parts = []
            for opt in TEST_STAGE_OPTIONS:
                name = normalize(opt.replace("：________", ""))
                mark = "☑" if (name in stage_set or normalize(opt) in stage_set) else "☐"
                parts.append("%s %s" % (mark, opt))
            set_para_text(p, "    ".join(parts))
            applied.append("三、测试阶段勾选：%s" % ("、".join(stages) if stages else "无"))
            break
    t3 = find_table(body, ("涉及应用 / 端", None))
    if t3 is None:
        raise SystemExit("未找到【三、测试信息】表")
    for label, value in [
        ("涉及应用 / 端", env.get("apps", "")),
        ("涉及硬件（如有）", env.get("hardware", "—")),
        ("最低运行环境", env.get("min_runtime", "—")),
    ]:
        if not set_value_row(t3, label, value):
            raise SystemExit("测试信息表缺少行：%s" % label)
    applied.append("三、系统/端信息")

    # 四、本次变更说明：需求变更明细 + 底层/公共变更
    t4 = find_table(body, ("需求号", "类型"))
    if t4 is None:
        raise SystemExit("未找到【需求变更明细】表")
    change_rows = []
    for chg in fields.get("changes", []) or []:
        modules = chg.get("modules", "")
        if isinstance(modules, str):
            modules = [x for x in modules.split("\n") if x.strip()] or [modules]
        change_rows.append([
            chg.get("req_no", ""),
            chg.get("type", ""),
            chg.get("summary", ""),
            list(modules),
            chg.get("verification", ""),
        ])
    fill_data_table(t4, change_rows, 5)
    applied.append("四、需求变更明细（%d 条）" % len(change_rows))

    t5 = find_table(body, ("项目", "变更说明"))
    if t5 is not None:
        common_rows = []
        for c in fields.get("common_changes", []) or []:
            common_rows.append([
                c.get("item", ""),
                c.get("description", ""),
                c.get("impact", ""),
            ])
        if common_rows:
            fill_data_table(t5, common_rows, 3)
        applied.append("四、底层/公共变更（%d 条）" % len(common_rows))

    # 五、开发自测说明
    t6 = find_table(body, ("自测结论", None))
    if t6 is not None:
        tr = find_row_by_label(t6, "自测结论")
        tcs = cells(tr)
        selected = normalize(self_test.get("conclusion", "通过"))
        if len(tcs) >= 2:
            ps = tcs[1].findall(W + "p")
            if selected not in SELF_TEST_OPTIONS:
                raise SystemExit("self_test.conclusion 必须是：%s 之一，当前为：%s" % ("/".join(SELF_TEST_OPTIONS), selected))
            for i, p in enumerate(ps):
                base = list(SELF_TEST_OPTIONS.values())[i] if i < len(SELF_TEST_OPTIONS) else para_text(p)
                base_clean = re.sub(r"^\s*[√☑☐✓]\s*", "", base)
                mark = "√" if base_clean == SELF_TEST_OPTIONS[selected] else "☐"
                set_para_text(p, mark + " " + base_clean)
            applied.append("五、自测结论：%s" % self_test.get("conclusion", "通过"))
        tr2 = find_row_by_label(t6, "自测范围说明")
        if tr2 is not None and len(cells(tr2)) >= 2:
            set_cell_text(cells(tr2)[1], self_test.get("scope", ""))
            applied.append("五、自测范围说明")

    # 六、测试资料同步情况（附件方式，由 prepare_attachments 生成展示文本）
    t7 = find_table(body, ("需求 / 原型文档", None))
    if t7 is None:
        raise SystemExit("未找到【六、测试资料同步情况】表")
    docs_cells = fields.get("_docs_cells") or {}
    for label, fallback in [
        ("需求 / 原型文档", docs.get("requirement", "")),
        ("系统分析 / 设计文档", docs.get("design", "")),
        ("技术方案 / 接口文档", docs.get("tech", "")),
    ]:
        value = docs_cells.get(label, fallback)
        if not set_value_row(t7, label, value):
            raise SystemExit("测试资料表缺少行：%s" % label)
    applied.append("六、测试资料同步情况（附件方式 3 项）")

    # 七、测试确认 / 八、备注：测试责任人填写，保持模板原样
    xml_bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + xml_bytes, applied


def generate(fields, template, out):
    tpl_zip = zipfile.ZipFile(str(template), "r")
    try:
        fields["_document_xml_bytes"] = tpl_zip.read("word/document.xml")
        new_doc_xml, applied = build_document_xml(fields)
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
            for item in tpl_zip.infolist():
                if item.filename == "word/document.xml":
                    zf.writestr(item, new_doc_xml)
                else:
                    zf.writestr(item, tpl_zip.read(item.filename))
    finally:
        tpl_zip.close()
    return out, applied


def dump_docx(path):
    """打印 docx 正文全部文本（段落逐行、表格逐行逐格），用于生成后自查。"""
    with zipfile.ZipFile(str(path), "r") as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(W + "body")
    ti = 0
    for child in body:
        tag = child.tag.replace(W, "")
        if tag == "p":
            txt = para_text(child)
            if txt.strip():
                print("[P] " + txt)
        elif tag == "tbl":
            ti += 1
            print("===== TABLE %d =====" % ti)
            for ri, tr in enumerate(child.findall(W + "tr")):
                row = [cell_text(tc) for tc in cells(tr)]
                print("  R%d: %s" % (ri, row))


def main():
    ap = argparse.ArgumentParser(description="根据模板生成《需求提测确认接收单》")
    ap.add_argument("--fields", help="字段 JSON 文件（UTF-8）")
    ap.add_argument("--template", help="模板 docx 路径，默认 skill 自带 assets/需求提测确认接收单-模板.docx")
    ap.add_argument("--out", help="输出 docx 路径；省略时默认输出到桌面：需求提测确认接收单-{iteration}.docx")
    ap.add_argument("--dump", metavar="DOCX", help="打印指定 docx 的全部文本后退出")
    args = ap.parse_args()

    if args.dump:
        dump_docx(args.dump)
        return

    if not args.fields:
        ap.error("--fields 必填（或使用 --dump）")
    template = Path(args.template) if args.template else Path(__file__).resolve().parent.parent / "assets" / "需求提测确认接收单-模板.docx"
    if not template.exists():
        raise SystemExit("模板不存在：%s" % template)
    with open(args.fields, encoding="utf-8") as f:
        fields = json.load(f)
    if not fields.get("iteration", "").strip():
        raise SystemExit("fields.iteration（需求号/迭代名称）不能为空")

    if args.out:
        out = args.out
    else:
        out = default_output_path(fields["iteration"].strip())
        print("未指定 --out，默认输出到桌面：")

    att_folder = prepare_attachments(fields, Path(out))
    out, applied = generate(fields, template, out)
    print("附件文件夹：%s（%d 个文件）" % (att_folder, len(list(att_folder.iterdir()))))
    print("已生成：%s" % out)
    for a in applied:
        print("  - " + a)


if __name__ == "__main__":
    main()
