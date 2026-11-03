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
PRODUCTS = ("casebook.html", "casebook.md", "run.json", "redaction-report.txt")


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


class TestStrictPiiAndUrlFlags(unittest.TestCase):
    """P0-2 / P1-3 CLI 档位：strict-pii 默认 fail-closed；URL 分级。"""

    DIGITS_INPUT = ('{"type": "user", "text": "订单流水号 202611030000123，请复核", '
                    '"ts": "2026-03-05T10:00:00"}\n')
    URL_INPUT = ('{"type": "user", "text": "参考 https://arxiv.org/abs/2309.15217 撰写", '
                 '"ts": "2026-03-05T10:00:00"}\n')

    def _write(self, td, content):
        inp = Path(td) / "input.jsonl"
        inp.write_text(content, encoding="utf-8")
        return inp

    def test_strict_pii_default_blocks_suspect(self):
        with tempfile.TemporaryDirectory() as td:
            inp = self._write(td, self.DIGITS_INPUT)
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir)]), 5)
            self.assertFalse(any((outdir / p).exists() for p in PRODUCTS), "fail-closed 不落盘")

    def test_no_strict_pii_passes_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            inp = self._write(td, self.DIGITS_INPUT)
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir),
                                      "--no-strict-pii"]), 0)
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            codes = [w.get("code") for w in run.get("warnings", [])]
            self.assertIn("PII_SUSPECTED", codes)
            suspect = [w for w in run["warnings"] if w["code"] == "PII_SUSPECTED"][0]
            self.assertTrue(suspect.get("source_ref"), "PII_SUSPECTED 必须带定位 source_ref")
            self.assertTrue(suspect.get("detail", "").startswith("形态探测命中"))

    def test_default_mode_preserves_external_url(self):
        with tempfile.TemporaryDirectory() as td:
            inp = self._write(td, self.URL_INPUT)
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir)]), 0)
            html = (outdir / "casebook.html").read_text(encoding="utf-8")
            self.assertIn("https://arxiv.org/abs/2309.15217", html)

    def test_no_urls_flag_redacts_all_urls(self):
        with tempfile.TemporaryDirectory() as td:
            inp = self._write(td, self.URL_INPUT)
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir),
                                      "--no-urls"]), 0)
            html = (outdir / "casebook.html").read_text(encoding="utf-8")
            self.assertNotIn("arxiv.org", html)
            self.assertIn("[REDACTED:R-URL]", html)

    def test_url_flags_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            inp = self._write(td, self.URL_INPUT)
            with self.assertRaises(SystemExit) as cm:
                cb.main(["all", str(inp), "--out", str(td), "--no-urls", "--keep-urls"])
            self.assertEqual(cm.exception.code, 2)


class TestDenylistAndReport(unittest.TestCase):
    """P2-3 / P2-6：--denylist、redaction-report.txt、run.json 不含原文。"""

    INPUT = ('{"type": "user", "text": "客户张伟来电，回电 13812345678", '
             '"ts": "2026-03-05T10:00:00"}\n')

    def test_denylist_flag_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(self.INPUT, encoding="utf-8")
            dl = Path(td) / "dl.txt"
            dl.write_text("# 注释\n张伟\n\n", encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir),
                                      "--denylist", str(dl)]), 0)
            for p in PRODUCTS:
                self.assertTrue((outdir / p).is_file(), p)
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            blob = json.dumps(run, ensure_ascii=False)
            self.assertNotIn("张伟", blob)
            self.assertNotIn("13812345678", blob)
            self.assertIn("[REDACTED:R-DENYLIST]", blob)
            applied = {a["rule"]: a["count"] for a in run["redaction"]["applied"]}
            self.assertEqual(applied.get("R-DENYLIST"), 1)
            self.assertEqual(applied.get("R-CN-MOBILE"), 1)
            self.assertTrue(all("snippet" not in d for d in run["redaction"]["details"]),
                            "run.json details 不得含原文片段")
            report = (outdir / "redaction-report.txt").read_text(encoding="utf-8")
            self.assertIn("不可分享", report)
            self.assertIn("张伟", report)
            self.assertIn("13812345678", report)
            html = (outdir / "casebook.html").read_text(encoding="utf-8")
            self.assertNotIn("张伟", html)
            self.assertNotIn("13812345678", html)

    def test_default_report_written_without_denylist(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(self.INPUT, encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir)]), 0)
            report = (outdir / "redaction-report.txt").read_text(encoding="utf-8")
            self.assertIn("不可分享", report)
            self.assertIn("13812345678", report)

    def test_denylist_missing_file_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(self.INPUT, encoding="utf-8")
            self.assertEqual(cb.main(["all", str(inp), "--out", str(td),
                                      "--denylist", str(Path(td) / "nope.txt")]), 2)

    def test_counts_three_urls_in_run_json(self):
        """P2-6 验收：一条文本含 3 个 URL，对应规则计数必须为 3。"""
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text('{"type": "user", "text": "a https://x.example/1 '
                           'https://y.example/2 https://z.example/3", '
                           '"ts": "2026-03-05T10:00:00"}\n', encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir),
                                      "--no-urls"]), 0)
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            applied = {a["rule"]: a["count"] for a in run["redaction"]["applied"]}
            self.assertEqual(applied.get("R-URL"), 3)


