#!/usr/bin/env python3
"""build_casebook.py — 离线单文件 HTML / Markdown 摘要渲染与原子落盘。

职责（设计蓝图 5.6 / 7 / 8）：
- load_template / load_css：资源以脚本自身位置定位技能根，cwd 无关；缺失 → BuildError
- render_html / render_markdown：七个区块全部由确定性数据渲染，
  所有动态值经 html.escape（含引号转义），缺失指标整个槽位不渲染
- emit_atomic：内存组装 → 残留扫描硬门 → 临时文件 → 原子改名落盘

确定性约束：渲染不写墙钟时间（时间只来自源数据），同一输入重复构建逐字节一致。
"""

import html
import os
from pathlib import Path

try:
    from . import runmodel as rm
    from . import redact as rd
except ImportError:
    import runmodel as rm
    import redact as rd

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "assets" / "casebook-template.html"
CSS_PATH = ROOT / "assets" / "casebook.css"


class BuildError(Exception):
    """构建错误（模板 / CSS 缺失、资源解析失败、产物含脚本）。"""


def esc(value):
    """强制转义：所有动态值统一入口（含引号转义，属性位置同样安全）。"""
    return html.escape("" if value is None else str(value), quote=True)


def load_template():
    if not TEMPLATE_PATH.is_file():
        raise BuildError("模板缺失: {}".format(TEMPLATE_PATH))
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    if "<script" in text.lower():
        raise BuildError("模板包含脚本标签，违反离线约束")
    return text


def load_css():
    if not CSS_PATH.is_file():
        raise BuildError("样式缺失: {}".format(CSS_PATH))
    text = CSS_PATH.read_text(encoding="utf-8")
    low = text.lower()
    if "<script" in low or "url(" in low or "@import" in low:
        raise BuildError("样式包含外链或脚本形态，违反离线约束")
    return text


def _anchor(ref):
    return rm.make_anchor_id(ref)


# 锚点登记表：保证页面内 id 唯一、链接只指向已放置的锚点（渲染开始时重置）
_ID_COUNT = {}
_ID_FIRST = {}
_ELEM_SEEN = {}


def _reset_ids():
    _ID_COUNT.clear()
    _ID_FIRST.clear()
    _ELEM_SEEN.clear()


def _place_id(ref):
    """为 source_ref 放置一个页面锚点 id；重复引用得到确定性后缀。"""
    base = rm.make_anchor_id(ref)
    _ID_COUNT[base] = _ID_COUNT.get(base, 0) + 1
    actual = base if _ID_COUNT[base] == 1 else "{}-{}".format(base, _ID_COUNT[base])
    if _ID_COUNT[base] == 1:
        _ID_FIRST[base] = actual
    return actual


def _lookup_id(ref):
    """读取已放置的锚点 id（不重复登记）。"""
    base = rm.make_anchor_id(ref)
    return _ID_FIRST.get(base, base)


def _elem_id(ref):
    """为承载元素分配页面锚点 id：同一 ref 的首个元素用登记位 id，
    后续元素获得确定性后缀，保证全页 id 唯一；链接一律指向首个。"""
    base = rm.make_anchor_id(ref)
    n = _ELEM_SEEN.get(base, 0) + 1
    _ELEM_SEEN[base] = n
    if n == 1 and base in _ID_FIRST:
        return _ID_FIRST[base]
    return "{}-e{}".format(base, n)


def _preplace_anchors(run):
    """渲染前统一登记会承载锚点的元素（交付物、主张、工具调用、步骤），顺序确定。"""
    for item in run.get("deliverables", []):
        _place_id(item.get("source_ref", ""))
    for item in run.get("claims", []):
        _place_id(item.get("source_ref", ""))
    for item in run.get("tool_calls", []):
        _place_id(item.get("source_ref", ""))
    for item in run.get("steps", []):
        _place_id(item.get("source_ref", ""))


def _source_link(ref, label="来源"):
    """来源链接：目标锚点未放置时输出纯文本（不产生断链）。"""
    base = rm.make_anchor_id(ref)
    if base in _ID_FIRST:
        return '<a href="#{}" class="mono">{}:{}</a>'.format(
            esc(_ID_FIRST[base]), esc(label), esc(_ID_FIRST[base]))
    return '<span class="mono">ref:{}</span>'.format(esc(base))


