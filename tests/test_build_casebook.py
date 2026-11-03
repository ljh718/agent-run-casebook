#!/usr/bin/env python3
"""test_build_casebook.py — 转义、无 JS/无外链、锚点有效、CSP、原子落盘、重复构建一致。"""

import re
import tempfile
import unittest
from pathlib import Path

import _helpers
from _helpers import fixture, make_run, GOOD_NARRATIVE

import normalize as nz
import redact as rd
import build_casebook as bc
import validate_case as vc


def _pipeline_run(input_path, narrative=None):
    run, _ = nz.parse_input(input_path)
    if narrative is not None:
        violations = vc.validate_narrative(run, narrative)
        assert not violations, violations
        run["narrative"] = narrative
        run["narrative_check"] = {"passed": True, "violations": []}
    redacted, counts = rd.redact_tree(run)
    redacted["redaction"] = {"applied": [{"rule": k, "count": v} for k, v in counts.items()],
                             "residual_scan": "passed"}
    return redacted


class TestEscape(unittest.TestCase):
    def test_script_tag_escaped(self):
        self.assertEqual(bc.esc("<script>alert(1)</script>"),
                         "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_attr_quote_escaped(self):
        self.assertEqual(bc.esc('<img src=x onerror="y">'),
                         "&lt;img src=x onerror=&quot;y&quot;&gt;")

    def test_amp(self):
        self.assertEqual(bc.esc("a&b"), "a&amp;b")


class TestHtmlConstraints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_model = _pipeline_run(fixture("good", "bugfix", "input.jsonl"), GOOD_NARRATIVE)
        cls.html = bc.render_html(cls.run_model)

    def test_no_script_tag(self):
        self.assertNotIn("<script", self.html.lower())

    def test_no_external_protocol(self):
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertNotIn("file://", self.html)
        self.assertNotIn("javascript:", self.html)

    def test_csp_meta_present(self):
        self.assertIn("Content-Security-Policy", self.html)
        self.assertIn("default-src 'none'", self.html)

    def test_details_and_target_used(self):
        self.assertIn("<details", self.html)
        self.assertIn(":target", bc.load_css())

    def test_no_unfilled_slots(self):
        self.assertNotIn("{{", self.html)

    def test_all_anchors_resolve(self):
        hrefs = set(re.findall(r'href="#([^"]+)"', self.html))
        ids = set(re.findall(r'id="([^"]+)"', self.html))
        self.assertTrue(hrefs, "页面应包含来源锚点链接")
        self.assertEqual(hrefs - ids, set(), "存在断链锚点")

    def test_anchor_ids_unique(self):
        ids = re.findall(r'id="([^"]+)"', self.html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_path_variant_redacted(self):
        """P2-1：fixture 预置的盘符正斜杠重复斜杠路径变体不得残留。"""
        self.assertNotIn("C://Users", self.html)
        self.assertNotIn("C:\\Users", self.html)
        self.assertIn("[PATH]", self.html)


class TestHtmlInjectionFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_model = _pipeline_run(fixture("bad", "html-inject.jsonl"))
        cls.html = bc.render_html(cls.run_model)

    def test_script_escaped_visible(self):
        self.assertIn("&lt;script&gt;", self.html)
        self.assertNotIn("<script", self.html.lower())

    def test_onerror_escaped(self):
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", self.html)
        self.assertNotIn("<img", self.html)

    def test_javascript_attr_escaped(self):
        self.assertNotIn('href="javascript:', self.html)


class TestMissingMetricsNotRendered(unittest.TestCase):
    def test_text_mode_hides_metrics(self):
        run_model = _pipeline_run(fixture("good", "research", "input.md"))
        html = bc.render_html(run_model)
        md = bc.render_markdown(run_model)
        self.assertNotIn("总耗时", html)
        self.assertNotIn("Token 用量", html)
        self.assertIn("文本模式", html)
        self.assertIn("文本模式", md)
        self.assertNotIn("总耗时", md)

    def test_full_mode_shows_metrics(self):
        run_model = _pipeline_run(fixture("good", "bugfix", "input.jsonl"))
        html = bc.render_html(run_model)
        self.assertIn("总耗时", html)


class TestRepeatBuildByteIdentical(unittest.TestCase):
    def test_jsonl_fixture(self):
        run1 = _pipeline_run(fixture("good", "bugfix", "input.jsonl"), GOOD_NARRATIVE)
        run2 = _pipeline_run(fixture("good", "bugfix", "input.jsonl"), GOOD_NARRATIVE)
        self.assertEqual(bc.render_html(run1), bc.render_html(run2))
        self.assertEqual(bc.render_markdown(run1), bc.render_markdown(run2))

    def test_zip_fixture(self):
        """ZIP 成员时间戳固定 → 同一输入两次解析渲染逐字节一致。"""
        run1 = _pipeline_run(fixture("good", "data", "export.zip"))
        run2 = _pipeline_run(fixture("good", "data", "export.zip"))
        self.assertEqual(bc.render_html(run1), bc.render_html(run2))
        self.assertEqual(bc.render_markdown(run1), bc.render_markdown(run2))

    def test_markdown_fixture(self):
        run1 = _pipeline_run(fixture("good", "research", "input.md"))
        run2 = _pipeline_run(fixture("good", "research", "input.md"))
        self.assertEqual(bc.render_html(run1), bc.render_html(run2))


class TestEmitAtomic(unittest.TestCase):
    def test_writes_all_files(self):
        with tempfile.TemporaryDirectory() as td:
            paths = bc.emit_atomic(Path(td), {"casebook.html": "<html></html>",
                                              "casebook.md": "# 摘要",
                                              "run.json": "{}"})
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(p.is_file() for p in paths))

    def test_leak_blocks_all_writes(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(rd.ResidualLeakError):
                bc.emit_atomic(Path(td), {"casebook.html": "<html>ok</html>",
                                          "casebook.md": "xhttps://keys.host/leak",
                                          "run.json": "{}"})
            self.assertEqual(list(Path(td).iterdir()), [], "残留扫描失败不得落盘任何文件")

    def test_no_partial_tmp_left_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            bc.emit_atomic(Path(td), {"casebook.md": "内容"})
            leftovers = [p.name for p in Path(td).iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class TestResourceGuards(unittest.TestCase):
    def test_template_loaded(self):
        self.assertIn("{{HEADER}}", bc.load_template())

    def test_css_no_external(self):
        css = bc.load_css()
        self.assertNotIn("url(", css)
        self.assertNotIn("@import", css)


if __name__ == "__main__":
    unittest.main()
