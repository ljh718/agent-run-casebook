#!/usr/bin/env python3
"""normalize.py — 输入识别与归一化（ZIP / JSONL / Markdown → 原始 run 模型）。

职责（设计蓝图 5.2）：
- detect_input: ZIP 魔数 / JSONL 首行可解析 / Markdown 标题结构嗅探
- parse_jsonl / parse_zip / parse_markdown
- pair_tool_calls: 同一文档作用域内 callId ↔ toolCallId 配对，跨作用域不配对
- collect_unknown_fields: 契约键集外字段只保留来源引用与警告
- assemble_run_model: 生成统一 Run JSON（含确定性 source_ref）

失败行为：坏 JSON 行不静默跳过——计入 degradations（PARSE_ERROR）并继续；
整文件无有效记录 → UnrecognizedInputError（CLI exit 3）。
"""

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

try:
    from . import runmodel as rm
except ImportError:  # 直接以脚本目录为 sys.path 运行时
    import runmodel as rm


class UnrecognizedInputError(ValueError):
    """输入不可识别（空文件、非 ZIP/JSONL/Markdown、零有效记录）。"""


EVENT_TYPES = ("user", "assistant", "tool_call", "tool_result",
               "check", "automation", "deliverable")

_FILE_TOKEN_RE = re.compile(
    r"\b[A-Za-z0-9_\-.\\/\u4e00-\u9fff]*[A-Za-z0-9_\-]+\."
    r"(?:py|json|jsonl|md|csv|txt|html|htm|zip|png|jpg|jpeg|svg|log|yaml|yml|toml)\b")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SLUG_KEEP_RE = re.compile(r"[^\w\u4e00-\u9fff-]+")


def _slug(text):
    slug = _SLUG_KEEP_RE.sub("-", str(text).strip())
    return slug.strip("-") or "sec"


def _parse_ts(value):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── 输入嗅探 ────────────────────────────────────────────────────────

def detect_input(path):
    """返回输入类型（rm.SOURCE_KINDS 之一）；不可识别抛 UnrecognizedInputError。"""
    p = Path(path)
    if not p.is_file():
        raise UnrecognizedInputError("输入不是文件: {}".format(p))
    with open(p, "rb") as f:
        head = f.read(4)
    if head[:2] == b"PK":
        return "dsh-zip"
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise UnrecognizedInputError("输入文件为空: {}".format(p))
    try:
        first = json.loads(lines[0])
        if isinstance(first, dict):
            return "dsh-jsonl"
    except json.JSONDecodeError:
        pass
    if any(_MD_HEADING_RE.match(ln) for ln in text.splitlines()):
        headings = [m.group(2) for m in
                    (_MD_HEADING_RE.match(ln) for ln in text.splitlines())
                    if m]
        role_words = ("用户", "助手", "工具", "user", "assistant", "tool")
        joined = " ".join(headings).lower()
        kind = "dsh-markdown" if any(w in joined for w in role_words) else "generic-markdown"
        return kind
    raise UnrecognizedInputError(
        "输入不可识别（非 ZIP / JSONL / Markdown）: {}".format(p))


# ── 事件流构造 ──────────────────────────────────────────────────────

# 结构排除集（蓝图 §7 规则 1）：隐藏推理字段与 system/developer 记录
# 整体不进入运行模型，只记排除计数与警告，值不保留、不渲染。
EXCLUDED_RECORD_TYPES = frozenset({"system", "developer"})
EXCLUDED_FIELD_KEYS = frozenset({
    "reasoning", "thinking", "thought", "reasoning_content",
    "system_prompt", "developer_messages", "hidden_thought",
})

EXCLUSION_LABELS = {
    "SYSTEM_RECORD": "system/developer 记录",
    "HIDDEN_REASONING": "隐藏推理字段",
}


