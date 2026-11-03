#!/usr/bin/env python3
"""test_normalize.py — 输入嗅探、callId 配对、source_ref 稳定性、未知字段、坏行降级。"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import _helpers
from _helpers import fixture

import normalize as nz
import runmodel as rm


class TestDetectInput(unittest.TestCase):
    def test_jsonl(self):
        self.assertEqual(nz.detect_input(fixture("good", "bugfix", "input.jsonl")), "dsh-jsonl")

    def test_dsh_markdown(self):
        self.assertEqual(nz.detect_input(fixture("good", "research", "input.md")), "dsh-markdown")

    def test_generic_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.md"
            p.write_text("# 标题\n\n正文段落，没有用户助手结构。\n", encoding="utf-8")
            self.assertEqual(nz.detect_input(p), "generic-markdown")

    def test_zip_magic(self):
        self.assertEqual(nz.detect_input(fixture("good", "data", "export.zip")), "dsh-zip")

    def test_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "junk.txt"
            p.write_text("not json not markdown\n", encoding="utf-8")
            with self.assertRaises(nz.UnrecognizedInputError):
                nz.detect_input(p)

    def test_empty(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            with self.assertRaises(nz.UnrecognizedInputError):
                nz.detect_input(p)

    def test_missing(self):
        with self.assertRaises(nz.UnrecognizedInputError):
            nz.detect_input(Path("no-such-file.jsonl"))


class TestBugfixFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_model, cls.report = nz.parse_input(fixture("good", "bugfix", "input.jsonl"))

    def test_kind_and_mode(self):
        self.assertEqual(self.run_model["source"]["kind"], "dsh-jsonl")
        self.assertEqual(self.run_model["source"]["mode"], "full")

    def test_tool_calls_paired(self):
        self.assertEqual(len(self.run_model["tool_calls"]), 3)
        statuses = [tc["status"] for tc in self.run_model["tool_calls"]]
        self.assertEqual(statuses, ["ok", "ok", "ok"])
        self.assertTrue(all(tc["duration_ms"] is not None for tc in self.run_model["tool_calls"]))

    def test_claim_evidence_evolution(self):
        levels = [c["evidence_level"] for c in self.run_model["claims"]]
        self.assertIn("failed", levels)
        self.assertIn("external-verification", levels)
        self.assertEqual(levels[-1], "external-verification")

    def test_deliverables_and_metrics(self):
        paths = [d["path"] for d in self.run_model["deliverables"]]
        self.assertIn("src/parser.py", paths)
        self.assertIn("duration_ms", self.run_model["metrics"])

    def test_source_ref_stability(self):
        run2, _ = nz.parse_input(fixture("good", "bugfix", "input.jsonl"))
        refs1 = [c["source_ref"] for c in self.run_model["claims"]]
        refs2 = [c["source_ref"] for c in run2["claims"]]
        self.assertEqual(refs1, refs2)
        self.assertTrue(all(r.startswith("s1/L") and "/j/" in r for r in refs1))

    def test_anchor_id_deterministic(self):
        ref = self.run_model["claims"][0]["source_ref"]
        self.assertEqual(rm.make_anchor_id(ref), rm.make_anchor_id(ref))
        self.assertEqual(len(rm.make_anchor_id(ref)), 10)

    def test_sensitive_redaction_ready(self):
        # 敏感串在原始模型中保留（归一化不丢事实），由 redact 层处理
        blob = json.dumps(self.run_model, ensure_ascii=False)
        self.assertIn("sk-testabcdef0123456789ab", blob)


class TestMarkdownTextMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_model, cls.report = nz.parse_input(fixture("good", "research", "input.md"))

    def test_text_mode(self):
        self.assertEqual(self.run_model["source"]["kind"], "dsh-markdown")
        self.assertEqual(self.run_model["source"]["mode"], "text")

    def test_no_metrics(self):
        self.assertEqual(self.run_model["metrics"], {})
        self.assertIsNone(self.run_model["task"]["started_at"])

    def test_deliverable_from_text(self):
        paths = [d["path"] for d in self.run_model["deliverables"]]
        self.assertIn("research-notes.md", paths)

    def test_unverified_claim(self):
        levels = [c["evidence_level"] for c in self.run_model["claims"]]
        self.assertIn("unverified", levels)

    def test_tool_evidence_reachable(self):
        """P1-2：窗口内工具调用使主张可判为 tool-evidence（规则 3 可达）。"""
        levels = [c["evidence_level"] for c in self.run_model["claims"]]
        self.assertIn("tool-evidence", levels)

    def test_markdown_source_ref_shape(self):
        for step in self.run_model["steps"]:
            self.assertRegex(step["source_ref"], r"^s1/h\d:.+/L\d+$")


class TestStructuralExclusion(unittest.TestCase):
    """P1-1 / P2-2：隐藏推理与 system/developer 记录整体排除，只记计数与警告。"""

    def test_system_record_excluded_with_counter(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(
                json.dumps({"type": "system", "text": "SECRET-SYSTEM-CONTENT-XYZ",
                            "ts": "2026-03-01T09:00:00"}, ensure_ascii=False) + "\n"
                + json.dumps({"type": "user", "text": "修复任务", "ts": "2026-03-01T10:00:00"},
                             ensure_ascii=False) + "\n",
                encoding="utf-8")
            run, _ = nz.parse_input(p)
        blob = json.dumps(run, ensure_ascii=False)
        self.assertNotIn("SECRET-SYSTEM-CONTENT-XYZ", blob)
        self.assertIn({"code": "SYSTEM_RECORD", "count": 1}, run["source"]["exclusions"])
        self.assertEqual(run["task"]["goal"], "修复任务")
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("STRUCT_EXCLUDED", codes)

    def test_reasoning_field_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(json.dumps({
                "type": "assistant", "text": "已完成修复。",
                "reasoning": "内部推理草稿-XYZ",
                "ts": "2026-03-01T10:01:00",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            run, _ = nz.parse_input(p)
        blob = json.dumps(run, ensure_ascii=False)
        self.assertNotIn("内部推理草稿-XYZ", blob)
        self.assertIn({"code": "HIDDEN_REASONING", "count": 1}, run["source"]["exclusions"])
        names = [u["name"] for s in run["steps"] for u in s.get("unknown_fields", [])]
        self.assertNotIn("reasoning", names)
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("STRUCT_EXCLUDED", codes)

    def test_exclusions_empty_when_clean(self):
        run, _ = nz.parse_input(fixture("good", "bugfix", "input.jsonl"))
        self.assertEqual(run["source"]["exclusions"], [])


class TestClaimToolWindow(unittest.TestCase):
    def test_claim_with_only_tools_is_tool_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(
                json.dumps({"type": "user", "text": "整理数据", "ts": "2026-03-01T10:00:00"},
                           ensure_ascii=False) + "\n"
                + json.dumps({"type": "assistant", "text": "已完成数据整理。",
                              "ts": "2026-03-01T10:01:00"}, ensure_ascii=False) + "\n"
                + json.dumps({"type": "tool", "callId": "c-1", "name": "summarize",
                              "ts": "2026-03-01T10:02:00"}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            run, _ = nz.parse_input(p)
        self.assertEqual([c["evidence_level"] for c in run["claims"]], ["tool-evidence"])
        self.assertEqual(run["claims"][0]["verification"], "unverified")


class TestUnknownFields(unittest.TestCase):
    def test_unknown_top_level_field(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(json.dumps({
                "type": "user", "text": "任务", "ts": "2026-03-01T10:00:00",
                "customExtension": {"deep": True},
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            run, _ = nz.parse_input(p)
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("UNKNOWN_FIELD", codes)

    def test_collect_unknown_fields(self):
        unknown, warnings = nz.collect_unknown_fields({"type": "user", "newKey": 1}, rm.CONTRACT_KNOWN_KEYS)
        self.assertEqual([u["name"] for u in unknown], ["newKey"])
        self.assertEqual(len(warnings), 1)


class TestContractVersion(unittest.TestCase):
    def test_version_mismatch_degrades(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(json.dumps({
                "type": "user", "text": "任务", "ts": "2026-03-01T10:00:00",
                "schemaVersion": "v9",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            run, _ = nz.parse_input(p)
        self.assertEqual(run["source"]["contract_version"], "unknown")
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("CONTRACT_VERSION_MISMATCH", codes)


class TestBadLines(unittest.TestCase):
    def test_partial_parse_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(
                json.dumps({"type": "user", "text": "任务", "ts": "2026-03-01T10:00:00"},
                           ensure_ascii=False) + "\n"
                + "{broken json line\n",
                encoding="utf-8")
            run, report = nz.parse_input(p)
        self.assertEqual(report["parse_errors"], 1)
        self.assertEqual(run["source"]["degradations"][0]["code"], "PARSE_ERROR")
        self.assertTrue(run["task"]["goal"])

    def test_all_bad_lines_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text("bad1\nbad2\n", encoding="utf-8")
            with self.assertRaises(nz.UnrecognizedInputError):
                nz.parse_input(p)


class TestCrossScopePairing(unittest.TestCase):
    def test_unpaired_tool_call_id_across_members(self):
        """callId 与 toolCallId 分处 ZIP 不同成员（不同文档作用域）→ 不配对并出警告。"""
        with tempfile.TemporaryDirectory() as td:
            zp = Path(td) / "export.zip"
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("a.jsonl", json.dumps({
                    "type": "tool", "callId": "call-x", "name": "edit"}) + "\n")
                zf.writestr("b.jsonl", json.dumps({
                    "type": "tool", "toolCallId": "call-x", "status": "ok"}) + "\n")
            run, _ = nz.parse_input(zp)
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("UNPAIRED_TOOL_CALL", codes)
        # 配对失败的 tool_call 保留原始状态（不被跨作用域结果改写）
        self.assertIsNone(run["tool_calls"][0]["status"])

    def test_zip_partial_records_and_automation(self):
        run, report = nz.parse_input(fixture("good", "data", "export.zip"))
        self.assertEqual(run["source"]["kind"], "dsh-zip")
        self.assertEqual(report["parse_errors"], 1)
        self.assertEqual(run["source"]["degradations"][0]["code"], "PARSE_ERROR")
        self.assertEqual(len(run["automation"]), 1)
        self.assertEqual(run["automation"][0]["label"], "已投递")
        self.assertEqual(run["automation"][0]["evidence"]["level"], "tool-evidence")


if __name__ == "__main__":
    unittest.main()