def _badge(kind, text):
    return '<span class="badge {}">{}</span>'.format(esc(kind), esc(text))


def _evidence_badge(level):
    cls = {
        "external-verification": "b-verified",
        "failed": "b-failed",
        "tool-evidence": "b-tool",
        "unverified": "b-unverified",
        "self-report": "b-self",
    }.get(level, "b-unverified")
    return _badge(cls, rm.EVIDENCE_LABELS.get(level, level))


def _verification_badge(verification):
    cls = {"verified": "b-verified", "failed": "b-failed"}.get(verification, "b-unverified")
    return _badge(cls, rm.VERIFICATION_LABELS.get(verification, verification))


def _fmt_ts(ts):
    return esc(ts) if ts else ""


# ── 区块渲染 ────────────────────────────────────────────────────────

def _section_header(run):
    task = run.get("task", {})
    mode = run.get("source", {}).get("mode", "full")
    title = _page_title(run)
    goal = task.get("goal")
    chips = []
    if goal:
        chips.append('<p class="goal">任务目标：{}</p>'.format(esc(goal)))
    badges = ['<span class="badge b-mode">{}</span>'.format(
        esc("文本模式" if mode == "text" else "完整模式"))]
    metrics = run.get("metrics", {})
    for key, label, fmt in (("duration_ms", "总耗时", "{} ms"),
                            ("tokens", "Token 用量", "{}"),
                            ("cost", "成本", "{}")):
        if key in metrics:  # 缺失指标不渲染、不估算
            badges.append(_badge("b-tool", label + "：" + fmt.format(metrics[key])))
    if run.get("narrative_check", {}).get("passed") is False and run.get("narrative"):
        badges.append(_badge("b-unverified", "叙事未通过核验，已按事实模式渲染"))
    return ("<section class=\"card\" id=\"casebook-header\"><h1>{}</h1>{}</section>"
            .format(esc(title), "".join(chips)) +
            '<div class="badges">{}</div>'.format("".join(badges)))


def _page_title(run):
    narrative = run.get("narrative")
    if narrative and run.get("narrative_check", {}).get("passed"):
        return narrative.get("title") or run.get("task", {}).get("goal") or "Agent 运行案例册"
    return run.get("task", {}).get("goal") or "Agent 运行案例册"


def _section_narrative(run):
    parts = ['<h2 id="narrative">叙事概览</h2>']
    narrative = run.get("narrative")
    check = run.get("narrative_check", {})
    if narrative and check.get("passed"):
        parts.append('<section class="card"><p>{}</p></section>'.format(esc(narrative.get("summary", ""))))
        notes = narrative.get("reader_notes") or []
        if notes:
            parts.append('<ul>' + "".join('<li>{}</li>'.format(esc(n)) for n in notes) + '</ul>')
    else:
        if narrative:
            parts.append('<div class="banner">叙事未通过核验，已按事实模式渲染。'
                         '事实与指标不受影响，以下各区块均直接来自脱敏后的源数据。</div>')
        else:
            parts.append('<p class="muted">本页未包含叙事区块（事实模式：无 narrative.json 输入）。</p>')
    return "".join(parts)


def _section_deliverables(run):
    parts = ['<h2 id="deliverables">交付物</h2>']
    items = run.get("deliverables", [])
    if not items:
        parts.append('<p class="muted">（无交付物记录；无来源依据的文件不生成卡片）</p>')
    for item in items:
        ev = item.get("evidence", {})
        parts.append(
            '<div class="card" id="{}"><p><strong class="mono">{}</strong> {} {}</p>'
            '<p class="muted">类型：{} {}</p></div>'.format(
                esc(_elem_id(item["source_ref"])), esc(item.get("path", "")),
                _badge("b-tool", esc(item.get("kind", "other"))),
                _evidence_badge(ev.get("level", "unverified")),
                esc(item.get("kind", "other")),
                _verification_badge(ev.get("verification", "unverified"))))
    return "".join(parts)