def _event(etype, ref, **kw):
    ev = {"etype": etype, "ref": ref, "ts": None, "text": "", "name": "",
          "call_id": None, "tool_call_id": None, "status": None,
          "duration_ms": None, "path": None, "kind": None,
          "tokens": None, "cost": None, "order": 0, "origin": "",
          "contract_hint": None, "unknown_fields": []}
    ev.update(kw)
    return ev


def _unknown_from_record(record, base_ref, warnings, state=None):
    """契约键集外字段：保留字段名 + source_ref（标量另存原值），不猜语义。
    隐藏推理字段（reasoning / thinking 等）整体排除：值不保留，计数并警告。"""
    unknown = []
    for key, value in record.items():
        if key in rm.CONTRACT_KNOWN_KEYS:
            continue
        if key.lower() in EXCLUDED_FIELD_KEYS:
            if state is not None:
                state["excluded_fields"] = state.get("excluded_fields", 0) + 1
            warnings.append({"code": "STRUCT_EXCLUDED", "source_ref": base_ref,
                             "detail": "隐藏推理字段已整体排除，值不进入运行模型: {}".format(key)})
            continue
        entry = {"name": key, "source_ref": "{}".format(base_ref)}
        if isinstance(value, (str, int, float, bool)) or value is None:
            entry["value"] = value
        unknown.append(entry)
        warnings.append({"code": "UNKNOWN_FIELD", "source_ref": base_ref,
                         "detail": "未识别字段（未解读）: {}".format(key)})
    return unknown


def _jsonl_record_events(record, line_no, scope_prefix, warnings, state):
    """单条 JSONL 记录 → 事件列表。state 为跨记录共享计数器（结构排除统计）。"""
    ref_base = rm.make_ref(scope_prefix, line_no)
    rtype = str(record.get("type", "")).strip().lower()
    role = str(record.get("role", "")).strip().lower()
    if rtype in EXCLUDED_RECORD_TYPES or role in EXCLUDED_RECORD_TYPES:
        state["excluded_records"] = state.get("excluded_records", 0) + 1
        warnings.append({"code": "STRUCT_EXCLUDED", "source_ref": ref_base,
                         "detail": "system/developer 记录整体排除，不进入运行模型"})
        return []
    unknown = _unknown_from_record(record, ref_base, warnings, state)
    contract_hint = record.get("schemaVersion", record.get("contract_version"))
    ts = record.get("ts", record.get("timestamp"))
    text = record.get("text", record.get("content", "")) or ""
    events = []

    def mk(etype, jpath, **kw):
        ev = _event(etype, rm.make_ref(scope_prefix, line_no, jpath),
                    ts=_parse_ts(ts), text=str(text), origin=rtype or "record",
                    contract_hint=contract_hint,
                    unknown_fields=unknown, **kw)
        events.append(ev)
        return ev

    if rtype in ("automation", "schedule") or str(record.get("kind", "")).lower() in ("automation", "schedule"):
        ev = mk("automation", "type", name=str(record.get("name", record.get("title", "")) or ""))
        ev["kind"] = "schedule" if (rtype == "schedule" or str(record.get("kind", "")).lower() == "schedule") else "automation"
        return events
    if rtype == "user" or record.get("role") == "user":
        mk("user", "type")
        return events
    if rtype == "assistant":
        mk("assistant", "type")
        for idx, call in enumerate(record.get("toolCalls") or []):
            if not isinstance(call, dict):
                continue
            call_ref = rm.make_ref(scope_prefix, line_no, "toolCalls[{}]".format(idx))
            events.append(_event(
                "tool_call", call_ref, ts=_parse_ts(call.get("ts")),
                name=str(call.get("name", "") or ""), call_id=call.get("callId"),
                status=call.get("status"),
                duration_ms=call.get("durationMs"),
                unknown_fields=_unknown_from_record(call, call_ref, warnings, state)))
        for entry in record.get("deliverables") or []:
            if isinstance(entry, dict) and entry.get("path"):
                mk("deliverable", "type", path=str(entry.get("path")))
        return events
    if rtype in ("tool", "tool_call") or record.get("callId") is not None:
        if record.get("toolCallId") is not None:
            mk("tool_result", "type", tool_call_id=record.get("toolCallId"),
               status=record.get("status"), name=str(record.get("name", "") or ""),
               duration_ms=record.get("durationMs"))
            return events
        mk("tool_call", "type", call_id=record.get("callId"),
           name=str(record.get("name", record.get("title", "")) or ""),
           status=record.get("status"), duration_ms=record.get("durationMs"))
        return events
    if rtype in ("check", "verification"):
        mk("check", "type", status=record.get("status"),
           name=str(record.get("name", record.get("title", "")) or ""))
        return events
    # 无已知 type：按字段形态落位，形态也不符则仅保留警告
    if record.get("path", record.get("filePath")):
        mk("deliverable", "type", path=str(record.get("path", record.get("filePath"))))
    elif record.get("callId") is not None:
        mk("tool_call", "type", call_id=record.get("callId"),
           name=str(record.get("name", "")))
    else:
        warnings.append({"code": "UNKNOWN_FIELD", "source_ref": ref_base,
                         "detail": "记录无已知 type 且无可用字段形态，仅保留来源引用"})
    return events