class TestUrlClaimLeakRegression(unittest.TestCase):
    """F-1 / F-2 复测回归：URL query 不再被句读切碎；--no-urls 不因 details 假阳性 exit 5。"""

    def test_assistant_url_query_redacted_in_claims(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(
                '{"type": "assistant", "text": "已配置回调 '
                'https://api.example.com/cb?access_token=abc123 请查收。", '
                '"ts": "2026-03-05T10:01:00"}\n', encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir)]), 0)
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(len(run["claims"]), 1, "URL 内 ? 不得切分 claim")
            blob = json.dumps(run, ensure_ascii=False)
            self.assertNotIn("access_token", blob)
            html = (outdir / "casebook.html").read_text(encoding="utf-8")
            self.assertNotIn("access_token", html)
            self.assertIn("[REDACTED:R-URL-QUERY]", html)

    def test_no_urls_with_cred_url_exit_0(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(
                '{"type": "assistant", "text": "回调 https://user:secret@example.com/x 已处理。", '
                '"ts": "2026-03-05T10:01:00"}\n', encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir),
                                      "--no-urls"]), 0)
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            blob = json.dumps(run, ensure_ascii=False)
            self.assertNotIn("user:secret", blob)
            self.assertIn("[REDACTED:R-URL]", blob)
            self.assertNotIn("https://[REDACTED:R-URLCRED]", blob,
                             "--no-urls 档 cred URL 应被整体抹除")

    def test_combined_url_sample_zero_leak_default(self):
        """F-1 验收：userinfo + query token + 多 sid + URL 内 ?/! 的组合样本。"""
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(
                '{"type": "assistant", "text": "回调 https://user:secret@example.com/cb'
                '?access_token=abc123!ok 与 https://a.example/set?sid=x1 和 '
                'https://b.example/set?sid=x2。", "ts": "2026-03-05T10:01:00"}\n',
                encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir)]), 0)
            run = json.loads((outdir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(len(run["claims"]), 1, "URL 不被句读切断")
            blob = json.dumps(run, ensure_ascii=False)
            for bad in ("user:secret", "access_token", "abc123", "sid=x1", "sid=x2"):
                self.assertNotIn(bad, blob, bad)
            for p in ("casebook.html", "casebook.md"):
                text = (outdir / p).read_text(encoding="utf-8")
                for bad in ("user:secret", "access_token", "abc123", "sid=x"):
                    self.assertNotIn(bad, text, "{}: {}".format(p, bad))

    def test_keep_urls_token_query_strict_exit5(self):
        """F-1 兜底：keep-urls 保留的 query 若含高风险键，strict 默认 exit 5。"""
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(
                '{"type": "assistant", "text": "回调 https://a.example/cb'
                '?access_token=abc123 已登记。", "ts": "2026-03-05T10:01:00"}\n',
                encoding="utf-8")
            outdir = Path(td) / "out"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir),
                                      "--keep-urls"]), 5)
            self.assertFalse(any((outdir / p).exists() for p in PRODUCTS))
            # 宽松档放行并记 PII_SUSPECTED
            outdir2 = Path(td) / "out2"
            self.assertEqual(cb.main(["all", str(inp), "--out", str(outdir2),
                                      "--keep-urls", "--no-strict-pii"]), 0)
            run = json.loads((outdir2 / "run.json").read_text(encoding="utf-8"))
            codes = [w.get("code") for w in run.get("warnings", [])]
            self.assertIn("PII_SUSPECTED", codes)


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
