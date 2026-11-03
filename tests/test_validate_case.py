#!/usr/bin/env python3
"""test_validate_case.py — schema / 引用 / narrative 白名单五规则逐条。"""

import unittest

from _helpers import make_run, GOOD_NARRATIVE
import validate_case as vc
import redact as rd


def _redacted_run():
    run, _ = rd.redact_tree(make_run())
    return run


class TestSchema(unittest.TestCase):
    def test_valid_run_passes(self):
        self.assertEqual(vc.validate_schema(make_run()), [])
        self.assertEqual(vc.validate_references(make_run()), [])

    def test_missing_top_key(self):
        run = make_run()
        del run["metrics"]
        codes = [v["code"] for v in vc.validate_schema(run)]
        self.assertIn("E-SCHEMA", codes)

    def test_duplicate_ids(self):
        run = make_run()
        run["claims"].append(dict(run["claims"][0]))
        codes = [v["code"] for v in vc.validate_schema(run)]
        self.assertIn("E-SCHEMA", codes)

    def test_bad_evidence_level(self):
        run = make_run()
        run["claims"][0]["evidence_level"] = "verified-magic"
        codes = [v["code"] for v in vc.validate_schema(run)]
        self.assertIn("E-SCHEMA", codes)

    def test_bad_metric_key(self):
        run = make_run()
        run["metrics"]["cost_estimate"] = 1
        codes = [v["code"] for v in vc.validate_schema(run)]
        self.assertIn("E-SCHEMA", codes)

    def test_automation_label_locked(self):
        run = make_run()
        run["automation"][0]["label"] = "已执行"
        codes = [v["code"] for v in vc.validate_schema(run)]
        self.assertIn("E-SCHEMA", codes)

    def test_automation_evidence_cap(self):
        run = make_run()
        run["automation"][0]["evidence"]["level"] = "external-verification"
        codes = [v["code"] for v in vc.validate_schema(run)]
        self.assertIn("E-SCHEMA", codes)


class TestReferences(unittest.TestCase):
    def test_missing_tool_call_ref(self):
        run = make_run()
        run["steps"][0]["tool_call_ids"] = ["tc-404"]
        codes = [v["code"] for v in vc.validate_references(run)]
        self.assertIn("E-REF", codes)

    def test_missing_verification_ref(self):
        run = make_run()
        run["claims"][0]["verification_refs"] = ["tc-404"]
        codes = [v["code"] for v in vc.validate_references(run)]
        self.assertIn("E-REF", codes)

    def test_bad_source_ref_shape(self):
        run = make_run()
        run["claims"][0]["source_ref"] = "随便写的引用"
        codes = [v["code"] for v in vc.validate_references(run)]
        self.assertIn("E-REF", codes)


class TestNarrativeWhitelist(unittest.TestCase):
    def test_good_narrative_passes(self):
        self.assertEqual(vc.validate_narrative(make_run(), GOOD_NARRATIVE), [])

    def test_ref_violation(self):
        narrative = dict(GOOD_NARRATIVE)
        narrative["key_nodes"] = [{"ref": "step-99", "heading": "x", "blurb": "y"}]
        codes = [v["code"] for v in vc.validate_narrative(make_run(), narrative)]
        self.assertIn("E-NARR-REF", codes)

    def test_new_fact_violation(self):
        narrative = {
            "title": "标题",
            "summary": "本轮还生成了 brand-new-report.py 文件。",
            "key_nodes": [{"ref": "step-1", "heading": "h", "blurb": "编辑 parser.py"}],
            "reader_notes": [],
        }
        codes = [v["code"] for v in vc.validate_narrative(make_run(), narrative)]
        self.assertIn("E-NARR-FACT", codes)

    def test_level_word_violation(self):
        narrative = {
            "title": "标题",
            "summary": "全流程已复验。",
            "key_nodes": [{"ref": "step-1", "heading": "h", "blurb": "编辑 parser.py"}],
            "reader_notes": [],
        }
        codes = [v["code"] for v in vc.validate_narrative(make_run(), narrative)]
        self.assertIn("E-NARR-LEVEL", codes)

    def test_size_violation(self):
        narrative = dict(GOOD_NARRATIVE)
        narrative["title"] = "长" * 201
        codes = [v["code"] for v in vc.validate_narrative(make_run(), narrative)]
        self.assertIn("E-NARR-SIZE", codes)

    def test_size_violation_blurb(self):
        narrative = dict(GOOD_NARRATIVE)
        narrative["key_nodes"] = [{"ref": "step-1", "heading": "h", "blurb": "长" * 241}]
        codes = [v["code"] for v in vc.validate_narrative(make_run(), narrative)]
        self.assertIn("E-NARR-SIZE", codes)

    def test_bad_schema_narrative(self):
        codes = [v["code"] for v in vc.validate_narrative(make_run(), {"title": 1})]
        self.assertIn("E-NARR-SCHEMA", codes)

    def test_existing_fact_allowed(self):
        """叙事复述事实集中已有文件与指标 → 放行（只能改表述，不能新增事实）。"""
        narrative = {
            "title": "解析修复复盘",
            "summary": "围绕 parser.py 的修复，总耗时 360000（毫秒），来自 tc-1 的编辑。",
            "key_nodes": [{"ref": "step-1", "heading": "修改解析器",
                           "blurb": "编辑 parser.py 并复跑回归"}],
            "reader_notes": ["工具 edit 的耗时来自源数据"],
        }
        self.assertEqual(vc.validate_narrative(make_run(), narrative), [])


if __name__ == "__main__":
    unittest.main()
