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

    def test_bad_claim_origin(self):
        """P2-1：claim_origin 必须为 marker / statement。"""
        run = make_run()
        run["claims"][0]["claim_origin"] = "magic"
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


class TestNarrativeLevelPatterns(unittest.TestCase):
    """P1-1：等级词黑名单升级为正则模式——A 类专名 + B 类验收语境搭配。"""

    BAD = [
        "这条属于外部复验",
        "该主张判为验证失败",
        "仅为工具证据",
        "属于工具证据（未复验）",
        "这条还没验证",
        "测试全部通过",
        "全部 passed",
        "结果为 unverified",
    ]
    GOOD = [
        "通过 ssh 连接到服务器",
        "通过这种方式减少了重复劳动",
        "检查日志后继续排查",
    ]

    def _codes(self, summary):
        narrative = {"title": "标题", "summary": summary,
                     "key_nodes": [{"ref": "step-1", "heading": "h", "blurb": "编辑 parser.py"}],
                     "reader_notes": []}
        return [v["code"] for v in vc.validate_narrative(make_run(), narrative)]

    def test_level_assertions_rejected(self):
        for s in self.BAD:
            self.assertIn("E-NARR-LEVEL", self._codes(s), msg=s)

    def test_normal_pass_phrases_allowed(self):
        for s in self.GOOD:
            self.assertNotIn("E-NARR-LEVEL", self._codes(s), msg=s)


class TestFactUnitTable(unittest.TestCase):
    """P1-2：事实候选单位表扩展 + 汉字数字规则。"""

    def test_new_units_extracted(self):
        self.assertIn("12 分钟", vc._fact_candidates("Agent 用 12 分钟修复了问题"))
        self.assertIn("3.5 美元", vc._fact_candidates("成本约 3.5 美元"))
        self.assertIn("两小时", vc._fact_candidates("耗时两小时"))
        self.assertIn("512 MB", vc._fact_candidates("内存占用 512 MB"))
        self.assertIn("30 秒", vc._fact_candidates("连接超时 30 秒"))
        self.assertIn("12%", vc._fact_candidates("覆盖率提升 12%"))

    def test_non_fact_numbers_ignored(self):
        self.assertEqual(vc._fact_candidates("版本 python 3.11"), [])
        self.assertEqual(vc._fact_candidates("端口 6379"), [])

    def test_fabricated_duration_rejected(self):
        narrative = {"title": "标题", "summary": "Agent 用 12 分钟修复了问题。",
                     "key_nodes": [{"ref": "step-1", "heading": "h", "blurb": "编辑 parser.py"}],
                     "reader_notes": []}
        codes = [v["code"] for v in vc.validate_narrative(make_run(), narrative)]
        self.assertIn("E-NARR-FACT", codes)

    def test_existing_fact_unit_allowed(self):
        run = make_run()
        run["steps"][0]["title"] = "耗时 360000 ms 的修复"
        narrative = {"title": "标题", "summary": "本轮总耗时 360000 ms。",
                     "key_nodes": [{"ref": "step-1", "heading": "修改解析器",
                                    "blurb": "编辑 parser.py 并复跑回归"}],
                     "reader_notes": []}
        self.assertEqual(vc.validate_narrative(run, narrative), [])


if __name__ == "__main__":
    unittest.main()
