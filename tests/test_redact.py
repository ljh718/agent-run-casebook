#!/usr/bin/env python3
"""test_redact.py — 各类敏感串、中文路径、规则顺序、幂等、残留扫描。"""

import json
import unittest

import redact as rd
import build_casebook as bc


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
        ("https://api.example.com/cb?access_token=abc123", "R-URL-QUERY"),
        ("https://wiki.corp.cn/rag-eval", "R-URL-INTERNAL"),
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


class TestPiiRules(unittest.TestCase):
    """P0-1 回归基线：报告已实测的命中与不误伤清单。"""

    HIT = [
        ("部署到 106.53.62.135", "R-IPV4"),
        ("13812345678", "R-CN-MOBILE"),
        ("138-1234-5678", "R-CN-MOBILE"),
        ("+86 138-1234-5678", "R-CN-MOBILE"),
        ("zhang.wei@corp.cn", "R-EMAIL"),
        ("110105199003074512", "R-CN-ID"),
        ("6222021234567890123", "R-BANKCARD"),
        ("服务器密码 Ljh071823!", "R-INLINE-CRED"),
        ("password=hunter2x", "R-INLINE-CRED"),
        ("-----BEGIN OPENSSL PRIVATE KEY-----\nMIIEvQ\n-----END OPENSSL PRIVATE KEY-----",
         "R-PRIVKEY"),
        ("-----BEGIN OPENSSL PRIVATE KEY-----", "R-PRIVKEY"),
    ]
    SAFE = [
        "版本 python 3.11.4",
        "耗时 360000 ms",
        "改动 3 个文件",
        "覆盖率 87%",
        "订单 2026110300001",
        "端口 6379",
        "日志行 L4210",
        "密码错误三次",
        "密码为空",
        "密码字段必填",
        "密码长度至少 8 位",
        "用户抱怨密码记不住",
    ]

    def test_each_pii_rule_hits(self):
        for sample, rule in self.HIT:
            counts = {}
            out = rd.redact_text(sample, counts)
            self.assertIn(rule, counts, msg=sample)
            self.assertNotIn(sample, out, msg=sample)
            self.assertIn("[REDACTED:", out, msg=sample)

    def test_no_false_positive_on_reported_safe_list(self):
        for safe in self.SAFE:
            self.assertEqual(rd.redact_text(safe), safe, msg=safe)

    def test_inline_cred_idempotent_after_replacement(self):
        once = rd.redact_text("password=hunter2x")
        self.assertEqual(rd.redact_text(once), once)

    def test_pii_tree_idempotent(self):
        tree = {"text": "客户 张伟，手机 13812345678，密码 abc12345，"
                        "邮箱 a@b.cn，卡 6222021234567890123"}
        once, _ = rd.redact_tree(tree)
        twice, _ = rd.redact_tree(once)
        self.assertEqual(once, twice)


class TestUrlTiering(unittest.TestCase):
    """P1-3：URL 分级——默认保留 host+path、抹 query、抹内网域名。"""

    def test_default_preserves_public_host_path(self):
        sample = "参考 https://arxiv.org/abs/2309.15217 与 https://docs.ragas.io/en/stable/"
        self.assertEqual(rd.redact_text(sample), sample)

    def test_default_redacts_query(self):
        out = rd.redact_text("见 https://api.example.com/cb?access_token=abc123 说明")
        self.assertIn("https://api.example.com/cb?[REDACTED:R-URL-QUERY]", out)
        self.assertNotIn("access_token", out)

    def test_default_redacts_internal_domain(self):
        out = rd.redact_text("另见内部文档 https://wiki.corp.cn/rag-eval 第 3 节。")
        self.assertNotIn("wiki.corp.cn", out)
        self.assertIn("[REDACTED:R-URL-INTERNAL]", out)

    def test_internal_bare_tld(self):
        out = rd.redact_text("见 xhttps://keys.internal/leak 末尾")
        self.assertNotIn("keys.internal", out)

    def test_no_urls_redacts_all(self):
        out = rd.redact_text("见 https://arxiv.org/abs/2309.15217 说明", url_mode="no-urls")
        self.assertNotIn("https://", out)
        self.assertIn("[REDACTED:R-URL]", out)

    def test_keep_urls_keeps_query_and_internal(self):
        sample = "见 https://api.example.com/cb?access_token=abc123 与 https://wiki.corp.cn/x"
        out = rd.redact_text(sample, url_mode="keep-urls")
        self.assertIn("access_token", out)
        self.assertIn("wiki.corp.cn", out)

    def test_cred_url_userinfo_still_redacted_in_all_modes(self):
        for mode in ("default", "no-urls", "keep-urls"):
            out = rd.redact_text("https://user:secret@example.com/x", url_mode=mode)
            self.assertNotIn("user:secret", out, msg=mode)


