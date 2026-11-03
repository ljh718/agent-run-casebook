#!/usr/bin/env python3
"""validate_case.py — schema / 引用 / narrative 白名单校验。

职责（设计蓝图 5.4 / 6）：
- validate_schema: 必填键、类型、id 唯一性
- validate_references: source_ref 形态、tool_call_ids / verification_refs / key_nodes.ref 存在性
- validate_narrative: 白名单核验（只能改表述、选步骤、加读者解释）

失败行为：违规逐条产出 {code, path, detail}，非空即 exit 4；绝不静默修正事实字段。
"""

try:
    from . import runmodel as rm
except ImportError:
    import runmodel as rm

REQUIRED_TOP_KEYS = (
    "schema_version", "generator", "source", "task", "steps", "tool_calls",
    "deliverables", "claims", "automation", "metrics", "warnings",
)

_NARR_SIZE_LIMITS = {"title": 200, "summary": 500, "heading": 80, "blurb": 240}

# 事实候选提取：路径样式 token、已知扩展名文件 token、带单位数字 token
import re

_FACT_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/)[^\s\"'\uff0c\u3002\uff1b\uff09()]{2,}")
_FACT_FILE_RE = re.compile(
    r"\b[A-Za-z0-9_\-][A-Za-z0-9_\-.]*\."
    r"(?:py|json|jsonl|md|csv|txt|html|htm|zip|png|jpg|jpeg|svg|log|yaml|yml|toml)\b")
_FACT_NUM_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:ms|分钟|分|小时|秒|s\b|天|周|个月|年"
    r"|tokens?|美元|元|刀|倍|%|次|个|条|行|GB|MB|KB)", re.I)
# 汉字数字 + 单位（覆盖「两小时」「十次」「三百元」这类写法）
_FACT_CN_NUM_RE = re.compile(
    r"[一二三四五六七八九十百千万两]+(?:分钟|小时|天|周|个月|年|倍|元|美元|次|个|条|行)")


def _fact_candidates(text):
    out = set()
    for m in _FACT_FILE_RE.finditer(text):
        out.add(m.group(0))
    for m in _FACT_PATH_RE.finditer(text):
        tok = m.group(0).rstrip(".,;:)\u3001\uff0c\u3002\uff1b\uff09\uff5d]")
        if len(tok) >= 3:
            out.add(tok)
    for m in _FACT_NUM_RE.finditer(text):
        out.add(m.group(0))
    for m in _FACT_CN_NUM_RE.finditer(text):
        out.add(m.group(0))
    return sorted(out)


def _string_leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _string_leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _string_leaves(v)
    elif isinstance(obj, str):
        yield obj


def _fact_corpus(run):
    """事实集 = run 模型全部字符串值（不含 narrative 自身）。"""
    parts = []
    for key, value in run.items():
        if key == "narrative":
            continue
        parts.extend(_string_leaves(value))
    return "\n".join(parts)


