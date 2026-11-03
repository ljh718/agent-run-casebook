#!/usr/bin/env python3
r"""redact.py — 全树脱敏规则引擎与残留扫描硬门（两套独立机制）。

固定顺序（设计蓝图 7，先结构后内容，路径类最后）：
  1. 结构排除（system/developer、隐藏推理）在 normalize 层从源头不存在
  2. 结构化字段：已知敏感键的值 → [REDACTED:R-STRUCT]
  3. 模式规则：密钥 / Bearer / JWT / URL 凭据 / 连接串 / URL 分级 / Cookie
  4. PII 规则：私钥块 / 身份证 / 手机号 / 银行卡 / IPv4 / 邮箱 / 自然语言明文凭据
  5. 路径规则：Windows 盘符绝对路径（含中文段）与 POSIX 用户目录 → [PATH]
  6. 全树应用：run / narrative / HTML / MD 同一规则表跑同一遍
  7. 残留扫描（硬门，两套独立机制，见下）→ 任一命中即 ResidualLeakError，不落盘

URL 分级（v1.1.0，替代旧 R-URL 无差别全抹）：
  default    保留 host+path 作为引用出处，抹 query（R-URL-QUERY），
             内网域名整体抹除（R-URL-INTERNAL）
  no-urls    旧行为：所有 http(s) URL 全抹（R-URL）
  keep-urls  只保留 R-URLCRED 凭据兜底，其余 URL 原样保留

残留扫描两套机制（v1.1.0，修复「检测集与替换集同源」盲区）：
  A. 规则复检：把生效规则表在最终文本上重跑一遍——各规则/负向集带占位符守卫
     （(?!\[REDACTED)），占位符自身不会被再命中，命中即代表替换未生效。
  B. 独立宽形态探测 RESIDUAL_SUSPICIOUS：与替换集刻意不同源、更宽，
     只查不改，命中即拒绝产出（fail-closed），让使用者清洗输入。
     默认 --strict-pii 开启；--no-strict-pii 时跳过 B，仅记 PII_SUSPECTED
     警告（含 JSON 路径 source_ref）放行，由使用者自行承担复核责任。
  另有独立负向集 RESIDUAL_NEGATIVE：file:// 仍绝对禁止；
  http(s) 的 userinfo 凭据形态仍绝对禁止（普通外链自 v1.1.0 起放行）。

灰区说明：模式规则可能误伤演示文本——脚本只做确定性替换并按实际替换次数计数
（v1.1.0 P2-6），命中明细进 redaction.applied / redaction.details 供人复核，
语义裁决归 QA 与用户。自定义 denylist（--denylist，P2-3）词条先于模式规则
以普通字符串替换应用，占位符分段受保护保证幂等；原文片段只进
redaction-report.txt（本地审计用，不可分享），run.json 不含原文。
已知残余风险（有意保留，不做自动特判）：
  - R-BANKCARD 为形态粗筛，可能误伤 16-19 位长订单号 / 哈希前缀；
  - R-IPV4 会命中 127.0.0.1 / 0.0.0.0（无识别性，保留规则简单）；
  - R-CN-MOBILE 会命中 1 开头的 11 位纯数字流水号（脱敏偏向「多脱」）。
"""

import re

try:
    from . import runmodel as rm
except ImportError:
    import runmodel as rm


class ResidualLeakError(Exception):
    """残留扫描命中：最终产物不落盘。"""

    def __init__(self, hits):
        self.hits = list(hits)
        super().__init__("残留扫描命中 {} 处: {}".format(len(self.hits), ", ".join(self.hits[:10])))