def _section_keypath(run):
    parts = ['<h2 id="keypath">关键路径</h2>']
    narrative = run.get("narrative")
    if narrative and run.get("narrative_check", {}).get("passed"):
        parts.append('<ol>')
        for node in narrative.get("key_nodes", []):
            parts.append('<li><strong>{}</strong><br>{}<br>{}</li>'.format(
                esc(node.get("heading", "")), esc(node.get("blurb", "")),
                _source_link(node.get("ref", ""))))
        parts.append('</ol>')
    else:
        fact_steps = [s for s in run.get("steps", []) if s.get("tool_call_ids")][:7] \
            or run.get("steps", [])[:7]
        if not fact_steps:
            parts.append('<p class="muted">（无步骤记录）</p>')
        parts.append('<ol>')
        for step in fact_steps:
            parts.append('<li>{}<br>{} {}</li>'.format(
                esc(step.get("title", "")),
                _badge("b-tool", "工具调用 ×{}".format(len(step.get("tool_call_ids", [])))),
                _source_link(step.get("source_ref", ""))))
        parts.append('</ol>')
    return "".join(parts)


def _section_evidence(run):
    parts = ['<h2 id="evidence">证据面板</h2>']
    claims = run.get("claims", [])
    if not claims:
        parts.append('<p class="muted">（无主张记录）</p>')
        return "".join(parts)
    parts.append('<table><tr><th>主张（原文）</th><th>证据等级</th><th>验证状态</th><th>来源</th></tr>')
    for item in claims:
        parts.append('<tr><td><pre>{}</pre></td><td>{}{}</td><td>{}</td><td>{}</td></tr>'.format(
            esc(item.get("text", "")),
            '<span id="{}"></span>'.format(esc(_elem_id(item.get("source_ref", "")))),
            _evidence_badge(item.get("evidence_level", "unverified")),
            _verification_badge(item.get("verification", "unverified")),
            _source_link(item.get("source_ref", ""))))
    parts.append('</table>')
    return "".join(parts)


def _section_timeline(run):
    parts = ['<h2 id="timeline">完整时间线</h2>']
    tc_by_id = {item["id"]: item for item in run.get("tool_calls", [])}
    steps = run.get("steps", [])
    if not steps:
        parts.append('<p class="muted">（无步骤记录）</p>')
    for step in steps:
        body = step.get("text") or step.get("title", "")
        inner = ['<pre>{}</pre>'.format(esc(body))]
        if step.get("ts"):
            inner.append('<p class="muted">时间：{}</p>'.format(_fmt_ts(step.get("ts"))))
        for tid in step.get("tool_call_ids", []):
            call = tc_by_id.get(tid, {})
            bits = ['<li><span id="{}"></span><span class="mono">{}</span>'.format(
                esc(_elem_id(call.get("source_ref", ""))), esc(call.get("name", "")))]
            if call.get("status"):
                bits.append(' 状态：<span class="mono">{}</span>'.format(esc(call.get("status"))))
            if call.get("duration_ms") is not None:
                bits.append(' 耗时：{} ms'.format(call.get("duration_ms")))
            bits.append(' {}</li>'.format(_source_link(call.get("source_ref", ""))))
            inner.append('<ul>' + "".join(bits) + '</ul>')
        unknown = step.get("unknown_fields", [])
        if unknown:
            shown = unknown[:20]
            rest = len(unknown) - len(shown)
            inner.append('<details><summary>未识别字段（未解读）×{}</summary><ul>'.format(len(unknown)))
            for u in shown:
                line = esc(u.get("name", ""))
                if "value" in u:
                    line += " = " + esc(u.get("value"))
                inner.append('<li>{} {}</li>'.format(line, _source_link(u.get("source_ref", ""))))
            if rest > 0:
                inner.append('<li class="muted">……其余 {} 条仅计入警告，不重复展示</li>'.format(rest))
            inner.append('</ul></details>')
        parts.append('<details id="{}"><summary>{} {}</summary>{}</details>'.format(
            esc(_elem_id(step.get("source_ref", ""))),
            esc(step.get("id", "")), esc(step.get("title", "")), "".join(inner)))
    return "".join(parts)


