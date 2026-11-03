#!/usr/bin/env python3
"""test_dsh_envelope.py — DSH 官方信封事件格式（v2/v4）解析回归。

覆盖：解析计数 > 0（0 条回归）、text 块拼接、tool-call 块与 tool/result 配对、
epoch ms 时间确定性、automation 封顶、system 排除计数、未知事件仅警告不计事件、
version 2/4 已知与 99 降级、重复构建逐字节一致。
样本为人工脱敏信封（tests/fixtures/good/dsh-v4/input.jsonl），无真实 PII。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _helpers
from _helpers import fixture

import normalize as nz
import dsh_events as dsh

DSH_V4 = fixture("good", "dsh-v4", "input.jsonl")
SCRIPTS_DIR = _helpers.SCRIPTS_DIR

# fixture 时间基准（epoch ms，与 input.jsonl 中的字面量一致）
T0 = 1772359200000  # 2026-03-01T10:00:00Z


def _envelope_file(tmpdir, version, tail_type="user/message"):
    """构造最小信封文件：头行 version + 一条 user/message 事件。"""
    p = Path(tmpdir) / "in.jsonl"
    lines = [
        json.dumps({"type": "session", "version": version, "id": "session-x",
                    "createdAt": T0}),
        json.dumps({"type": tail_type, "seq": 2, "time": T0 + 1000,
                    "data": {"content": [{"type": "text", "text": "演示任务"}],
                             "role": "user", "id": "u-1",
                             "source": {"kind": "user"}}}),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestDshV4Fixture(unittest.TestCase):
    """端到端：脱敏信封样本经完整归一化管线的结果。"""

    @classmethod
    def setUpClass(cls):
        cls.model, cls.report = nz.parse_input(DSH_V4)

    def test_parse_counts_not_zero(self):
        """0 条回归：信封格式必须解析出有效记录。"""
        self.assertGreater(self.report["steps"], 0)
        self.assertEqual(self.report["steps"], 4)
        self.assertEqual(self.report["tool_calls"], 3)
        self.assertGreater(self.report["claims"], 0)
        # tool-call 块与独立 tool/call 事件指向同一次调用 → 去重后不虚增
        call_ids = [tc["call_id"] for tc in self.model["tool_calls"]]
        self.assertEqual(len(call_ids), len(set(call_ids)))
        for step in self.model["steps"]:
            self.assertEqual(len(step["tool_call_ids"]), len(set(step["tool_call_ids"])))

    def test_text_blocks_concatenated_in_order(self):
        goal = self.model["task"]["goal"]
        self.assertEqual(goal, "修复 parser.py 的日期解析回归。\n配置见附件。")

    def test_session_title_captured(self):
        self.assertEqual(self.model["task"]["title"], "解析回归修复案例（演示）")

    def test_tool_block_and_result_pairing(self):
        statuses = [tc["status"] for tc in self.model["tool_calls"]]
        self.assertEqual(statuses, ["ok", "fail", "ok"])
        levels = [c["evidence_level"] for c in self.model["claims"]]
        self.assertIn("failed", levels)
        self.assertIn("external-verification", levels)

    def test_usage_tokens_recorded_no_cost(self):
        # 120 + 45（cacheReadTokens 不计）+ 100 + 30 = 295；无 cost 不估算
        self.assertEqual(self.model["metrics"].get("tokens"), 295)
        self.assertNotIn("cost", self.model["metrics"])

    def test_epoch_ms_time_deterministic_utc(self):
        self.assertEqual(self.model["task"]["started_at"], "2026-03-01T10:00:00+00:00")
        delivered = [a["delivered_at"] for a in self.model["automation"]]
        self.assertIn("2026-03-01T10:05:00.123000+00:00", delivered)

    def test_automation_delivered_capped(self):
        self.assertEqual(len(self.model["automation"]), 3)
        for item in self.model["automation"]:
            self.assertEqual(item["label"], "已投递")
            self.assertEqual(item["kind"], "automation")
            self.assertEqual(item["evidence"]["level"], "tool-evidence")
            self.assertEqual(item["evidence"]["verification"], "unverified")

    def test_system_message_excluded(self):
        self.assertIn({"code": "SYSTEM_RECORD", "count": 1},
                      self.model["source"]["exclusions"])
        blob = json.dumps(self.model, ensure_ascii=False)
        self.assertNotIn("SYSTEM-DEMO-CONTENT-XYZ", blob)

    def test_unknown_event_warning_only(self):
        codes = [w["code"] for w in self.model["warnings"]]
        self.assertIn("UNKNOWN_FIELD", codes)
        blob = json.dumps(self.model, ensure_ascii=False)
        # 未知事件不生成 user/assistant/claim 事件，data 值不进入运行模型
        # （事件类型名只出现在 UNKNOWN_FIELD 警告 detail 中，用于溯源）
        self.assertNotIn('"beat"', blob)
        # 但仍计入有效记录：未知事件存在时不会 0 条误报
        unknown = [w for w in self.model["warnings"]
                   if w["code"] == "UNKNOWN_FIELD"]
        self.assertTrue(any(w["source_ref"].startswith("s1/L14") for w in unknown))

    def test_contract_version_v4_locked(self):
        self.assertEqual(self.model["source"]["contract_version"], "v4")
        codes = [w["code"] for w in self.model["warnings"]]
        self.assertNotIn("CONTRACT_VERSION_MISMATCH", codes)

    def test_deliverable_from_file_block(self):
        paths = [d["path"] for d in self.model["deliverables"]]
        self.assertIn("config-demo.ini", paths)


class TestEnvelopeHeadVersion(unittest.TestCase):
    def test_version_2_and_4_known(self):
        for version, want in ((2, "v2"), (4, "v4")):
            with tempfile.TemporaryDirectory() as td:
                run, _ = nz.parse_input(_envelope_file(td, version))
            self.assertEqual(run["source"]["contract_version"], want)

    def test_version_99_degrades_to_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            run, _ = nz.parse_input(_envelope_file(td, 99))
        self.assertEqual(run["source"]["contract_version"], "unknown")
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("CONTRACT_VERSION_MISMATCH", codes)

    def test_head_capture_unit(self):
        state = {}
        dsh.capture_head({"type": "session", "version": 4}, state)
        self.assertEqual(state["envelope_version"], "v4")
        dsh.capture_head({"type": "session", "version": 2}, state)
        self.assertEqual(state["envelope_version"], "v2")

    def test_epoch_ms_to_dt(self):
        from datetime import datetime, timezone
        self.assertEqual(dsh.epoch_ms_to_dt(T0),
                         datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(dsh.epoch_ms_to_dt(T0 + 1),
                         datetime(2026, 3, 1, 10, 0, 0, 1000, tzinfo=timezone.utc))
        self.assertIsNone(dsh.epoch_ms_to_dt(None))
        self.assertIsNone(dsh.epoch_ms_to_dt("not-a-number"))
        self.assertIsNone(dsh.epoch_ms_to_dt(-5))

    def test_unknown_type_falls_to_warning_branch(self):
        """合成格式外的信封未知类型 → 警告 + unknown 事件（计入有效记录）。"""
        with tempfile.TemporaryDirectory() as td:
            run, _ = nz.parse_input(_envelope_file(td, 4, tail_type="weird/thing"))
        codes = [w["code"] for w in run["warnings"]]
        self.assertIn("UNKNOWN_FIELD", codes)
        self.assertEqual(run["steps"], [])


DSH_V4_REALFORM = fixture("good", "dsh-v4-realform", "input.jsonl")


class TestDshV4RealForm(unittest.TestCase):
    """真实 v4 形态：assistant tool-call 块不带 callId（实测 0/22 带）。

    回归背景：无合并时每次调用产出两条 tool_call（块副本 call_id=None），
    三例真实会话统计精确翻倍（16/8、44/22、68/34），且 call_id_to_id[None]
    被副本覆盖导致多步骤错误引用同一幽灵条目。"""

    @classmethod
    def setUpClass(cls):
        cls.model, cls.report = nz.parse_input(DSH_V4_REALFORM)

    def test_no_double_counting(self):
        """块与同名 tool/call 事件合并：带 callId 的 tool_call 数 == 事件数。"""
        call_ids = [tc["call_id"] for tc in self.model["tool_calls"]]
        self.assertEqual(call_ids, ["call-r1", "call-r2", "call-r3", None])
        statuses = [tc["status"] for tc in self.model["tool_calls"]]
        self.assertEqual(statuses, ["ok", "fail", "ok", None])
        # 合并不出 TOOL_CALL_DUPLICATE；未匹配 pending 块出 UNMERGED 警告
        codes = [w["code"] for w in self.model["warnings"]]
        self.assertNotIn("TOOL_CALL_DUPLICATE", codes)
        self.assertEqual(codes.count("UNMERGED_TOOL_CALL_BLOCK"), 1)
        self.assertEqual(self.model["source"]["contract_version"], "v4")

    def test_step_tool_refs_correctly_distributed(self):
        """步骤-工具引用按真实调用分布，无幽灵共享。"""
        refs = [s["tool_call_ids"] for s in self.model["steps"]]
        self.assertEqual(refs, [["tc-1"], ["tc-2"], ["tc-3"], [], []])

    def test_claim_evidence_levels(self):
        levels = [c["evidence_level"] for c in self.model["claims"]]
        self.assertIn("failed", levels)
        self.assertIn("external-verification", levels)
        # 未匹配 pending 块按确定性归属规则计入最近主张的工具证据
        self.assertIn("tool-evidence", levels)

    def test_merge_only_touches_flagged_events(self):
        """合成格式 / Markdown 的无 callId tool_call 不受合并影响。"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.jsonl"
            p.write_text(
                json.dumps({"type": "user", "text": "整理数据",
                            "ts": "2026-03-01T10:00:00"}, ensure_ascii=False) + "\n"
                + json.dumps({"type": "tool", "callId": "c-1", "name": "summarize",
                              "ts": "2026-03-01T10:02:00"}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            run, _ = nz.parse_input(p)
        self.assertEqual(len(run["tool_calls"]), 1)
        self.assertEqual(run["tool_calls"][0]["call_id"], "c-1")

    def test_merge_unit_first_same_name_wins(self):
        dsh_a = [{"etype": "tool_call", "ref": "s1/L1/j/x", "name": "edit",
                  "call_id": None, "_dsh_block_no_callid": True},
                 {"etype": "tool_call", "ref": "s1/L2/j/x", "name": "edit",
                  "call_id": None, "_dsh_block_no_callid": True},
                 {"etype": "tool_call", "ref": "s1/L3/j/x", "name": "edit",
                  "call_id": "c1"},
                 {"etype": "tool_call", "ref": "s1/L4/j/x", "name": "edit",
                  "call_id": "c2"}]
        warnings = []
        dsh.merge_pending_tool_blocks(dsh_a, warnings)
        self.assertEqual(len(dsh_a), 2)
        self.assertEqual([e["call_id"] for e in dsh_a], ["c1", "c2"])
        self.assertEqual(warnings, [])

    def test_merge_unit_unresolved_warns(self):
        evs = [{"etype": "tool_call", "ref": "s1/L1/j/x", "name": "probe",
                "call_id": None, "_dsh_block_no_callid": True}]
        warnings = []
        dsh.merge_pending_tool_blocks(evs, warnings)
        self.assertEqual(len(evs), 1)
        self.assertEqual(warnings[0]["code"], "UNMERGED_TOOL_CALL_BLOCK")

    def test_realform_fixture_cli_products(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "out"
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "casebook.py"), "all",
                 str(DSH_V4_REALFORM), "--out", str(outdir)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            for name in ("casebook.html", "casebook.md", "run.json",
                         "redaction-report.txt"):
                self.assertTrue((outdir / name).is_file(), name)


class TestRebuildByteIdentical(unittest.TestCase):
    def test_model_level_identical(self):
        dump = lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True)
        run1, _ = nz.parse_input(DSH_V4)
        run2, _ = nz.parse_input(DSH_V4)
        self.assertEqual(dump(run1), dump(run2))

    def test_cli_products_identical(self):
        def build(outdir):
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "casebook.py"), "all",
                 str(DSH_V4), "--out", outdir],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return {name: (Path(outdir) / name).read_bytes()
                    for name in ("casebook.html", "casebook.md", "run.json")}

        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            first = build(td1)
            second = build(td2)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
