#!/usr/bin/env python3
"""redact.py — 全树脱敏规则引擎与残留扫描硬门。

固定顺序（设计蓝图 7，先结构后内容，路径类最后）：
  1. 结构排除（system/developer、隐藏推理）在 normalize 层从源头不存在
  2. 结构化字段：已知敏感键的值 → [REDACTED:R-STRUCT]
  3. 模式规则：密钥 / Bearer / JWT / URL 内嵌凭据 / 连接串 / 通用 URL / Cookie
  4. 路径规则：Windows 盘符绝对路径（含中文段）与 POSIX 用户目录 → [PATH]
  5. 全树应用：run / narrative / HTML / MD 同一规则表跑同一遍
  6. 残留扫描（硬门）：任一命中 → ResidualLeakError，CLI exit 5，不写出任何产物

灰区说明：模式规则可能误伤演示文本——脚本只做确定性替换并计数，
命中明细进 redaction.applied 供人复核，语义裁决归 QA 与用户。

说明：设计蓝图要求「可相对化时输出工作区相对路径」；脚本无法确知工作区根，
统一以 [PATH] 占位，这是可预测的确定性降级（无猜测）。
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
    ("R-URLCRED", r"([A-Za-z][A-Za-z0-9+.\-]{1,20})://[^\s/@:]+:[^\s/@]+@",
     r"\g<1>://[REDACTED:R-URLCRED]@"),
    ("R-CONN", r"(?i)\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqps?|mssql)://[^\s'\"<>]+",
     "[REDACTED:R-CONN]"),
    ("R-URL", r"(?i)\bhttps?://[^\s'\"<>]+", "[REDACTED:R-URL]"),
    ("R-FILEURI", r"(?i)\bfile://[^\s'\"<>]+", "[REDACTED:R-FILEURI]"),
    ("R-COOKIE", r"(?i)\b(set-)?cookie\s*[:=]\s*[^\r\n]{4,}", "[REDACTED:R-COOKIE]"),
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

# 独立负向集：最终产物中绝不允许出现的外链协议形态
RESIDUAL_NEGATIVE = [
    ("R-RES-HTTP", re.compile(r"(?i)https?://")),
    ("R-RES-FILEURI", re.compile(r"(?i)file://")),
]


def redact_text(text, counts=None):
    """对单条字符串按规则表顺序替换。counts: dict 累计各规则命中次数。"""
    def bump(rid):
        if counts is not None:
            counts[rid] = counts.get(rid, 0) + 1
    out = text
    for rid, rx, repl in REDACTION_RULES:
        new, n = rx.subn(repl, out)
        if n:
            out = new
            bump(rid)
    return out


def redact_tree(obj, counts=None):
    """递归脱敏任意 JSON 树（dict / list / str / 标量）。
    敏感键的值整体替换；其余字符串值走模式规则。返回 (new_obj, counts)。"""
    counts = {} if counts is None else counts

    def walk(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if isinstance(k, str) and k.lower() in rm.SENSITIVE_STRUCT_KEYS:
                    out[k] = "[REDACTED:R-STRUCT]"
                    counts["R-STRUCT"] = counts.get("R-STRUCT", 0) + 1
                else:
                    out[k] = walk(v)
            return out
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, str):
            return redact_text(o, counts)
        return o

    return walk(obj), counts


def residual_scan_text(text, extra_markers=()):
    """对最终产物文本重跑全部规则 + 独立负向集 + 预置 marker。返回命中标识列表。"""
    hits = []
    for rid, rx, _repl in REDACTION_RULES:
        if rx.search(text):
            hits.append(rid)
    for rid, rx in RESIDUAL_NEGATIVE:
        if rx.search(text):
            hits.append(rid)
    for marker in extra_markers or ():
        if marker and marker in text:
            hits.append("MARKER:{}".format(marker))
    return hits


def residual_scan_bytes(data, extra_markers=()):
    return residual_scan_text(data.decode("utf-8", errors="replace"), extra_markers)