def _iter_jsonl_lines(text, scope_prefix, warnings, degradations, state=None):
    """逐行解析 JSONL；坏行计入 PARSE_ERROR 并继续。
    返回 (events, state)；state 为结构排除计数器（跨行共享）。"""
    events = []
    if state is None:
        state = {"excluded_records": 0, "excluded_fields": 0}
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            ref = rm.make_ref(scope_prefix, line_no)
            degradations.append({"code": "PARSE_ERROR", "reason": "第 {} 行 JSON 解析失败: {}".format(line_no, exc.msg),
                                 "source_ref": ref})
            warnings.append({"code": "PARSE_ERROR", "source_ref": ref,
                             "detail": "坏 JSON 行，已降级保留来源引用"})
            continue
        if not isinstance(record, dict):
            ref = rm.make_ref(scope_prefix, line_no)
            degradations.append({"code": "PARSE_ERROR",
                                 "reason": "第 {} 行不是 JSON 对象".format(line_no),
                                 "source_ref": ref})
            continue
        for item in _jsonl_record_events(record, line_no, scope_prefix, warnings, state):
            events.append(item)
    return events, state


def parse_jsonl(path, ordinal):
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    warnings, degradations = [], []
    events, state = _iter_jsonl_lines(text, "s{}".format(ordinal), warnings, degradations)
    record_count = sum(1 for ln in text.splitlines() if ln.strip())
    inputs = [{"ordinal": ordinal, "name": p.name, "record_count": record_count}]
    return events, inputs, warnings, degradations, state


def parse_zip(path, ordinal):
    p = Path(path)
    warnings, degradations = [], []
    events, inputs = [], []
    skipped = 0
    state = {"excluded_records": 0, "excluded_fields": 0}
    with zipfile.ZipFile(p) as zf:
        infos = sorted(zf.infolist(), key=lambda i: i.filename)
        member_ordinal = ordinal
        for info in infos:
            name = info.filename
            if name.endswith("/"):
                continue
            lower = name.lower()
            if not (lower.endswith(".jsonl") or lower.endswith(".md") or lower.endswith(".markdown")):
                skipped += 1
                continue
            member_prefix = "s{}@{}".format(member_ordinal, name)
            text = zf.read(info).decode("utf-8", errors="replace")
            if lower.endswith(".jsonl"):
                member_events, state = _iter_jsonl_lines(text, member_prefix, warnings, degradations, state)
                events.extend(member_events)
                count = sum(1 for ln in text.splitlines() if ln.strip())
            else:
                events.extend(_parse_markdown_text(text, member_prefix, warnings))
                count = sum(1 for _ in text.splitlines() if _.strip())
            inputs.append({"ordinal": member_ordinal, "name": name, "record_count": count})
            member_ordinal += 1
    return events, inputs, warnings, degradations, skipped, state