class TestResidualSuspicious(unittest.TestCase):
    """P0-2：独立宽检测集与规则复检拆分。"""

    def test_strict_default_flags_wide_forms(self):
        self.assertIn("R-SUS-DIGITS", rd.residual_scan_text("订单 202611030000123 受理"))
        self.assertIn("R-SUS-EMAIL", rd.residual_scan_text("mail a@b.cn"))
        self.assertIn("R-SUS-IPV4", rd.residual_scan_text("host 10.1.2.3"))
        self.assertIn("R-SUS-PRIVKEY", rd.residual_scan_text("-----BEGIN PRIVATE KEY-----"))
        self.assertIn("R-SUS-CREDWORD", rd.residual_scan_text("password=abcd1234"))

    def test_no_strict_skips_suspicious_only(self):
        hits = rd.residual_scan_text("订单 202611030000123", strict_pii=False)
        self.assertEqual([h for h in hits if h.startswith("R-SUS")], [])

    def test_rules_recheck_ignores_placeholders(self):
        clean = "密码 [REDACTED:R-INLINE-CRED] [PATH] https://arxiv.org/abs/2309.15217"
        self.assertEqual(rd.residual_scan_text(clean), [])

    def test_rules_recheck_still_catches_missed_rules(self):
        self.assertIn("R-KEY-OPENAI", rd.residual_scan_text("leak sk-abcdef0123456789abcdef01"))

    def test_suspect_scan_tree_reports_paths(self):
        tree = {"claims": [{"text": "订单 202611030000123"}]}
        self.assertIn(("R-SUS-DIGITS", "$.claims[0].text"), rd.suspect_scan_tree(tree))

    def test_suspect_scan_tree_clean(self):
        tree = {"text": "耗时 360000 ms", "redaction": {"url_mode": "default"}}
        self.assertEqual(rd.suspect_scan_tree(tree), [])