def _section_repro(run):
    parts = ['<h2 id="repro">复现与未知事项</h2>']
    src = run.get("source", {})
    parts.append('<h3>输入来源</h3><ul>')
    for inp in src.get("inputs", []):
        parts.append('<li><span class="mono">{}</span>（记录数 {}）</li>'.format(
            esc(inp.get("name", "")), esc(inp.get("record_count", 0))))
    parts.append('</ul>')
    degr = src.get("degradations", [])
    if degr:
        parts.append('<h3>降级清单</h3><ul>')
        for d in degr:
            parts.append('<li><span class="mono">{}</span> {} {}</li>'.format(
                esc(d.get("code", "")), esc(d.get("reason", "")), _source_link(d.get("source_ref", ""))))
        parts.append('</ul>')
    else:
        parts.append('<p class="muted">无降级。</p>')
    excl = src.get("exclusions", [])
    if excl:
        parts.append('<h3>结构排除（内容不进入本页与 run.json）</h3><ul>')
        for e in excl:
            label = {"SYSTEM_RECORD": "system/developer 记录",
                     "HIDDEN_REASONING": "隐藏推理字段"}.get(e.get("code"), e.get("code", ""))
            parts.append('<li>{} ×{}</li>'.format(esc(label), esc(e.get("count", 0))))
        parts.append('</ul>')
    autos = run.get("automation", [])
    if autos:
        parts.append('<h3>Automation / Schedule（只标已投递）</h3><ul>')
        for a in autos:
            parts.append('<li>{} <span class="mono">{}</span> {}'.format(
                _badge("b-delivered", "已投递"), esc(a.get("kind", "")),
                _fmt_ts(a.get("delivered_at")) or '<span class="muted">（无时间）</span>'))
            parts.append(' {}</li>'.format(_source_link(a.get("source_ref", ""))))
        parts.append('</ul>')
    warn_limit = 50
    warns = run.get("warnings", [])
    if warns:
        parts.append('<h3>警告（{} 条）</h3><ul>'.format(len(warns)))
        for w in warns[:warn_limit]:
            parts.append('<li><span class="mono">{}</span> {} {}</li>'.format(
                esc(w.get("code", "")), esc(w.get("detail", "")), _source_link(w.get("source_ref", ""))))
        if len(warns) > warn_limit:
            parts.append('<li class="muted">……其余 {} 条见 run.json 的 warnings 字段</li>'.format(len(warns) - warn_limit))
        parts.append('</ul>')
    return "".join(parts)


def _section_footer(run):
    src = run.get("source", {})
    applied = run.get("redaction", {}).get("applied", [])
    applied_text = "、".join("{}×{}".format(a.get("rule"), a.get("count")) for a in applied) or "无命中"
    excl = src.get("exclusions", [])
    excl_text = "、".join(
        "{}×{}".format({"SYSTEM_RECORD": "system/developer 记录",
                        "HIDDEN_REASONING": "隐藏推理字段"}.get(e.get("code"), e.get("code", "")),
                       e.get("count", 0))
        for e in excl) or "无"
    return ('<footer>生成器：{} v{}｜来源类型：{}｜契约版本：{}｜结构排除：{}｜脱敏命中：{}<br>'
            '本页为本地生成，未自动发布。无脚本、无外部请求；所有主张可经来源锚点回溯。</footer>'
            .format(esc(rm.GENERATOR_NAME), esc(rm.GENERATOR_VERSION),
                    esc(src.get("kind", "")), esc(src.get("contract_version", "unknown")),
                    esc(excl_text), esc(applied_text)))


def render_html(run):
    """渲染单文件 HTML。run 必须是已脱敏的 run 模型。"""
    _reset_ids()
    _preplace_anchors(run)
    template = load_template()
    css = load_css()
    slots = {
        "TITLE": esc(_page_title(run)),
        "CSS": css,
        "HEADER": _section_header(run),
        "NARRATIVE": _section_narrative(run),
        "DELIVERABLES": _section_deliverables(run),
        "KEYPATH": _section_keypath(run),
        "EVIDENCE": _section_evidence(run),
        "TIMELINE": _section_timeline(run),
        "REPRO": _section_repro(run),
        "FOOTER": _section_footer(run),
    }
    out = template
    for key, value in slots.items():
        out = out.replace("{{" + key + "}}", value)
    if "{{" in out:
        raise BuildError("模板存在未填充的槽位")
    low = out.lower()
    if "<script" in low:
        raise BuildError("产物包含脚本标签，违反离线约束")
    return out