# ── Markdown 解析（文本模式） ───────────────────────────────────────

_ROLE_USER = ("用户", "user")
_ROLE_ASSISTANT = ("助手", "assistant")
_ROLE_TOOL = ("工具", "tool")


def _parse_markdown_text(text, scope_prefix, warnings):
    """结构化 Markdown（用户 / 助手 / 工具标题）→ 事件流。"""
    events = []
    cur_role = None
    cur_title = ""
    cur_level = 0
    cur_start_line = 0
    buf = []
    file_idx = 0

    def flush(end_line):
        nonlocal buf, file_idx
        if cur_role is None or not buf:
            return
        body = "\n".join(buf).strip()
        ref = "{}/h{}:{}/L{}".format(scope_prefix, cur_level, _slug(cur_title), cur_start_line)
        if cur_role == "user":
            events.append(_event("user", ref, text=body, origin="user"))
        elif cur_role == "assistant":
            events.append(_event("assistant", ref, text=body, origin="assistant"))
        else:
            name = cur_title.split("：", 1)[-1].split(":", 1)[-1].strip()
            status = None
            for ln in buf:
                low = rm.norm_status(ln.strip())
                if low in rm.PASS_WORDS or low in rm.FAIL_WORDS:
                    status = ln.strip()
                    break
            events.append(_event("tool_call", ref, name=name, status=status, text=body, origin="tool"))
        # 文本模式交付物：正文中的文件样式 token（确定性正则，非语义判断）
        for off, ln in enumerate(buf):
            for tok in _FILE_TOKEN_RE.findall(ln):
                file_idx += 1
                events.append(_event(
                    "deliverable",
                    "{}/h{}:{}/L{}".format(scope_prefix, cur_level, _slug(cur_title), cur_start_line + off),
                    path=tok, origin=cur_role))

    line_no = 0
    lines = text.splitlines()
    while line_no < len(lines):
        raw = lines[line_no]
        line_no += 1
        m = _MD_HEADING_RE.match(raw)
        if m:
            flush(line_no - 1)
            level = len(m.group(1))
            title = m.group(2).strip()
            low = title.lower()
            if any(w in low for w in _ROLE_USER):
                cur_role = "user"
            elif any(w in low for w in _ROLE_ASSISTANT):
                cur_role = "assistant"
            elif any(w in low for w in _ROLE_TOOL):
                cur_role = "tool"
            else:
                cur_role = None
            cur_title, cur_level, cur_start_line = title, level, line_no
            buf = []
        elif cur_role is not None:
            buf.append(raw)
    flush(len(lines))
    return events


def parse_markdown(path, ordinal):
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    warnings = []
    events = _parse_markdown_text(text, "s{}".format(ordinal), warnings)
    inputs = [{"ordinal": ordinal, "name": p.name,
               "record_count": sum(1 for ln in text.splitlines() if ln.strip())}]
    return events, inputs, warnings, [], 0, {"excluded_records": 0, "excluded_fields": 0}


def parse_zip_entry(path, ordinal):
    return parse_zip(path, ordinal)


# ── callId ↔ toolCallId 配对（同一文档作用域内） ────────────────────