class TestDenylistAndCounts(unittest.TestCase):
    """P2-3 / P2-6：自定义 denylist 与精确替换计数。"""

    def test_counts_per_replacement(self):
        counts = {}
        out = rd.redact_text("https://a.example/1 https://b.example/2 https://c.example/3",
                             counts, url_mode="no-urls")
        self.assertEqual(counts.get("R-URL"), 3)
        self.assertEqual(out.count("[REDACTED:R-URL]"), 3)

    def test_counts_phone_multiple(self):
        counts = {}
        rd.redact_text("13812345678 13812345678 13812345678", counts)
        self.assertEqual(counts.get("R-CN-MOBILE"), 3)

    def test_denylist_basic_and_longest_first(self):
        counts = {}
        out = rd.redact_text("客户张伟使用了 Atlas-内部代号", counts,
                             denylist=["Atlas-内部代号", "张伟"])
        self.assertEqual(out, "客户[REDACTED:R-DENYLIST]使用了 [REDACTED:R-DENYLIST]")
        self.assertEqual(counts.get("R-DENYLIST"), 2)

    def test_denylist_plain_string_not_regex(self):
        out = rd.redact_text("a.c$^ 匹配测试", denylist=["c$^"])
        self.assertEqual(out, "a.[REDACTED:R-DENYLIST] 匹配测试")

    def test_denylist_idempotent(self):
        once = rd.redact_text("客户张伟", denylist=["张伟"])
        self.assertEqual(rd.redact_text(once, denylist=["张伟"]), once)

    def test_denylist_protects_placeholders(self):
        out = rd.redact_text("已脱敏 [REDACTED:R-URL] 与 张伟R-URL尾", denylist=["R-URL"])
        self.assertEqual(out.count("[REDACTED:R-URL]"), 1)
        self.assertTrue(out.endswith("[REDACTED:R-DENYLIST]尾"))

    def test_denylist_residual_recheck(self):
        self.assertIn("R-DENYLIST", rd.residual_scan_text("涉及张伟", denylist=["张伟"]))
        self.assertNotIn("R-DENYLIST", rd.residual_scan_text(
            "[REDACTED:R-DENYLIST] 已清洗完毕", denylist=["R-URL"]))

    def test_load_denylist_ignores_comments_and_blanks(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "dl.txt"
            p.write_text("# 注释行\n张伟\n\n  Atlas  \n", encoding="utf-8")
            self.assertEqual(rd.load_denylist(p), ["张伟", "Atlas"])

    def test_audit_details_captured_with_path(self):
        audit = []
        rd.redact_tree({"task": {"goal": "手机 13812345678 与 13987654321"}}, audit=audit)
        self.assertEqual(len(audit), 2)
        self.assertEqual({a["rule_id"] for a in audit}, {"R-CN-MOBILE"})
        self.assertTrue(all(a["source_ref"] == "$.task.goal" for a in audit))
        self.assertEqual(audit[0]["snippet"], "13812345678")
        self.assertIn("replacement", audit[0])

    def test_audit_details_denylist(self):
        audit = []
        rd.redact_text("客户张伟", audit=audit, source_ref="$.x", denylist=["张伟"])
        self.assertEqual(audit[0]["rule_id"], "R-DENYLIST")
        self.assertEqual(audit[0]["snippet"], "张伟")

    def test_audit_replacement_scheme_masked(self):
        """F-2：details.replacement 的 URL scheme 掩码，防 --no-urls 档复检假阳性。"""
        audit = []
        rd.redact_text("回调 https://user:secret@example.com/x", audit=audit,
                       source_ref="$.x", url_mode="no-urls")
        replacements = [a["replacement"] for a in audit if a["rule_id"] == "R-URLCRED"]
        self.assertTrue(replacements)
        for r in replacements:
            self.assertNotIn("https://", r.lower())
            self.assertIn("[SCHEME]://", r)
        # R-URL 带守卫 + R-URL-CREDREST 兜底：残体形态漏进产物仍被拦截（fail-closed）
        text = "回调 https://[REDACTED:R-URLCRED]@api.example.com/cb 已脱敏"
        hits = rd.residual_scan_text(text, url_mode="no-urls")
        self.assertIn("R-URL-CREDREST", hits)
        # --no-urls 档：cred URL 在内容层被整体抹除，无残留
        out = rd.redact_text("回调 https://user:secret@example.com/x", url_mode="no-urls")
        self.assertEqual(out, "回调 [REDACTED:R-URL]")
        self.assertEqual(rd.residual_scan_text(out, url_mode="no-urls"), [])

    def test_sus_urlkey_backstop(self):
        """F-1 兜底：query 高风险键出现在产物中即 strict 硬门命中；已替换占位符不命中。"""
        for sample in ("see https://a.example/cb?access_token=abc123",
                       "回调 https://a.example/set?sid=x1 完成",
                       "参数 ?client_secret=abcdef 结尾",
                       "oauth 回调 ?code=xyz99 返回"):
            self.assertIn("R-SUS-URLKEY", rd.residual_scan_text(sample), msg=sample)
        self.assertNotIn("R-SUS-URLKEY",
                         rd.residual_scan_text("https://a.example/cb?[REDACTED:R-URL-QUERY]"))
        self.assertNotIn("R-SUS-URLKEY",
                         rd.residual_scan_text("路径形态 https://a.example/auth/login 无键值"))


class TestResidualScan(unittest.TestCase):
    def test_rules_and_negative(self):
        self.assertIn("R-RES-URLCRED", rd.residual_scan_text("see xhttps://u:p@keys.host/leak"))
        self.assertIn("R-RES-FILEURI", rd.residual_scan_text("see xfile://etc/passwd"))
        self.assertIn("R-KEY-OPENAI", rd.residual_scan_text("leak sk-abcdef0123456789abcdef01"))
        self.assertEqual(rd.residual_scan_text("干净文本 [REDACTED:R-URL] [PATH]"), [])

    def test_plain_external_url_not_negative(self):
        """P1-3：普通外链自 v1.1.0 起不再是绝对禁项。"""
        self.assertNotIn("R-RES-URLCRED",
                         rd.residual_scan_text("see https://arxiv.org/abs/2309.15217"))

    def test_extra_markers(self):
        hits = rd.residual_scan_text("正文包含 MAGIC-MARKER 结尾", extra_markers=("MAGIC-MARKER",))
        self.assertIn("MARKER:MAGIC-MARKER", hits)

    def test_scan_bytes(self):
        self.assertIn("R-RES-URLCRED", rd.residual_scan_bytes("xhttps://u:p@a.b".encode("utf-8")))


class TestResidualScanTreeDomain(unittest.TestCase):
    """v1.2.0：复检域不变式——规则的应用域是字符串叶，复检必须同域。

    回归背景（真实 DSH 会话实测，样本脱敏重构）：正文「……密码）」后接
    换行 + 编号列表「2. …」，叶内凭据值段只有 1 个非空白字符（规则不命中、
    也不该命中）；但 JSON 序列化把换行编码为字面反斜杠+n、HTML 渲染在
    <pre> 结尾后直接拼接标记串，两种字节流上都能凑满 \\S{4,} 而误触发
    R-INLINE-CRED 硬门（exit 5、产物零落盘）。修复：run.json / HTML / MD
    统一按脱敏树逐叶扫描（residual_scan_tree）。"""

    # 脱敏合成样本：中文正文形态（无任何真实凭据），两个跨界变体同形
    PROSE_LEAF = "请通过跳板机连上环境（需要你输一次 root 密码）\n2. 重新验证能否正常连接。"
    END_LEAF = "请通过跳板机连上环境（需要你输一次 root 密码）"
    # 叶内真凭据形态：密码 + 4 个以上非空白字符（应被应用且复检零命中）
    CRED_LEAF = "数据库密码是 abcd1234efgh，请勿外传。"

    def _redact_tree(self, text):
        run = {"task": {"goal": text}, "warnings": []}
        redacted, counts = rd.redact_tree(run)
        return redacted, counts

    def test_prose_boundary_not_applied_and_tree_scan_clean(self):
        """跨界正文：规则不应用（值段过短），逐叶复检零命中。"""
        redacted, counts = self._redact_tree(self.PROSE_LEAF)
        self.assertNotIn("R-INLINE-CRED", counts)
        self.assertEqual(rd.residual_scan_tree(redacted), [])
        self.assertEqual(rd.suspect_scan_tree(redacted), [])
        blob = json.dumps(redacted, ensure_ascii=False)
        self.assertIn("root 密码", blob, "正文非凭据内容必须原样保留")

    def test_json_bytes_divergence_documented(self):
        """文档化根因：同一树的 JSON 字节流会命中（字面 \\n 转义拼出跨界值段），
        因此复检禁止在序列化字节流上进行。"""
        redacted, _ = self._redact_tree(self.PROSE_LEAF)
        payload = json.dumps(redacted, ensure_ascii=False).encode("utf-8")
        self.assertIn("R-INLINE-CRED", rd.residual_scan_bytes(payload))

    def test_html_markup_boundary_not_hit(self):
        """HTML 变体：<pre> 单元格结尾「密码）」后紧跟标记串，叶内值段过短；
        树扫描零命中（渲染字节流属非应用域，不得作为复检依据）。"""
        redacted, _ = self._redact_tree(self.END_LEAF)
        # 模拟渲染拼接：叶文本后紧跟非空白标记串（形态同 </pre></td><td><span）
        rendered_like = self.END_LEAF + "</pre></td><td><span"
        rx = dict((r[0], r[1]) for r in rd.REDACTION_RULES)["R-INLINE-CRED"]
        self.assertTrue(rx.search(rendered_like), "字节流形态应能复现误报")
        self.assertEqual(rd.residual_scan_tree(redacted), [])

    def test_real_cred_still_applied_and_clean(self):
        """不变式正向：真凭据叶应用后逐叶复检零命中（守卫覆盖占位符）。"""
        redacted, counts = self._redact_tree(self.CRED_LEAF)
        self.assertEqual(counts.get("R-INLINE-CRED"), 1)
        self.assertNotIn("abcd1234efgh", json.dumps(redacted, ensure_ascii=False))
        self.assertEqual(rd.residual_scan_tree(redacted), [])
        self.assertEqual(rd.suspect_scan_tree(redacted), [])

    def test_unredacted_cred_tree_caught(self):
        """负向：未经应用的树（绕过脱敏）必须被逐叶复检拦截——修复不得放松语义。"""
        tree = {"task": {"goal": self.CRED_LEAF}}
        self.assertIn("R-INLINE-CRED", rd.residual_scan_tree(tree))
        self.assertIn("R-SUS-CREDWORD", rd.residual_scan_tree(tree))

    def test_tree_scan_denylist_and_markers(self):
        tree = {"task": {"goal": "涉及张伟的项目"}, "warnings": []}
        self.assertIn("R-DENYLIST", rd.residual_scan_tree(tree, denylist=["张伟"]))
        cleaned, _ = rd.redact_tree({"task": {"goal": "涉及张伟的项目"}},
                                    denylist=["张伟"])
        self.assertEqual(rd.residual_scan_tree(cleaned, denylist=["张伟"]), [])
        self.assertIn("MARKER:M1", rd.residual_scan_tree(
            {"task": {"goal": "含标记 M1"}}, extra_markers=("M1",)))

    def test_emit_atomic_tree_scan_beats_rendered_bytes(self):
        """emit_atomic 传入 scan_tree 时按叶扫描：跨界正文产物应成功落盘。"""
        import tempfile
        from pathlib import Path
        redacted, _ = self._redact_tree(self.PROSE_LEAF)
        html_text = "<p>" + self.END_LEAF + "</pre></td><td><span"
        with tempfile.TemporaryDirectory() as td:
            paths = bc.emit_atomic(td, {"casebook.html": html_text,
                                        "run.json": json.dumps(redacted).encode("utf-8")},
                                   scan_tree=redacted)
            self.assertTrue(all(Path(p).is_file() for p in paths))

    def test_emit_atomic_byte_scan_still_blocks_leak(self):
        """向后兼容：不传 scan_tree 时保持逐产物字节扫描（直接调用方语义不变）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(rd.ResidualLeakError):
                bc.emit_atomic(td, {"casebook.html": "数据库密码是 abcd1234efgh"})

    def test_cli_end_to_end_boundary_prose_exit_0(self):
        """CLI 端到端：含跨界正文形态的合成 JSONL 走 all 全流程 → exit 0 四件产物齐。"""
        import json as _json
        import tempfile
        import casebook as cb_cli
        from pathlib import Path
        lines = [
            _json.dumps({"type": "user", "text": "排查连接问题", "ts": "2026-03-01T10:00:00"},
                        ensure_ascii=False),
            _json.dumps({"type": "assistant",
                         "text": self.PROSE_LEAF,
                         "ts": "2026-03-01T10:01:00"}, ensure_ascii=False),
        ]
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            outdir = Path(td) / "out"
            code = cb_cli.main(["all", str(inp), "--out", str(outdir)])
            self.assertEqual(code, 0)
            for name in ("casebook.html", "casebook.md", "run.json",
                         "redaction-report.txt"):
                self.assertTrue((outdir / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
