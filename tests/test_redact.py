#!/usr/bin/env python3
"""test_redact.py — 各类敏感串、中文路径、规则顺序、幂等、残留扫描。"""

import unittest

import redact as rd


class TestPatternRules(unittest.TestCase):
    CASES = [
        ("sk-abcdef0123456789abcdef01", "R-KEY-OPENAI"),
        ("AKIAABCDEFGHIJKLMNOP", "R-KEY-AWS"),
        ("ghp_abcdefghijklmnopqrstuvwxyz012345", "R-KEY-GITHUB"),
        ("xoxb-123456789012-abcdefgh", "R-KEY-SLACK"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwp", "R-JWT"),
        ("Bearer abcdefgh12345678", "R-BEARER"),
        ("postgres://admin:p4ssw0rd@db.host:5432/app", "R-URLCRED"),
        ("mongodb+srv://u:p@cluster.host/db", "R-CONN"),
        ("https://assets.host/static/app.js", "R-URL"),
        ("file:///C:/notes/x.txt", "R-FILEURI"),
        ("Set-Cookie: sid=abcdef0123456789; Path=/", "R-COOKIE"),
        ("cookie: session=abcdef0123456789", "R-COOKIE"),
    ]

    def test_each_rule_hits(self):
        for sample, rule in self.CASES:
            counts = {}
            out = rd.redact_text(sample, counts)
            self.assertIn(rule, counts, msg=sample)
            self.assertNotIn(sample, out, msg=sample)
            self.assertIn("[REDACTED:", out, msg=sample)

    def test_safe_text_untouched(self):
        for safe in ("修复解析逻辑", "步骤 2 完成", "s1/L42/j/toolCalls[0].callId",
                     "[REDACTED:R-KEY-OPENAI] 与 [PATH]"):
            self.assertEqual(rd.redact_text(safe), safe)

    def test_no_false_positive_on_generic_words(self):
        # 词表外普通词不触发（如 bearer 出现在无凭据语境、短 token 样词）
        self.assertEqual(rd.redact_text("task-based approach"), "task-based approach")


class TestPathRules(unittest.TestCase):
    def test_windows_ascii_path(self):
        counts = {}
        out = rd.redact_text("C:\\Users\\demo\\Documents\\report.md", counts)
        self.assertEqual(out, "[PATH]")
        self.assertIn("R-WINPATH", counts)

    def test_forward_slash_drive_path(self):
        """P2-1：盘符 + 正斜杠 + 重复斜杠变体同样脱敏。"""
        counts = {}
        out = rd.redact_text("见 C://Users//demo//app//config.ini 附录", counts)
        self.assertEqual(out, "见 [PATH] 附录")
        self.assertIn("R-WINPATH", counts)
        self.assertEqual(rd.redact_text("C:/Users/demo/app/config.ini"), "[PATH]")

    def test_windows_chinese_path(self):
        out = rd.redact_text("配置位于 C:\\用户\\演示\\项目\\报告.md 一文")
        self.assertNotIn("\\", out)
        self.assertIn("[PATH]", out)

    def test_posix_home_path(self):
        self.assertEqual(rd.redact_text("见 /home/demo/work/notes.md 附录"), "见 [PATH] 附录")

    def test_macos_users_path(self):
        self.assertEqual(rd.redact_text("check /Users/demo/dev/app.py first"), "check [PATH] first")

    def test_root_path(self):
        self.assertEqual(rd.redact_text("cat /root/.ssh/config"), "cat [PATH]")

    def test_relative_path_kept(self):
        self.assertEqual(rd.redact_text("编辑 src/parser.py 文件"), "编辑 src/parser.py 文件")


class TestStructuralKeys(unittest.TestCase):
    def test_sensitive_keys_redacted(self):
        counts = {}
        tree, counts = rd.redact_tree({
            "password": "abc123", "nested": {"token": "xyz", "note": "keep me"}},
            counts)
        self.assertEqual(tree["password"], "[REDACTED:R-STRUCT]")
        self.assertEqual(tree["nested"]["token"], "[REDACTED:R-STRUCT]")
        self.assertEqual(tree["nested"]["note"], "keep me")
        self.assertEqual(counts.get("R-STRUCT"), 2)

    def test_env_value_redacted(self):
        tree, _ = rd.redact_tree({"env_vars": {"DB_PASS": "hunter2", "MODE": "prod"}})
        self.assertEqual(tree["env_vars"], "[REDACTED:R-STRUCT]")


class TestOrderAndIdempotence(unittest.TestCase):
    def test_pattern_rules_before_path_rules(self):
        # 连接串内含路径样式：连接串规则先命中，整体替换为单一占位符
        out = rd.redact_text("postgres://u:p@h/db C:\\x\\y.md")
        self.assertTrue(out.startswith("[REDACTED:R-CONN]") or out.startswith("postgres://[REDACTED:R-URLCRED]"))
        self.assertNotIn("C:\\x\\y.md", out)

    def test_tree_idempotent(self):
        tree = {"a": "sk-abcdef0123456789abcdef01",
                "b": ["C:\\用户\\中文\\x.md", {"cookie": "sid=1"}],
                "c": {"text": "普通文本"}}
        once, _ = rd.redact_tree(tree)
        twice, _ = rd.redact_tree(once)
        self.assertEqual(once, twice)

    def test_text_idempotent(self):
        sample = "https://a.host/x C:\\y\\z.md"
        once = rd.redact_text(sample)
        self.assertEqual(rd.redact_text(once), once)


class TestResidualScan(unittest.TestCase):
    def test_rules_and_negative(self):
        self.assertIn("R-RES-HTTP", rd.residual_scan_text("see xhttps://keys.host/leak"))
        self.assertIn("R-RES-FILEURI", rd.residual_scan_text("see xfile://etc/passwd"))
        self.assertIn("R-KEY-OPENAI", rd.residual_scan_text("leak sk-abcdef0123456789abcdef01"))
        self.assertEqual(rd.residual_scan_text("干净文本 [REDACTED:R-URL] [PATH]"), [])

    def test_extra_markers(self):
        hits = rd.residual_scan_text("正文包含 MAGIC-MARKER 结尾", extra_markers=("MAGIC-MARKER",))
        self.assertIn("MARKER:MAGIC-MARKER", hits)

    def test_scan_bytes(self):
        self.assertIn("R-RES-HTTP", rd.residual_scan_bytes("xhttps://a.b".encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