def pair_tool_calls(events):
    """按文档作用域内 callId ↔ toolCallId 配对。
    作用域 = source_ref 首段（JSONL: s<n>；ZIP 成员: s<n>@<成员名>；
    Markdown: s<n>，整份文档一个作用域）。跨作用域不配对，未配对产出警告。
    返回 (paired_call_ids, unpaired_warnings)
    """
    calls = {}    # scope -> {call_id: event}
    results = []  # (scope, event)
    for ev in events:
        scope = ev["ref"].split("/")[0]
        if ev["etype"] == "tool_call" and ev.get("call_id"):
            calls.setdefault(scope, {}).setdefault(ev["call_id"], ev)
        elif ev["etype"] == "tool_result" and ev.get("tool_call_id"):
            results.append((scope, ev))
    paired, unpaired = [], []
    for scope, ev in results:
        target = calls.get(scope, {}).get(ev["tool_call_id"])
        if target is None:
            unpaired.append({
                "code": "UNPAIRED_TOOL_CALL", "source_ref": ev["ref"],
                "detail": "toolCallId 在同一文档作用域内未找到对应 callId: {}".format(ev["tool_call_id"])})
            continue
        paired.append(ev["tool_call_id"])
        if ev.get("status") is not None:
            target["status"] = ev["status"]
        if ev.get("duration_ms") is not None:
            target["duration_ms"] = ev["duration_ms"]
    return paired, unpaired


def collect_unknown_fields(record, contract_keys):
    """与 _unknown_from_record 同源的独立入口（供测试与复用）。"""
    warnings = []
    return _unknown_from_record(record, "s1/L1", warnings), warnings


# ── 组装统一 Run 模型 ───────────────────────────────────────────────

_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|\n+")


def _window_events(events, start_idx):
    """当前 assistant 事件之后、下一个 assistant 事件之前（跨作用域连续编号）。"""
    out = []
    for ev in events[start_idx + 1:]:
        if ev["etype"] == "assistant":
            break
        out.append(ev)
    return out


