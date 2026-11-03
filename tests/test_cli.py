#!/usr/bin/env python3
"""test_cli.py — CLI 基本路径、退出码 2/3/4/6、cwd 无关、自检入口。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _helpers
from _helpers import SCRIPTS_DIR, SKILL_ROOT, fixture

import build_casebook as bc
import casebook as cb

CASEBOOK = SCRIPTS_DIR / "casebook.py"
PRODUCTS = ("casebook.html", "casebook.md", "run.json")


class TestUsageErrors(unittest.TestCase):
    def test_no_args_exit_2(self):
        self.assertEqual(cb.main([]), 2)

    def test_normalize_without_out_exit_2(self):
        with self.assertRaises(SystemExit) as cm:
            cb.main(["normalize", str(fixture("good", "bugfix", "input.jsonl"))])
        self.assertEqual(cm.exception.code, 2)

    def test_unknown_input_exit_3(self):
        with tempfile.TemporaryDirectory() as td:
            junk = Path(td) / "junk.txt"
            junk.write_text("not json not markdown\n", encoding="utf-8")
            self.assertEqual(cb.main(["all", str(junk), "--out", td]), 3)

    def test_narrative_violation_exit_4(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cb.main([
                "all", str(fixture("bad", "narrative-violation", "input.jsonl")),
                "--out", td,
                "--narrative", str(fixture("bad", "narrative-violation", "narrative.json")),
            ]), 4)
            self.assertTrue((Path(td) / "validate.report.json").is_file())
            self.assertFalse(any((Path(td) / p).exists() for p in PRODUCTS))


class TestBuildError(unittest.TestCase):
    def test_missing_template_exit_6(self):
        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td) / "work"
            self.assertEqual(cb.main([
                "normalize", str(fixture("good", "bugfix", "input.jsonl")),
                "--out", str(workdir)]), 0)
            self.assertEqual(cb.main(["redact", str(workdir)]), 0)
            with mock.patch.object(bc, "TEMPLATE_PATH", Path(td) / "missing-template.html"):
                self.assertEqual(cb.main(["build", str(workdir)]), 6)
            # 产物不落盘
            self.assertFalse((workdir / "casebook.html").exists())


class TestStepwisePipeline(unittest.TestCase):
    def test_normalize_validate_redact_build(self):
        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td) / "work"
            self.assertEqual(cb.main([
                "normalize", str(fixture("good", "bugfix", "input.jsonl")),
                "--out", str(workdir)]), 0)
            raw = json.loads((workdir / "run.raw.json").read_text(encoding="utf-8"))
            self.assertTrue(raw["__WARNING_UNREDACTED__"], "原始模型必须带醒目警告字段")
            self.assertEqual(cb.main(["validate", str(workdir)]), 0)
            self.assertEqual(cb.main(["redact", str(workdir)]), 0)
            redacted = json.loads((workdir / "run.json").read_text(encoding="utf-8"))
            self.assertNotIn("__WARNING_UNREDACTED__", redacted)
            self.assertEqual(redacted["redaction"]["residual_scan"], "passed")
            self.assertEqual(cb.main(["build", str(workdir)]), 0)
            for p in PRODUCTS:
                self.assertTrue((workdir / p).is_file(), p)


class TestAllFactMode(unittest.TestCase):
    def test_all_without_narrative(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "out"
            self.assertEqual(cb.main([
                "all", str(fixture("good", "bugfix", "input.jsonl")), "--out", str(outdir)]), 0)
            for p in PRODUCTS:
                self.assertTrue((outdir / p).is_file(), p)
            self.assertFalse((outdir / "run.raw.json").exists(), "all 模式不得落盘中间产物")
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            self.assertIsNone(run["narrative"])
            html = (outdir / "casebook.html").read_text(encoding="utf-8")
            self.assertIn("事实模式", html)


class TestCwdIndependence(unittest.TestCase):
    def test_all_runs_from_any_cwd(self):
        """资源路径以脚本自身位置解析：从任意 cwd 运行都必须成功。"""
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "out"
            proc = subprocess.run(
                [sys.executable, str(CASEBOOK), "all",
                 str(fixture("good", "bugfix", "input.jsonl")), "--out", str(outdir)],
                capture_output=True, text=True, cwd=str(SKILL_ROOT.parent))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            for p in PRODUCTS:
                self.assertTrue((outdir / p).is_file(), p)


class TestSelfcheckEntries(unittest.TestCase):
    def test_selftest_exit_0(self):
        self.assertEqual(cb.main(["--selftest"]), 0)

    def test_fixtures_exit_0(self):
        self.assertEqual(cb.main(["--fixtures"]), 0)

    def test_help_exit_2(self):
        with self.assertRaises(SystemExit) as cm:
            cb.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
