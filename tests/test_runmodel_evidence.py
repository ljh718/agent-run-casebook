#!/usr/bin/env python3
"""test_runmodel_evidence.py — 五级证据判定矩阵与 Automation 封顶（独立覆盖）。"""

import unittest

import runmodel as rm


def decide(text, statuses, tools=False):
    records = [{"etype": "tool_call"}] * (1 if tools else 0)
    records += [{"etype": "check", "status": s} for s in statuses]
    return rm.decide_evidence({"text": text}, records)


class TestEvidenceMatrix(unittest.TestCase):
    def test_fail_beats_everything(self):
        got = decide("已修复该问题", ["pass", "fail"])
        self.assertEqual(got["level"], "failed")
        self.assertEqual(got["verification"], "failed")

    def test_pass_means_external_verification(self):
        got = decide("已修复该问题", ["pass"])
        self.assertEqual(got["level"], "external-verification")
        self.assertEqual(got["verification"], "verified")

    def test_tools_only_means_tool_evidence(self):
        got = decide("已修复该问题", [], tools=True)
        self.assertEqual(got["level"], "tool-evidence")
        self.assertEqual(got["verification"], "unverified")

    def test_completion_without_records_means_unverified(self):
        got = decide("已完成全部整理", [])
        self.assertEqual(got["level"], "unverified")

    def test_descriptive_means_self_report(self):
        got = decide("分析了现有实现的分层结构", [])
        self.assertEqual(got["level"], "self-report")
        self.assertEqual(got["verification"], "unverified")

    def test_chinese_status_words(self):
        self.assertEqual(decide("已修复", ["通过"])["level"], "external-verification")
        self.assertEqual(decide("已修复", ["失败"])["level"], "failed")

    def test_unknown_status_degrades_with_warning(self):
        got = decide("已修复该问题", ["yellow"])
        self.assertIn(got["level"], ("unverified", "tool-evidence"))
        self.assertTrue(got["warnings"])

    def test_unknown_plus_pass_still_verified(self):
        got = decide("已修复该问题", ["yellow", "pass"])
        self.assertEqual(got["level"], "external-verification")
        self.assertTrue(got["warnings"])

    def test_mixed_pass_fail_prefers_failed(self):
        self.assertEqual(decide("已修复", ["ok", "error"])["level"], "failed")

    def test_tool_result_status_counts_as_verification(self):
        got = rm.decide_evidence({"text": "已修复该问题"},
                                 [{"etype": "tool_result", "status": "fail"}])
        self.assertEqual(got["level"], "failed")

    def test_tool_call_alone_is_not_verification(self):
        got = rm.decide_evidence({"text": "已修复该问题"},
                                 [{"etype": "tool_call", "status": "pass"}])
        # tool_call 不属于验证记录：只构成工具证据
        self.assertEqual(got["level"], "tool-evidence")

    def test_empty_status_ignored(self):
        got = decide("已修复该问题", ["", "  "])
        self.assertEqual(got["level"], "unverified")


class TestAutomationCap(unittest.TestCase):
    def test_cap_never_above_tool_evidence(self):
        self.assertEqual(rm.automation_cap("external-verification"), "tool-evidence")
        self.assertEqual(rm.automation_cap("tool-evidence"), "tool-evidence")

    def test_cap_keeps_lower_levels(self):
        self.assertEqual(rm.automation_cap("self-report"), "self-report")

    def test_label_fixed_in_schema_level(self):
        # Automation 条目的页面语义由渲染层固定为「已投递」；
        # 这里验证证据词表与等级常量完整。
        self.assertEqual(set(rm.EVIDENCE_LEVELS),
                         {"self-report", "tool-evidence", "external-verification",
                          "unverified", "failed"})


class TestMarkerVocab(unittest.TestCase):
    def test_completion_markers(self):
        for text in ("任务已完成。", "回归通过。", "已修复该问题", "build succeeded"):
            self.assertTrue(rm.is_completion_claim(text))

    def test_descriptive_not_marker(self):
        for text in ("分析了目录结构。", "先复现问题。", "稍后继续。"):
            self.assertFalse(rm.is_completion_claim(text))


if __name__ == "__main__":
    unittest.main()