def assemble_run_model(kind, events, inputs, warnings, degradations, skipped_members=0,
                       exclusions=None):
    events = list(events)
    for i, ev in enumerate(events):
        ev["order"] = i
    _, unpaired = pair_tool_calls(events)
    warnings.extend(unpaired)
    excl = exclusions or {}
    exclusions_list = []
    if excl.get("excluded_records"):
        exclusions_list.append({"code": "SYSTEM_RECORD", "count": excl["excluded_records"]})
    if excl.get("excluded_fields"):
        exclusions_list.append({"code": "HIDDEN_REASONING", "count": excl["excluded_fields"]})

    # 契约版本：来自 schemaVersion / contract_version 字段（已知键，直接读取）
    contract_version = None
    for ev in events:
        hint = ev.get("contract_hint")
        if hint not in (None, ""):
            contract_version = str(hint)
            break
    if contract_version is None:
        contract_version = "v2" if kind in ("dsh-zip", "dsh-jsonl") else "unknown"
    elif contract_version not in rm.LOCKED_CONTRACT_VERSIONS:
        warnings.append({"code": "CONTRACT_VERSION_MISMATCH",
                         "source_ref": inputs[0]["name"] if inputs else "s1",
                         "detail": "契约版本 {} 不在锁定集内，整体降级并保留来源引用".format(contract_version)})
        contract_version = "unknown"

    # 任务与时间
    goal = None
    started_at, ended_at = None, None
    for ev in events:
        if ev["etype"] == "user" and not goal:
            goal = ev["text"].strip()[:200] or None
        ts = ev.get("ts")
        if ts is not None:
            if started_at is None or ts < started_at:
                started_at = ts
            if ended_at is None or ts > ended_at:
                ended_at = ts

    # 工具调用（配对后状态）
    tool_calls, call_id_to_id = [], {}
    tc_n = 0
    for ev in events:
        if ev["etype"] == "tool_call":
            tc_n += 1
            tid = "tc-{}".format(tc_n)
            call_id_to_id[ev.get("call_id")] = tid
            tool_calls.append({
                "id": tid, "name": ev.get("name", ""), "call_id": ev.get("call_id"),
                "status": ev.get("status"), "ts": ev["ts"].isoformat() if ev.get("ts") else None,
                "duration_ms": ev.get("duration_ms"), "source_ref": ev["ref"],
                "unknown_fields": ev.get("unknown_fields", [])})

    # 步骤（窗口 = 当前 assistant 到下一个 assistant 之间）
    steps = []
    step_n = 0
    for i, ev in enumerate(events):
        if ev["etype"] != "assistant":
            continue
        step_n += 1
        window = _window_events(events, i)
        window_call_ids = [call_id_to_id[w.get("call_id")] for w in window
                           if w["etype"] == "tool_call" and w.get("call_id") in call_id_to_id]
        title = ev["text"].strip().splitlines()[0][:60] if ev["text"].strip() else "助手回复"
        steps.append({"id": "step-{}".format(step_n), "title": title or "助手回复",
                      "text": ev["text"], "source_ref": ev["ref"],
                      "tool_call_ids": window_call_ids,
                      "ts": ev["ts"].isoformat() if ev.get("ts") else None,
                      "unknown_fields": ev.get("unknown_fields", [])})

    # 主张与验证记录归属（确定性）：状态型事件（check / tool_result）归属到
    # 与之最近的主张所在 assistant 事件（距离并列时取前面），不 guess 语义。
    claim_specs = []  # (assistant_idx, sentence)
    for i, ev in enumerate(events):
        if ev["etype"] != "assistant":
            continue
        for sentence in _SENT_SPLIT_RE.split(ev["text"]):
            sentence = sentence.strip()
            if sentence and rm.is_completion_claim(sentence):
                claim_specs.append((i, sentence))
    claim_assistant_idx = sorted({i for i, _ in claim_specs})

    def _nearest_claim_assistant(j):
        if not claim_assistant_idx:
            return None
        return min(claim_assistant_idx,
                   key=lambda a: (abs(j - a), 0 if a <= j else 1))

    attributed = {}  # assistant_idx -> {"statuses": [(etype,status)], "refs": [tc-id]}
    for j, ev in enumerate(events):
        if ev["etype"] not in ("check", "tool_result"):
            continue
        if ev.get("status") is None or str(ev["status"]).strip() == "":
            continue
        owner = _nearest_claim_assistant(j)
        if owner is None:
            continue
        slot = attributed.setdefault(owner, {"statuses": [], "refs": []})
        slot["statuses"].append({"etype": ev["etype"], "status": ev["status"]})
        if ev["etype"] == "tool_result" and ev.get("tool_call_id") in call_id_to_id:
            slot["refs"].append(call_id_to_id[ev["tool_call_id"]])
    # 工具调用事件同样按最近主张归属（确定性），作为规则 3 的工具记录输入：
    # 「仅工具动作、未复验」的主张由此可判为 tool-evidence。
    for j, ev in enumerate(events):
        if ev["etype"] != "tool_call":
            continue
        owner = _nearest_claim_assistant(j)
        if owner is None:
            continue
        slot = attributed.setdefault(owner, {"statuses": [], "refs": []})
        slot["statuses"].append({"etype": "tool_call", "status": None})

    claims = []
    claim_n = 0
    for i, sentence in claim_specs:
        claim_n += 1
        ev = events[i]
        slot = attributed.get(i, {"statuses": [], "refs": []})
        verdict = rm.decide_evidence({"text": sentence}, slot["statuses"])
        for wmsg in verdict["warnings"]:
            warnings.append({"code": "EVIDENCE_STATUS_UNKNOWN",
                             "source_ref": ev["ref"], "detail": wmsg})
        claims.append({
            "id": "c-{}".format(claim_n), "text": sentence, "source_ref": ev["ref"],
            "evidence_level": verdict["level"], "verification": verdict["verification"],
            "verification_refs": list(dict.fromkeys(slot["refs"]))})

    # 交付物（按 path 去重，保留首个来源）
    deliverables, seen_paths = [], set()
    d_n = 0
    for ev in events:
        if ev["etype"] != "deliverable" or not ev.get("path"):
            continue
        if ev["path"] in seen_paths:
            continue
        seen_paths.add(ev["path"])
        d_n += 1
        # 确定性证据：来自用户侧记录 → self-report；来自工具 / 助手侧 → tool-evidence
        level = "self-report" if ev.get("origin") == "user" else "tool-evidence"
        dkind = "chart" if ev["path"].lower().endswith((".png", ".jpg", ".jpeg", ".svg")) else "file"
        deliverables.append({"id": "d-{}".format(d_n), "path": ev["path"], "kind": dkind,
                             "source_ref": ev["ref"],
                             "evidence": {"level": level, "verification": "unverified"}})

    # Automation / Schedule：只标「已投递」，证据封顶
    automation = []
    a_n = 0
    for ev in events:
        if ev["etype"] != "automation":
            continue
        a_n += 1
        automation.append({"id": "a-{}".format(a_n),
                           "kind": ev.get("kind") or "automation",
                           "label": "已投递",
                           "delivered_at": ev["ts"].isoformat() if ev.get("ts") else None,
                           "source_ref": ev["ref"],
                           "evidence": {"level": rm.automation_cap("tool-evidence"),
                                        "verification": "unverified"}})

    # 指标：仅源数据存在时出现，缺键即隐藏
    metrics = {}
    if started_at is not None and ended_at is not None:
        metrics["duration_ms"] = int((ended_at - started_at).total_seconds() * 1000)
    tokens_total = sum(ev["tokens"] for ev in events
                       if isinstance(ev.get("tokens"), (int, float)))
    cost_total = sum(ev["cost"] for ev in events
                     if isinstance(ev.get("cost"), (int, float)))
    if tokens_total:
        metrics["tokens"] = tokens_total
    if cost_total:
        metrics["cost"] = cost_total

    if degradations:
        warnings.append({"code": "PARTIAL_RECORDS", "source_ref": inputs[0]["name"] if inputs else "s1",
                         "detail": "{} 条记录解析失败，已降级保留来源引用".format(len(degradations))})

    run = {
        "schema_version": rm.SCHEMA_VERSION,
        "generator": {"name": rm.GENERATOR_NAME, "version": rm.GENERATOR_VERSION},
        "source": {
            "kind": kind,
            "mode": "text" if kind in ("dsh-markdown", "generic-markdown") else "full",
            "inputs": inputs,
            "contract_version": contract_version,
            "degradations": degradations,
            "exclusions": exclusions_list,
        },
        "task": {"goal": goal,
                 "started_at": started_at.isoformat() if started_at else None,
                 "ended_at": ended_at.isoformat() if ended_at else None},
        "steps": steps,
        "tool_calls": tool_calls,
        "deliverables": deliverables,
        "claims": claims,
        "automation": automation,
        "metrics": metrics,
        "narrative": None,
        "narrative_check": {"passed": False, "violations": [], "reason": "no-narrative"},
        "warnings": warnings,
    }
    report = {
        "kind": kind,
        "mode": run["source"]["mode"],
        "record_count": sum(inp["record_count"] for inp in inputs),
        "parse_errors": len(degradations),
        "skipped_members": skipped_members,
        "warnings": len(warnings),
        "steps": len(steps), "tool_calls": len(tool_calls),
        "claims": len(claims), "deliverables": len(deliverables),
        "automation": len(automation),
    }
    return run, report


def parse_input(path, ordinal=1):
    """入口：识别 + 解析 + 组装。返回 (run, report)。"""
    kind = detect_input(path)
    if kind == "dsh-zip":
        events, inputs, warnings, degradations, skipped, state = parse_zip(path, ordinal)
    elif kind == "dsh-jsonl":
        events, inputs, warnings, degradations, state = parse_jsonl(path, ordinal)
        skipped = 0
    else:
        events, inputs, warnings, degradations, skipped, state = parse_markdown(path, ordinal)
    if not events:
        raise UnrecognizedInputError("未解析到任何有效记录: {}".format(path))
    return assemble_run_model(kind, events, inputs, warnings, degradations, skipped, state)
