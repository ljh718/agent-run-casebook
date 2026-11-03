#!/usr/bin/env python3
"""tests/_helpers.py — 测试公共助手：scripts 目录入 sys.path、合成 run 模型、fixtures 路径。"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

FIXTURES = TESTS_DIR / "fixtures"


def fixture(*parts):
    return FIXTURES.joinpath(*parts)


def make_run():
    """最小合法 run 模型（通过 validate_schema / validate_references）。"""
    return {
        "schema_version": "1.0.0",
        "generator": {"name": "agent-run-casebook", "version": "1.0.0"},
        "source": {"kind": "dsh-jsonl", "mode": "full",
                   "inputs": [{"ordinal": 1, "name": "demo.jsonl", "record_count": 3}],
                   "contract_version": "v2", "degradations": []},
        "task": {"goal": "演示任务", "started_at": "2026-03-01T10:00:00",
                 "ended_at": "2026-03-01T10:06:00"},
        "steps": [{"id": "step-1", "title": "改动", "source_ref": "s1/L2/j/type",
                   "tool_call_ids": ["tc-1"], "ts": "2026-03-01T10:02:00",
                   "unknown_fields": []}],
        "tool_calls": [{"id": "tc-1", "name": "edit", "call_id": "call-1", "status": "ok",
                        "ts": "2026-03-01T10:02:10", "duration_ms": 120,
                        "source_ref": "s1/L3/j/callId"}],
        "deliverables": [{"id": "d-1", "path": "src/parser.py", "kind": "file",
                          "source_ref": "s1/L9/j/type",
                          "evidence": {"level": "tool-evidence", "verification": "unverified"}}],
        "claims": [{"id": "c-1", "text": "已修复 parser.py，回归通过。",
                    "source_ref": "s1/L4/j/type", "claim_origin": "marker",
                    "evidence_level": "external-verification", "verification": "verified",
                    "verification_refs": ["tc-1"]}],
        "automation": [{"id": "a-1", "kind": "automation", "label": "已投递",
                        "delivered_at": None, "source_ref": "s1/L10/j/type",
                        "evidence": {"level": "tool-evidence", "verification": "unverified"}}],
        "metrics": {"duration_ms": 360000},
        "narrative": None,
        "narrative_check": {"passed": False, "violations": [], "reason": "no-narrative"},
        "warnings": [],
        "redaction": {"applied": [], "residual_scan": "passed"},
    }


GOOD_NARRATIVE = {
    "title": "解析回归修复复盘",
    "summary": "本轮围绕 parser.py 完成修复并复跑回归，全部关键节点可回溯。",
    "key_nodes": [{"ref": "step-1", "heading": "修改解析器",
                   "blurb": "编辑 parser.py 并复跑回归"}],
    "reader_notes": ["点击来源锚点可回溯原文"],
}
