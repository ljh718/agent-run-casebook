#!/usr/bin/env python3
"""dsh_events.py — DSH 官方信封事件格式（v2 / v4）解析。

职责（v1.2.0 修复）：
- 识别信封头行（type=session，带 version）与信封事件（type 形如 "user/message"，带 data 对象）
- 把信封事件映射为 normalize 的统一内部事件（user / assistant / tool_call / tool_result /
  deliverable / automation / title / unknown），合成格式解析完全不受影响（向后兼容）
- epoch ms 时间 → 确定性 ISO 8601 UTC（固定时区，重复构建逐字节一致）
- 头行 version：2 与 4 为已知契约（v2 / v4）；其他值写入 contract_hint，
  由 assemble_run_model 统一出 CONTRACT_VERSION_MISMATCH 并降级 unknown

不猜语义原则：
- step/*、turn/*、request/*、permission/preset、sandbox/mode、approval/policy、
  web/*、agent/inbox/*、session/title-llm-request 及其他未知类型 → 只记
  UNKNOWN_FIELD 警告并保留 source_ref（内部 etype=unknown 计入有效记录防止
  0 条误报，但不生成任何 user / assistant / claim 事件，也不进入渲染）
- job/settled 不推断执行成功：与 registered / delivery-accepted 一样只产出
  automation 事件，沿用「只标已投递 + 证据封顶 tool-evidence」语义
- system/* 记录整体排除（值不保留，只记 SYSTEM_RECORD 计数与警告）
"""

from datetime import datetime, timedelta, timezone

try:
    from . import runmodel as rm
except ImportError:  # 直接以脚本目录为 sys.path 运行时
    import runmodel as rm

# 头行 version → 契约版本提示（已知契约；其他值生成 "v<n>" 字符串，交由
# assemble_run_model 的锁定集检查降级）
KNOWN_HEAD_VERSIONS = {2: "v2", 4: "v4"}

# automation 语义的已知信封类型（只标「已投递」，绝不推断执行成功）
AUTOMATION_TYPES = frozenset({"job/registered", "job/settled"})
AUTOMATION_DELIVERY_SUFFIX = "/delivery-accepted"


# ── 识别 ────────────────────────────────────────────────────────────

def is_envelope_head(record):
    """信封头行：type=session 且带整数 version（合成格式不含 session 记录）。"""
    if not isinstance(record, dict):
        return False
    return record.get("type") == "session" and isinstance(record.get("version"), int) \
        and not isinstance(record.get("version"), bool)


def is_envelope_event(record):
    """信封事件：type 含 "/" 且 data 为对象（合成格式 type 不含 "/"）。"""
    if not isinstance(record, dict):
        return False
    rtype = record.get("type")
    return isinstance(rtype, str) and "/" in rtype and isinstance(record.get("data"), dict)


def capture_head(record, state):
    """读取头行 version → contract_hint 写入跨行共享 state；头行本身不产事件。"""
    version = record.get("version")
    if isinstance(version, str) and version.strip().isdigit():
        version = int(version.strip())
    if isinstance(version, int) and not isinstance(version, bool):
        hint = KNOWN_HEAD_VERSIONS.get(version, "v{}".format(version))
    else:
        hint = str(version)
    state["envelope_version"] = hint


# ── 时间与块工具 ────────────────────────────────────────────────────