def render_markdown(run):
    """Markdown 摘要（标题层级不超过 3 级）。"""
    lines = ["# Agent 运行案例册：{}".format(_page_title(run))]
    src = run.get("source", {})
    lines.append("")
    mode_label = "文本模式" if src.get("mode") == "text" else "完整模式"
    lines.append("- 模式：{}".format(mode_label))
    lines.append("- 来源类型：{}（契约版本 {}）".format(src.get("kind", ""), src.get("contract_version", "unknown")))
    goal = run.get("task", {}).get("goal")
    if goal:
        lines.append("- 任务目标：{}".format(goal))
    for key, label, fmt in (("duration_ms", "总耗时", "{} ms"), ("tokens", "Token 用量", "{}"), ("cost", "成本", "{}")):
        if key in run.get("metrics", {}):
            lines.append("- {}：{}".format(label, fmt.format(run["metrics"][key])))
    narrative = run.get("narrative")
    if narrative and run.get("narrative_check", {}).get("passed"):
        lines += ["", "## 概览", "", narrative.get("summary", "")]
        for note in narrative.get("reader_notes", []):
            lines.append("- {}".format(note))
    else:
        if narrative:
            lines += ["", "## 概览", "", "叙事未通过核验，已按事实模式渲染。"]
        else:
            lines += ["", "## 概览", "", "本摘要未包含叙事（事实模式）。"]
    lines += ["", "## 交付物", ""]
    if run.get("deliverables"):
        for d in run["deliverables"]:
            lines.append("- `{}`（{}；证据：{}）".format(
                d.get("path", ""), d.get("kind", "other"),
                rm.EVIDENCE_LABELS.get(d.get("evidence", {}).get("level", "unverified"), "未验证")))
    else:
        lines.append("（无交付物记录）")
    lines += ["", "## 证据面板", "", "| 主张（原文） | 证据等级 | 验证状态 | 来源 |", "|---|---|---|---|"]
    if run.get("claims"):
        for c in run["claims"]:
            lines.append("| {} | {} | {} | `{}` |".format(
                c.get("text", "").replace("|", "\\|"),
                rm.EVIDENCE_LABELS.get(c.get("evidence_level", ""), "未验证"),
                rm.VERIFICATION_LABELS.get(c.get("verification", ""), "未验证"),
                c.get("source_ref", "")))
    else:
        lines.append("| （无主张记录） | | | |")
    lines += ["", "## 复现与未知事项", ""]
    for inp in src.get("inputs", []):
        lines.append("- 输入：`{}`（记录数 {}）".format(inp.get("name", ""), inp.get("record_count", 0)))
    for d in src.get("degradations", []):
        lines.append("- 降级：`{}` {}（{}）".format(d.get("code", ""), d.get("reason", ""), d.get("source_ref", "")))
    for a in run.get("automation", []):
        lines.append("- Automation（{}）：已投递{}".format(
            a.get("kind", ""), "，时间 " + a["delivered_at"] if a.get("delivered_at") else ""))
    applied = run.get("redaction", {}).get("applied", [])
    lines += ["", "## 脚注", "",
              "生成器 {} v{}；脱敏命中：{}；本地生成，未自动发布。".format(
                  rm.GENERATOR_NAME, rm.GENERATOR_VERSION,
                  "、".join("{}×{}".format(a.get("rule"), a.get("count")) for a in applied) or "无命中")]
    return "\n".join(lines) + "\n"


def emit_atomic(outdir, files):
    """内存组装 → 残留扫描 → 临时文件 → 原子改名。任一命中则整体失败、不落盘。"""
    outdir = Path(outdir)
    payloads = {}
    for name, content in files.items():
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        hits = rd.residual_scan_bytes(data)
        if hits:
            raise rd.ResidualLeakError(hits)
        payloads[name] = data
    outdir.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        tmp = outdir / ("." + name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, outdir / name)
    return [outdir / name for name in payloads]
