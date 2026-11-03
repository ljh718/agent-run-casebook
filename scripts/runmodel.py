#!/usr/bin/env python3
"""runmodel.py — 统一 Run JSON 模型常量与纯函数。

职责（设计蓝图 5.3）：
- Run JSON schema 常量（证据词表、契约已知键集、生成器标识）
- 五级证据判定纯函数 decide_evidence（脚本确定性判定，模型无授予通道）
- Automation「已投递」封顶 automation_cap
- source_ref 生成 make_ref 与 HTML 锚点 make_anchor_id

本模块为纯函数集合，不读取文件、不依赖 cwd、无第三方依赖。
"""

import hashlib

SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "agent-run-casebook"
GENERATOR_VERSION = "1.0.0"

# ── 五级证据词表 ────────────────────────────────────────────────────
EVIDENCE_LEVELS = (
    "self-report",
    "tool-evidence",
    "external-verification",
    "unverified",
    "failed",
)

# 检查记录状态受控词表：只认原文，词表外值降档并出 warning
PASS_WORDS = frozenset({
    "pass", "passed", "ok", "okay", "success", "succeeded", "green",
    "通过", "成功", "成功通过",
})
FAIL_WORDS = frozenset({
    "fail", "failed", "failure", "error", "errored", "red",
    "失败", "错误", "未通过",
})

# 主张「完成 / 成功」的受控标记词：句子中出现即视为完成主张
CLAIM_MARKERS = (
    "完成", "成功", "通过", "已修复", "已生成", "已部署", "已交付",
    "fixed", "completed", "succeeded", "success", "done", "shipped",
)

# 证据等级禁止进入叙事（validate_case 使用；ASCII 词不分大小写）
NARRATIVE_LEVEL_WORDS = (
    "已复验", "已验证", "已执行", "已完成", "已复核",
    "verified", "unverified", "failed",
    "external-verification", "tool-evidence", "self-report",
)

# ── 结构化敏感键（值整体替换，见 redact.py R-STRUCT） ───────────────
SENSITIVE_STRUCT_KEYS = frozenset({
    "cookie", "set-cookie", "set_cookie", "authorization",
    "proxy-authorization", "api_key", "apikey", "api-key", "token",
    "access_token", "refresh_token", "id_token", "secret", "client_secret",
    "secret_key", "private_key", "password", "passwd", "pwd",
    "connectionstring", "connection_string", "database_url", "db_url",
    "auth", "credentials", "env", "environment", "env_vars", "environ",
})

# ── 输入契约已知键集（单点维护；键集外字段只保留来源引用与警告） ──
CONTRACT_KNOWN_KEYS = frozenset({
    "type", "callId", "toolCallId", "name", "title", "content", "text",
    "status", "ts", "timestamp", "durationMs", "path", "filePath", "kind",
    "toolCalls", "tokens", "cost", "schemaVersion", "contract_version",
    "id", "session", "claims", "deliverables", "verificationRefs", "role",
})

# 首版锁定的导出契约版本；其他版本整体降级 + warning
LOCKED_CONTRACT_VERSIONS = frozenset({"v2"})

SOURCE_KINDS = ("dsh-zip", "dsh-jsonl", "dsh-markdown", "generic-markdown")
SOURCE_MODES = ("full", "text")

METRIC_KEYS = ("duration_ms", "tokens", "cost")


def norm_status(value):
    """状态原文归一：仅小写去空白，不做语义猜测。"""
    return str(value).strip().lower()


def make_ref(scope_prefix, line, json_path=""):
    """确定性生成 source_ref。
    JSONL 记录： s<序号>/L<行号>/j<JSON 路径>
    ZIP 成员内： s<序号>@<成员名>/L<行号>/j<JSON 路径>
    Markdown：   s<序号>/h<层级>:<标题锚>/L<行号>（scope_prefix 直接传入整段）
    """
    if json_path:
        return "{}/L{}/j/{}".format(scope_prefix, line, json_path)
    return "{}/L{}".format(scope_prefix, line)


def make_anchor_id(ref):
    """HTML 锚点 id = sha1(source_ref)[:10]，可重复构建且全页唯一。"""
    return hashlib.sha1(ref.encode("utf-8")).hexdigest()[:10]


def is_completion_claim(text):
    """确定性判断一句话是否主张了完成 / 成功（受控标记词，无语义推理）。"""
    low = str(text).lower()
    return any(marker in low for marker in CLAIM_MARKERS)


def decide_evidence(claim, records):
    """五级证据判定（单遍规则，首中即止）。

    参数：
      claim:   {"text": str} 助手主张原文
      records: 同窗口事件列表，元素 {"etype": ..., "status": ...}；
               etype 取 "check" | "tool_result" | "tool_call"
    返回：
      {"level": 五级之一, "verification": "verified|failed|unverified",
       "warnings": [str, ...]}

    规则（设计蓝图 4）：
      1. 验证记录存在明确失败 → failed
      2. 验证记录存在明确通过（且无失败）→ external-verification
      3. 无验证记录但有工具调用 → tool-evidence（页面注「未复验」）
      4. 无验证无工具但主张完成 → unverified
      5. 仅为描述性自述 → self-report
    状态词表外的值：不计入通过 / 失败，降档处理并出 warning。
    """
    text = str(claim.get("text", ""))
    warnings = []
    statuses = []
    has_tools = False
    for rec in records or []:
        etype = rec.get("etype")
        if etype == "tool_call":
            has_tools = True
        if etype in ("check", "tool_result"):
            status = rec.get("status")
            if status is not None and str(status).strip() != "":
                statuses.append(str(status))
    fails = [s for s in statuses if norm_status(s) in FAIL_WORDS]
    passes = [s for s in statuses if norm_status(s) in PASS_WORDS]
    unknown = [s for s in statuses
               if norm_status(s) not in PASS_WORDS and norm_status(s) not in FAIL_WORDS]
    if unknown:
        warnings.append("检查状态词表外值（降档处理）: " + ", ".join(sorted(set(unknown))))
    if fails:
        level = "failed"
    elif passes:
        level = "external-verification"
    elif has_tools:
        level = "tool-evidence"
    elif is_completion_claim(text):
        level = "unverified"
    else:
        level = "self-report"
    if level == "failed":
        verification = "failed"
    elif level == "external-verification":
        verification = "verified"
    else:
        verification = "unverified"
    return {"level": level, "verification": verification, "warnings": warnings}


def automation_cap(level):
    """Automation / Schedule 证据封顶：永不高于 tool-evidence。
    「已投递」不因别处存在执行或验收记录而升级。"""
    if level == "external-verification":
        return "tool-evidence"
    return level


VERIFICATION_LABELS = {
    "verified": "已复验",
    "failed": "验证失败",
    "unverified": "未验证",
}

EVIDENCE_LABELS = {
    "self-report": "Agent 自报",
    "tool-evidence": "工具证据（未复验）",
    "external-verification": "外部复验",
    "unverified": "未验证",
    "failed": "验证失败",
}