def validate_schema(run):
    violations = []
    if not isinstance(run, dict):
        return [{"code": "E-SCHEMA", "path": "$", "detail": "run 模型必须是 JSON 对象"}]
    for key in REQUIRED_TOP_KEYS:
        if key not in run:
            violations.append({"code": "E-SCHEMA", "path": "$." + key,
                               "detail": "缺少必填顶层键 {}".format(key)})
    if violations:
        return violations
    src = run["source"]
    if not isinstance(src, dict):
        violations.append({"code": "E-SCHEMA", "path": "$.source", "detail": "source 必须是对象"})
    else:
        if src.get("kind") not in rm.SOURCE_KINDS:
            violations.append({"code": "E-SCHEMA", "path": "$.source.kind",
                               "detail": "kind 取值非法: {}".format(src.get("kind"))})
        if src.get("mode") not in rm.SOURCE_MODES:
            violations.append({"code": "E-SCHEMA", "path": "$.source.mode",
                               "detail": "mode 取值非法: {}".format(src.get("mode"))})
    if not isinstance(run["task"], dict):
        violations.append({"code": "E-SCHEMA", "path": "$.task", "detail": "task 必须是对象"})
    for key in ("steps", "tool_calls", "deliverables", "claims", "automation", "warnings"):
        if not isinstance(run[key], list):
            violations.append({"code": "E-SCHEMA", "path": "$." + key,
                               "detail": "{} 必须是数组".format(key)})
    if not isinstance(run["metrics"], dict):
        violations.append({"code": "E-SCHEMA", "path": "$.metrics", "detail": "metrics 必须是对象"})
    else:
        for mk in run["metrics"]:
            if mk not in rm.METRIC_KEYS:
                violations.append({"code": "E-SCHEMA", "path": "$.metrics." + mk,
                                   "detail": "metrics 键不在允许集内: {}".format(mk)})
    # id 唯一性 + 证据词表
    for key in ("steps", "tool_calls", "deliverables", "claims", "automation"):
        ids = [item.get("id") for item in run[key] if isinstance(item, dict)]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            violations.append({"code": "E-SCHEMA", "path": "$." + key,
                               "detail": "id 重复: {}".format(", ".join(map(str, dup)))})
    for item in run["claims"]:
        if item.get("claim_origin") not in rm.CLAIM_ORIGINS:
            violations.append({"code": "E-SCHEMA", "path": "$.claims[].claim_origin",
                               "detail": "claim_origin 必须为 marker 或 statement: {}".format(
                                   item.get("claim_origin"))})
        if item.get("evidence_level") not in rm.EVIDENCE_LEVELS:
            violations.append({"code": "E-SCHEMA", "path": "$.claims[].evidence_level",
                               "detail": "证据等级不在五级词表内: {}".format(item.get("evidence_level"))})
        if item.get("verification") not in ("verified", "failed", "unverified"):
            violations.append({"code": "E-SCHEMA", "path": "$.claims[].verification",
                               "detail": "verification 取值非法: {}".format(item.get("verification"))})
    for item in run["automation"]:
        if item.get("label") != "已投递":
            violations.append({"code": "E-SCHEMA", "path": "$.automation[].label",
                               "detail": "Automation 记录 label 必须固定为「已投递」，不得显示已执行/已完成"})
        if item.get("evidence", {}).get("level") not in rm.EVIDENCE_LEVELS:
            violations.append({"code": "E-SCHEMA", "path": "$.automation[].evidence.level",
                               "detail": "automation 证据等级非法"})
        elif item["evidence"]["level"] not in ("self-report", "tool-evidence"):
            violations.append({"code": "E-SCHEMA", "path": "$.automation[].evidence.level",
                               "detail": "automation 证据等级超出 tool-evidence 封顶"})
    for w in run["warnings"]:
        if not isinstance(w, dict) or not {"code", "source_ref", "detail"} <= set(w):
            violations.append({"code": "E-SCHEMA", "path": "$.warnings[]",
                               "detail": "warning 项必须含 code / source_ref / detail"})
    return violations


def _ref_ok(ref):
    import re
    return bool(isinstance(ref, str) and re.match(r"^s\d+(/|@)", ref))


def validate_references(run):
    violations = []
    tc_ids = {item.get("id") for item in run.get("tool_calls", [])}
    for item in run.get("steps", []):
        if not _ref_ok(item.get("source_ref")):
            violations.append({"code": "E-REF", "path": "$.steps[].source_ref",
                               "detail": "source_ref 形态非法: {}".format(item.get("source_ref"))})
        for ref in item.get("tool_call_ids", []):
            if ref not in tc_ids:
                violations.append({"code": "E-REF", "path": "$.steps[].tool_call_ids",
                                   "detail": "引用不存在的 tool_call: {}".format(ref)})
    for item in run.get("claims", []):
        if not _ref_ok(item.get("source_ref")):
            violations.append({"code": "E-REF", "path": "$.claims[].source_ref",
                               "detail": "source_ref 形态非法: {}".format(item.get("source_ref"))})
        for ref in item.get("verification_refs", []):
            if ref not in tc_ids:
                violations.append({"code": "E-REF", "path": "$.claims[].verification_refs",
                                   "detail": "引用不存在的 tool_call: {}".format(ref)})
    for key in ("tool_calls", "deliverables", "automation"):
        for item in run.get(key, []):
            if not _ref_ok(item.get("source_ref")):
                violations.append({"code": "E-REF", "path": "$.{}[].source_ref".format(key),
                                   "detail": "source_ref 形态非法: {}".format(item.get("source_ref"))})
    return violations