# ── 模式规则表（按序应用；占位符本身不被任何规则再命中，保证幂等） ──
_RULE_SPECS = [
    ("R-KEY-OPENAI", r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{16,}", "[REDACTED:R-KEY-OPENAI]"),
    ("R-KEY-AWS", r"AKIA[0-9A-Z]{16}", "[REDACTED:R-KEY-AWS]"),
    ("R-KEY-GITHUB", r"gh[pousr]_[A-Za-z0-9]{20,}", "[REDACTED:R-KEY-GITHUB]"),
    ("R-KEY-SLACK", r"xox[baprs]-[A-Za-z0-9-]{10,}", "[REDACTED:R-KEY-SLACK]"),
    ("R-JWT", r"eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}", "[REDACTED:R-JWT]"),
    ("R-BEARER", r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", "[REDACTED:R-BEARER]"),
    ("R-URLCRED", r"([A-Za-z][A-Za-z0-9+.\-]{1,20})://(?!\[REDACTED)[^\s/@:]+:[^\s/@]+@",
     r"\g<1>://[REDACTED:R-URLCRED]@"),
    ("R-CONN", r"(?i)\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqps?|mssql)://[^\s'\"<>]+",
     "[REDACTED:R-CONN]"),
    # ── URL 分级规则（v1.1.0）：default 档启用 INTERNAL + QUERY；no-urls 档启用 R-URL；
    #    keep-urls 档三者全不启用，仅靠 R-URLCRED 兜底凭据。不带 \b：可命中 xhttps:// 混淆形态。
    ("R-URL-INTERNAL",
     r"(?i)https?://(?:[a-z0-9-]+\.)*(?:corp|internal|intra|local|lan|office)"
     r"(?:\.[a-z0-9-]+)*(?:[/?]|(?=[^\w.\-]|$))[^\s'\"<>]*",
     "[REDACTED:R-URL-INTERNAL]"),
    ("R-URL-QUERY",
     r"(?i)(https?://[^\s?\#'\"<>]+)\?(?!\[REDACTED)[^\s'\"<>]+",
     r"\1?[REDACTED:R-URL-QUERY]"),
    # R-URL 带占位符守卫（F-2）：不匹配 "https://[REDACTED:…]@" 残体形态；
    # 该残体在 --no-urls 档由紧随其后的 R-URL-CREDREST 整体抹除（保持「全抹」语义），
    # default / keep-urls 档两者均不生效，cred URL 保留 "[SCHEME]://[REDACTED:R-URLCRED]@host/path"。
    # 复检假阳性根因（审计明细 replacement 文本进入扫描）由 _AUDIT_SCHEME_RE scheme 掩码兜底。
    ("R-URL", r"(?i)https?://(?!\[REDACTED)[^\s'\"<>]+", "[REDACTED:R-URL]"),
    ("R-URL-CREDREST", r"(?i)https?://\[REDACTED:R-URLCRED\]@[^\s'\"<>]+",
     "[REDACTED:R-URL]"),
    ("R-FILEURI", r"(?i)\bfile://[^\s'\"<>]+", "[REDACTED:R-FILEURI]"),
    ("R-COOKIE", r"(?i)\b(set-)?cookie\s*[:=]\s*[^\r\n]{4,}", "[REDACTED:R-COOKIE]"),
    # ── PII 规则（v1.1.0）：默认开启；均为确定性替换，命中数进 redaction.applied 供人复核。
    # 顺序：私钥 → 身份证 → 手机号 → 银行卡 → IP → 邮箱 → 自然语言明文凭据。
    # 必须位于 R-URLCRED/R-URL 分级规则之后（否则 EMAIL 会吃掉 URL 凭据片段）、
    # 路径规则之前（路径里的用户名由 R-WINPATH 处理）。
    ("R-PRIVKEY",
     r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
     "[REDACTED:R-PRIVKEY]"),
    ("R-CN-ID",
     r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
     "[REDACTED:R-CN-ID]"),
    ("R-CN-MOBILE",
     r"(?<![\d-])(?:\+?86[\s-]?)?1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}(?![\d-])",
     "[REDACTED:R-CN-MOBILE]"),
    ("R-BANKCARD", r"(?<![\d.])\d{16,19}(?![\d.])", "[REDACTED:R-BANKCARD]"),
    ("R-IPV4",
     r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}"
     r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)(?![\d.])",
     "[REDACTED:R-IPV4]"),
    ("R-EMAIL",
     r"(?i)(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",
     "[REDACTED:R-EMAIL]"),
    # 自然语言明文凭据：仅当前缀是「密码/口令/password/pwd」且后接非否定词时替换；
    # 值不能是占位符或以 "=" 开头（分隔符组可省略，防回溯吞掉已替换文本，保证幂等）。
    ("R-INLINE-CRED",
     r"(?i)((?:密码|口令|password|passwd|pwd)\s*(?:是|为|[:：=])?\s*)"
     r"(?!错误|失败|不对|为空|字段|长度|框|提示|记不住|\[REDACTED)(?!=)(\S{4,})",
     r"\1[REDACTED:R-INLINE-CRED]"),
    # 路径类最后：避免路径替换破坏前面模式匹配的锚点。
    # 盘符后反斜杠 / 正斜杠 / 重复斜杠均覆盖（如 C:\a\b 与 C://a//b 变体）；
    # 中间段允许空格（如 Program Files），末段不含空格以免吞掉路径后的正文。
    ("R-WINPATH",
     r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+(?:[^\\/:*?\"<>|\r\n]+[\\/]+)*(?:[^\\/:*?\"<>|\r\n ]*)",
     "[PATH]"),
    ("R-POSIXPATH", r"/(?:home|Users)/[^\s/]+(?:/[^\s'\"]*)?", "[PATH]"),
    ("R-ROOTPATH", r"/root/(?:[^\s'\"]*)?", "[PATH]"),
]

REDACTION_RULES = [(rid, re.compile(pat), repl) for rid, pat, repl in _RULE_SPECS]

# URL 分级：各档位下不参与替换与复检的规则 id
_URL_RULE_IDS = ("R-URL-INTERNAL", "R-URL-QUERY", "R-URL", "R-URL-CREDREST")
_URL_MODE_SKIP = {
    "default": ("R-URL", "R-URL-CREDREST"),
    "no-urls": ("R-URL-INTERNAL", "R-URL-QUERY"),
    "keep-urls": _URL_RULE_IDS,
}


def active_rules(url_mode="default"):
    """按 URL 档位返回生效规则表（顺序不变）。未知档位按 default 处理。"""
    skip = _URL_MODE_SKIP.get(url_mode, _URL_MODE_SKIP["default"])
    return [rule for rule in REDACTION_RULES if rule[0] not in skip]


# 独立负向集：最终产物中绝不允许出现的形态。
# v1.1.0 起 http(s) 从「绝对禁止」降级为「仅禁止带 userinfo 凭据的形态」，
# 普通外链（host+path）作为引用出处放行；file:// 仍绝对禁止。
# userinfo 形态带 (?!\[REDACTED) 守卫：URLCRED 已替换的 "[REDACTED:R-URLCRED]@" 不算残留。
RESIDUAL_NEGATIVE = [
    ("R-RES-URLCRED", re.compile(r"(?i)https?://(?!\[REDACTED)[^\s/@]*:[^\s/@]*@")),
    ("R-RES-FILEURI", re.compile(r"(?i)file://")),
]

# 独立宽检测集（只查不改）：用于发现「替换集漏掉了什么」。
# 刻意比替换集宽——宁可误报要求人工清洗，不可漏报。与 REDACTION_RULES 不同源。
# R-SUS-URLKEY（F-1 兜底）：query 中高风险键（access_token / token / secret /
# api_key / apikey / session / sid / auth / code，允许 client_secret 等前缀形态）
# 出现在可分享产物即 strict 硬门拦截——含 keep-urls 档（用户显式保留 query 时
# 需自行清洗或降档 --no-strict-pii）。已替换的 "?[REDACTED:R-URL-QUERY]" 不命中。
RESIDUAL_SUSPICIOUS = [
    ("R-SUS-EMAIL", re.compile(r"(?i)[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")),
    ("R-SUS-DIGITS", re.compile(r"(?<!\d)\d{11,}(?!\d)")),        # 手机/身份证/卡号/长单号
    ("R-SUS-IPV4", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
    ("R-SUS-PRIVKEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("R-SUS-CREDWORD",
     re.compile(r"(?i)(?:密码|口令|password|passwd|pwd)\s*(?:是|为|[:：=])\s*(?!\[REDACTED)\S{4,}")),
    ("R-SUS-URLKEY",
     re.compile(r"(?i)[?&][a-z0-9_\-]*(?:access_token|api_key|apikey|session|sid|token|secret|auth|code)=[^\s&'\"<>]+")),
]

# 占位符说明：各规则与负向集均带 (?!\[REDACTED) 类守卫（或结构上不可能命中占位符），
# 因此复检 / 形态探测可直接在含占位符的最终文本上运行，无需剥离。
_PLACEHOLDER_RE = re.compile(r"\[(?:REDACTED:[A-Za-z0-9_\-]+|PATH)\]")

# ── 自定义 denylist（P2-3）与审计明细（P2-6） ───────────────────────
DENYLIST_RULE_ID = "R-DENYLIST"
DENYLIST_PLACEHOLDER = "[REDACTED:R-DENYLIST]"
# 占位符分段切分：奇数下标为占位符（denylist 不得命中占位符自身，保证幂等）
_DENY_SPLIT_RE = re.compile(r"(\[(?:REDACTED:[A-Za-z0-9_\-]+|PATH)\])")
DETAIL_AUDIT_LIMIT = 1000    # 审计明细采集上限（含原文片段，仅进 redaction-report.txt）
DETAIL_RUNJSON_LIMIT = 50    # run.json redaction.details 上限（不含原文片段）


def load_denylist(path):
    """读取 UTF-8 denylist 文件：每行一个词条；空行与 # 注释忽略；去首尾空白。"""
    from pathlib import Path
    terms = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        t = ln.strip()
        if t and not t.startswith("#"):
            terms.append(t)
    return terms


# 审计明细 replacement 的 scheme 掩码（F-2）：details 会写入 run.json 并被残留
# 扫描复检，若 replacement 保留 "https://[REDACTED:...]@" 形态，会在 --no-urls
# 档被 R-URL 自触发造成假阳性；掩码后不再匹配任何规则，审计信息（规则、偏移、
# 占位符）不受影响。原文片段只进 redaction-report.txt（不参与扫描）。
_AUDIT_SCHEME_RE = re.compile(r"(?i)^([a-z][a-z0-9+.\-]{0,20})://")


def _record(audit, source_ref, rule_id, replacement, offset, length, snippet):
    if audit is None or len(audit) >= DETAIL_AUDIT_LIMIT:
        return
    audit.append({"source_ref": source_ref, "rule_id": rule_id,
                  "replacement": _AUDIT_SCHEME_RE.sub("[SCHEME]://", str(replacement)),
                  "offset": offset, "length": length,
                  "snippet": str(snippet)[:80]})


def _apply_denylist(text, terms, counts, audit, source_ref):
    """denylist 词条按长度降序做普通字符串替换（不按 regex 解释）；
    占位符分段受保护——词条永不命中占位符自身，保证幂等。"""
    terms_sorted = sorted({t for t in terms if t}, key=len, reverse=True)
    if not terms_sorted:
        return text
    parts = _DENY_SPLIT_RE.split(text)
    for idx in range(0, len(parts), 2):          # 偶数下标 = 非占位符段
        seg = parts[idx]
        for term in terms_sorted:
            c = seg.count(term)
            if not c:
                continue
            if counts is not None:
                counts[DENYLIST_RULE_ID] = counts.get(DENYLIST_RULE_ID, 0) + c
            pos = 0
            for _ in range(c):
                off = seg.find(term, pos)
                _record(audit, source_ref, DENYLIST_RULE_ID, DENYLIST_PLACEHOLDER,
                        off, len(term), term)
                pos = off + len(term)
            seg = seg.replace(term, DENYLIST_PLACEHOLDER)
        parts[idx] = seg
    return "".join(parts)


def redact_text(text, counts=None, url_mode="default", denylist=(), audit=None,
                source_ref=""):
    """对单条字符串按生效规则表顺序替换。

    counts: 各规则命中计数——P2-6 起按 re.subn 实际替换次数累加。
    denylist: 自定义词条（普通字符串替换，先于模式规则应用）。
    audit: 审计明细输出列表（含原文片段，仅供 redaction-report.txt；
           run.json 的 redaction.details 由调用方剥离 snippet 后写入）。
    source_ref: 明细定位用 JSON 路径（如 $.steps[0].text）。
    """
    def bump(rid, n):
        if counts is not None:
            counts[rid] = counts.get(rid, 0) + n
    out = text
    if denylist:
        out = _apply_denylist(out, denylist, counts, audit, source_ref)
    for rid, rx, repl in active_rules(url_mode):
        def _record_match(m, _rid=rid, _rx=rx, _repl=repl):
            expanded = _rx.subn(_repl, m.group(0))[0]
            _record(audit, source_ref, _rid, expanded, m.start(),
                    len(m.group(0)), m.group(0))
            return expanded
        new, n = rx.subn(_record_match, out)
        if n:
            out = new
            bump(rid, n)
    return out


def redact_tree(obj, counts=None, url_mode="default", denylist=(), audit=None):
    """递归脱敏任意 JSON 树（dict / list / str / 标量）。
    敏感键的值整体替换；其余字符串值走模式规则。返回 (new_obj, counts)。"""
    counts = {} if counts is None else counts

    def walk(o, path):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if isinstance(k, str) and k.lower() in rm.SENSITIVE_STRUCT_KEYS:
                    out[k] = "[REDACTED:R-STRUCT]"
                    counts["R-STRUCT"] = counts.get("R-STRUCT", 0) + 1
                    _record(audit, "{}.{}".format(path, k), "R-STRUCT",
                            "[REDACTED:R-STRUCT]", 0, len(str(v)), v)
                else:
                    out[k] = walk(v, "{}.{}".format(path, k))
            return out
        if isinstance(o, list):
            return [walk(x, "{}[{}]".format(path, i)) for i, x in enumerate(o)]
        if isinstance(o, str):
            return redact_text(o, counts, url_mode, denylist, audit, path)
        return o

    return walk(obj, "$"), counts


def residual_scan_text(text, extra_markers=(), strict_pii=True, url_mode="default",
                       denylist=()):
    """残留扫描（两套独立机制 + 负向集 + denylist 复检 + 预置 marker）。返回命中标识列表。

    A 规则复检：生效规则表在最终文本上重跑——占位符由规则内守卫排除，不算残留。
    B 独立宽形态探测：strict_pii 为 True 时启用，命中即 fail-closed。
    C denylist 复检：任一词条在非占位符文本中出现即命中（占位符分段受保护）。
    """
    hits = []
    for rid, rx, _repl in active_rules(url_mode):
        if rx.search(text):
            hits.append(rid)
    for rid, rx in RESIDUAL_NEGATIVE:
        if rx.search(text):
            hits.append(rid)
    if denylist:
        clean = "".join(p for i, p in enumerate(_DENY_SPLIT_RE.split(text)) if i % 2 == 0)
        for term in {t for t in denylist if t}:
            if term in clean:
                hits.append(DENYLIST_RULE_ID)
                break
    if strict_pii:
        for rid, rx in RESIDUAL_SUSPICIOUS:
            if rx.search(text):
                hits.append(rid)
    for marker in extra_markers or ():
        if marker and marker in text:
            hits.append("MARKER:{}".format(marker))
    return hits


def residual_scan_bytes(data, extra_markers=(), strict_pii=True, url_mode="default",
                        denylist=()):
    return residual_scan_text(data.decode("utf-8", errors="replace"),
                              extra_markers, strict_pii, url_mode, denylist)


def suspect_scan_tree(obj):
    """对脱敏后树逐字符串叶跑 RESIDUAL_SUSPICIOUS（只查不改，用于定位）。
    返回 [(rule_id, json_path), ...]，路径确定性（$ 根、.key、[i] 下标）。"""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, "{}.{}".format(path, k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, "{}[{}]".format(path, i))
        elif isinstance(o, str):
            for rid, rx in RESIDUAL_SUSPICIOUS:
                if rx.search(o):
                    out.append((rid, path))

    walk(obj, "$")
    return out