def epoch_ms_to_dt(value):
    """epoch 毫秒 → aware datetime（UTC，微秒精度，整除实现避免浮点误差）。
    非 正数值 / 布尔 → None（缺时间不估算）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    total = int(value)
    if total <= 0:
        return None
    sec, ms = divmod(total, 1000)
    return datetime.fromtimestamp(sec, tz=timezone.utc) + timedelta(milliseconds=ms)


def _text_of_blocks(content):
    """content 块列表中 text 块按序拼接（非空块以换行连接，确定性）。"""
    if not isinstance(content, list):
        return ""
    parts = [str(b.get("text", "") or "") for b in content
             if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def _usage_tokens(usage):
    """data.usage 中的数值 token 求和；无 cost 不估算。
    规则（确定性）：键名含 token（不含 cache）的数值求和；若无 token 键且
    input / output 均为数值则取二者之和。无可用值返回 None。"""
    if not isinstance(usage, dict):
        return None
    total, found = 0, False
    for key, value in usage.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        low = str(key).lower()
        if "token" in low and "cache" not in low:
            total += value
            found = True
    if not found:
        if isinstance(usage.get("input"), (int, float)) and not isinstance(usage.get("input"), bool) \
                and isinstance(usage.get("output"), (int, float)) and not isinstance(usage.get("output"), bool):
            total = usage["input"] + usage["output"]
            found = True
    return total if found and total > 0 else None


def _event(etype, ref, ts, hint, origin, **kw):
    ev = {"etype": etype, "ref": ref, "ts": ts, "text": "", "name": "",
          "call_id": None, "tool_call_id": None, "status": None,
          "duration_ms": None, "path": None, "kind": None,
          "tokens": None, "cost": None, "order": 0, "origin": origin,
          "contract_hint": hint, "unknown_fields": []}
    ev.update(kw)
    return ev


# ── 主解析 ──────────────────────────────────────────────────────────

def envelope_record_events(record, line_no, scope_prefix, warnings, state):
    """单条信封事件 → 内部事件列表。state 为跨行共享计数器（沿用 normalize 口径）。"""
    rtype = str(record.get("type", "")).strip()
    data = record.get("data") or {}
    ref_base = rm.make_ref(scope_prefix, line_no)

    # 结构排除：system/* / developer/* 信封记录整体排除（值不保留）
    head_seg = rtype.split("/", 1)[0].strip().lower()
    if head_seg in ("system", "developer"):
        state["excluded_records"] = state.get("excluded_records", 0) + 1
        warnings.append({"code": "STRUCT_EXCLUDED", "source_ref": ref_base,
                         "detail": "system/developer 信封记录整体排除，不进入运行模型"})
        return []

    hint = state.get("envelope_version")
    ts = epoch_ms_to_dt(record.get("time"))
    events = []

    def mk(etype, jpath, origin=None, **kw):
        ref = rm.make_ref(scope_prefix, line_no, jpath) if jpath else ref_base
        ev = _event(etype, ref, ts, hint, origin if origin is not None else rtype, **kw)
        events.append(ev)
        return ev

    if rtype == "user/message":
        content = data.get("content")
        mk("user", "type", origin="user", text=_text_of_blocks(content))
        if isinstance(content, list):
            for idx, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "file":
                    continue
                attachment = block.get("attachment")
                name = attachment.get("name") if isinstance(attachment, dict) else None
                if name:
                    mk("deliverable", "content[{}].attachment.name".format(idx),
                       origin="user", path=str(name))
        return events

    if rtype == "assistant/message":
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = msg.get("content")
        ev = mk("assistant", "type", origin="assistant", text=_text_of_blocks(content))
        tokens = _usage_tokens(data.get("usage"))
        if tokens is not None:
            ev["tokens"] = tokens
        if isinstance(content, list):
            for idx, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "tool-call":
                    continue
                call_id = block.get("callId")
                ev = _event(
                    "tool_call",
                    rm.make_ref(scope_prefix, line_no, "message.content[{}]".format(idx)),
                    ts, hint, "assistant",
                    name=str(block.get("name", "") or ""), call_id=call_id)
                if call_id is None:
                    # 真实 v4 形态：块不带 callId（实测 0/22 带）。先按原位置
                    # 产出（保证未消解块的位置与静默消除警告），由
                    # merge_pending_tool_blocks 在文档作用域内与随后的
                    # 同名带 callId tool_call 事件合并。
                    ev["_dsh_block_no_callid"] = True
                events.append(ev)
        return events

    if rtype == "tool/call":
        mk("tool_call", "type", origin="tool",
           call_id=data.get("callId"), name=str(data.get("name", "") or ""))
        return events

    if rtype == "tool/result":
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        status = "fail" if msg.get("isError") else "ok"
        mk("tool_result", "type", origin="tool",
           tool_call_id=msg.get("toolCallId"), status=status)
        return events

    if rtype == "session/title":
        mk("title", "type", text=str(data.get("title", "") or ""))
        return events

    if rtype in AUTOMATION_TYPES or rtype.endswith(AUTOMATION_DELIVERY_SUFFIX):
        name = data.get("name") or data.get("title") or data.get("id") or ""
        mk("automation", "type", kind="automation", name=str(name))
        return events

    # 未知信封事件类型：不猜语义——UNKNOWN_FIELD 警告 + 保留来源引用；
    # 内部 etype=unknown 计入有效记录（防 0 条误报），不生成任何
    # user / assistant / claim 事件，也不进入渲染。
    mk("unknown", "type")
    warnings.append({"code": "UNKNOWN_FIELD", "source_ref": ref_base,
                     "detail": "未识别的信封事件类型（未解读，仅保留来源引用）: {}".format(rtype)})
    return events


def merge_pending_tool_blocks(events, warnings):
    """无 callId 的 tool-call 块合并（v1.2.0，真实 v4 形态 0/22 块带 callId）。

    不合并的后果：每次调用产出两条 tool_call（块副本 call_id=None），
    统计精确翻倍。规则（确定性，单遍）：
      - 作用域 = source_ref 首段（与 pair_tool_calls 一致），跨作用域不合并。
      - 带下划线前缀的内部标记 _dsh_block_no_callid 只由本模块设置；
        无标记的 call_id=None tool_call（合成格式 / Markdown）不受影响。
      - 同一作用域内，随后出现的带 callId 的 tool_call 事件（信封 tool/call
        或带 callId 的块）与「首个未消解同名 pending 块」合并：块副本从事件
        流移除（视为已消解），callId 事件保留——tool_call 数 == 带 callId
        事件数。
      - 文档结束时仍未消解的 pending 块保留原位置（call_id=None），并出
        UNMERGED_TOOL_CALL_BLOCK 警告（消除静默）。
    """
    pending = {}  # scope -> [event, ...]（未消解）
    for ev in events:
        scope = ev["ref"].split("/")[0]
        if ev.get("_dsh_block_no_callid"):
            pending.setdefault(scope, []).append(ev)
        elif ev["etype"] == "tool_call" and ev.get("call_id") is not None:
            candidates = [p for p in pending.get(scope, ())
                          if p.get("name") == ev.get("name")]
            if candidates:
                candidates[0]["_dsh_resolved"] = True
                pending[scope].remove(candidates[0])
    resolved = 0
    for ev in events:
        if ev.get("_dsh_block_no_callid") and ev.get("_dsh_resolved"):
            resolved += 1
    if resolved:
        events[:] = [ev for ev in events
                     if not (ev.get("_dsh_block_no_callid") and ev.get("_dsh_resolved"))]
    for ev in events:
        if ev.get("_dsh_block_no_callid"):
            warnings.append({"code": "UNMERGED_TOOL_CALL_BLOCK", "source_ref": ev["ref"],
                             "detail": "assistant tool-call 块未带 callId 且未能在同一文档作用域内"
                                       "与同名 tool/call 事件合并，按无 callId 工具调用保留: {}".format(
                                           ev.get("name", ""))})