def validate_narrative(run, narrative):
    """narrative 白名单核验（设计蓝图 6）。返回违规列表。"""
    violations = []
    if not isinstance(narrative, dict):
        return [{"code": "E-NARR-SCHEMA", "path": "narrative", "detail": "narrative 必须是 JSON 对象"}]
    title = narrative.get("title")
    summary = narrative.get("summary")
    key_nodes = narrative.get("key_nodes")
    reader_notes = narrative.get("reader_notes")
    if not isinstance(title, str) or not isinstance(summary, str) \
            or not isinstance(key_nodes, list) or not isinstance(reader_notes, list):
        return [{"code": "E-NARR-SCHEMA", "path": "narrative",
                 "detail": "narrative 需含 title(str) / summary(str) / key_nodes(list) / reader_notes(list)"}]

    # 规则 4：长度上限，防叙事膨胀掩盖事实区
    for field, limit in _NARR_SIZE_LIMITS.items():
        value = title if field == "title" else summary if field == "summary" else None
        if value is not None and len(value) > limit:
            violations.append({"code": "E-NARR-SIZE", "path": "narrative." + field,
                               "detail": "长度 {} 超过上限 {}".format(len(value), limit)})

    known_ids = {item.get("id") for key in ("steps", "tool_calls", "deliverables", "claims")
                 for item in run.get(key, [])}

    texts = [title, summary] + list(reader_notes)
    for idx, node in enumerate(key_nodes):
        if not isinstance(node, dict):
            violations.append({"code": "E-NARR-SCHEMA", "path": "narrative.key_nodes[{}]".format(idx),
                               "detail": "key_nodes 项必须是对象"})
            continue
        heading, blurb = node.get("heading"), node.get("blurb")
        if not isinstance(heading, str) or not isinstance(blurb, str):
            violations.append({"code": "E-NARR-SCHEMA", "path": "narrative.key_nodes[{}]".format(idx),
                               "detail": "key_nodes 项需含 heading(str) / blurb(str)"})
            continue
        if len(heading) > _NARR_SIZE_LIMITS["heading"]:
            violations.append({"code": "E-NARR-SIZE", "path": "narrative.key_nodes[{}].heading".format(idx),
                               "detail": "heading 长度 {} 超过上限 {}".format(len(heading), _NARR_SIZE_LIMITS["heading"])})
        if len(blurb) > _NARR_SIZE_LIMITS["blurb"]:
            violations.append({"code": "E-NARR-SIZE", "path": "narrative.key_nodes[{}].blurb".format(idx),
                               "detail": "blurb 长度 {} 超过上限 {}".format(len(blurb), _NARR_SIZE_LIMITS["blurb"])})
        # 规则 1：ref 必须存在于 run 模型 id 集合
        if node.get("ref") not in known_ids:
            violations.append({"code": "E-NARR-REF", "path": "narrative.key_nodes[{}].ref".format(idx),
                               "detail": "引用不存在的 id: {}".format(node.get("ref"))})
        texts.append(heading)
        texts.append(blurb)

    full_text = "\n".join(t for t in texts if t)

    # 规则 3：narrative 不得出现证据等级字样——等级只由页面从 run.json 渲染。
    # v1.1.0：词表子串匹配升级为正则模式（A 类专名出现即违规，B 类仅验收语境违规）
    for pat in rm.NARRATIVE_LEVEL_PATTERNS:
        m = re.search(pat, full_text, re.I)
        if m:
            violations.append({"code": "E-NARR-LEVEL", "path": "narrative",
                               "detail": "叙事出现证据等级字样（等级只由脚本判定）: {}".format(m.group(0))})

    # 规则 2：事实候选必须能在事实集中找到完全一致项——新增即拒
    corpus = _fact_corpus(run)
    for cand in _fact_candidates(full_text):
        if cand not in corpus:
            violations.append({"code": "E-NARR-FACT", "path": "narrative",
                               "detail": "事实候选在事实集中不存在（不得新增事实）: {}".format(cand)})
    return violations


def validate_run(run, narrative=None):
    """全量校验。返回违规列表（非空即 exit 4）。"""
    violations = list(validate_schema(run))
    violations += validate_references(run)
    if narrative is not None:
        violations += validate_narrative(run, narrative)
    return violations
