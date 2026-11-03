#!/usr/bin/env python3
"""casebook.py — agent-run-casebook 唯一 CLI 入口。

子命令（设计蓝图 3）：
    normalize <input> --out <dir>          解析输入 → run.raw.json（未脱敏，带醒目警告）+ normalize.report.json
    validate  <dir>                        schema / 引用 / narrative 白名单校验 → validate.report.json
    redact    <dir> [--narrative <file>]   全树脱敏 run.raw.json（+ 可选 narrative）→ run.json
    build     <dir> [--out <dir>]          渲染 casebook.html / casebook.md（+ run.json 原子副本）
    all       <input> --out <dir> [--narrative <file>]
                                           normalize→validate→redact→build 全内存串联，只落三件产物
    --selftest                             内置自检：脱敏 / 转义 / 证据判定 / 幂等向量
    --fixtures                             按 tests/fixtures/fixtures.json 跑回归集（缺失时清晰报错）

退出码：0 成功 | 2 用法错误 | 3 输入不可识别 | 4 校验失败 | 5 脱敏残留硬门 | 6 构建错误。

路径基准：所有资源以脚本自身位置解析技能根（Path(__file__)），不依赖 cwd。
run.raw.json 含未脱敏内容：首行含 "__WARNING_UNREDACTED__": true，不得分享该中间文件。
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import runmodel as rm            # noqa: E402
import normalize as nz           # noqa: E402
import validate_case as vc       # noqa: E402
import redact as rd              # noqa: E402
import build_casebook as bc      # noqa: E402

EXIT_OK, EXIT_USAGE, EXIT_INPUT, EXIT_VALIDATE, EXIT_REDACT, EXIT_BUILD = 0, 2, 3, 4, 5, 6

RAW_WARNING_FIELD = "__WARNING_UNREDACTED__"


# ── 共用读写 ────────────────────────────────────────────────────────

def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)


def _write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def _load_run_raw(workdir):
    path = Path(workdir) / "run.raw.json"
    if not path.is_file():
        print("找不到 {}；请先运行 normalize 子命令。".format(path))
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop(RAW_WARNING_FIELD, None)
    return data


def _load_narrative(path):
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        print("narrative 文件不存在: {}".format(p))
        return False
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print("narrative JSON 解析失败（按蓝图要求模型重出或放弃叙事）: {}".format(exc))
        return False


def _redaction_stats(counts):
    return {"applied": [{"rule": k, "count": v} for k, v in sorted(counts.items())],
            "residual_scan": "passed"}


# ── 子命令 ──────────────────────────────────────────────────────────

def cmd_normalize(args):
    try:
        run, report = nz.parse_input(args.input)
    except nz.UnrecognizedInputError as exc:
        print("输入不可识别: {}".format(exc))
        return EXIT_INPUT
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    raw_out = {RAW_WARNING_FIELD: True}
    raw_out.update(run)
    _write(outdir / "run.raw.json", _dump(raw_out) + "\n")
    _write(outdir / "normalize.report.json", _dump(report) + "\n")
    print("normalize 完成：{} 条记录，{} 警告，{} 降级 → {}".format(
        report["record_count"], report["warnings"], report["parse_errors"], outdir / "run.raw.json"))
    print("警告：run.raw.json 含未脱敏内容（{} 字段），不得分享该中间文件。".format(RAW_WARNING_FIELD))
    return EXIT_OK


def cmd_validate(args):
    run = _load_run_raw(args.dir)
    if run is None:
        return EXIT_USAGE
    narrative = _load_narrative(Path(args.dir) / "narrative.json") \
        if (Path(args.dir) / "narrative.json").is_file() else None
    if narrative is False:
        return EXIT_USAGE
    violations = vc.validate_run(run, narrative)
    report = {"passed": not violations, "violations": violations}
    _write(Path(args.dir) / "validate.report.json", _dump(report) + "\n")
    if violations:
        print("校验失败，{} 条违规:".format(len(violations)))
        for v in violations:
            print("  - [{}] {}: {}".format(v["code"], v["path"], v["detail"]))
        return EXIT_VALIDATE
    print("校验通过（schema / 引用 / narrative 白名单）。")
    return EXIT_OK


def cmd_redact(args):
    run = _load_run_raw(args.dir)
    if run is None:
        return EXIT_USAGE
    narrative = None
    if args.narrative:
        narrative = _load_narrative(args.narrative)
        if narrative is False:
            return EXIT_USAGE
        violations = vc.validate_narrative(run, narrative)
        if violations:
            print("narrative 白名单核验未通过，{} 条违规:".format(len(violations)))
            for v in violations:
                print("  - [{}] {}: {}".format(v["code"], v["path"], v["detail"]))
            return EXIT_VALIDATE
        run["narrative"] = narrative
        run["narrative_check"] = {"passed": True, "violations": []}
    redacted, counts = rd.redact_tree(run)
    redacted["redaction"] = _redaction_stats(counts)
    payload = (_dump(redacted) + "\n").encode("utf-8")
    hits = rd.residual_scan_bytes(payload)
    if hits:
        print("残留扫描不通过（硬门），run.json 不落盘。命中: {}".format(", ".join(hits)))
        return EXIT_REDACT
    outdir = Path(args.dir)
    outdir.mkdir(parents=True, exist_ok=True)
    _write(outdir / "run.json", payload.decode("utf-8"))
    print("redact 完成 → {}".format(outdir / "run.json"))
    return EXIT_OK


def cmd_build(args):
    run_path = Path(args.dir) / "run.json"
    if not run_path.is_file():
        print("找不到 {}；请先运行 redact 子命令。".format(run_path))
        return EXIT_USAGE
    run = json.loads(run_path.read_text(encoding="utf-8"))
    try:
        html_text = bc.render_html(run)
        md_text = bc.render_markdown(run)
    except bc.BuildError as exc:
        print("构建错误: {}".format(exc))
        return EXIT_BUILD
    outdir = Path(args.out) if args.out else Path(args.dir)
    try:
        paths = bc.emit_atomic(outdir, {
            "casebook.html": html_text,
            "casebook.md": md_text,
            "run.json": run_path.read_bytes(),
        })
    except rd.ResidualLeakError as exc:
        print("残留扫描不通过（硬门），产物不落盘。{}".format(exc))
        return EXIT_REDACT
    for p in paths:
        print("产物: {}".format(p))
    return EXIT_OK


def cmd_all(args):
    """主路径：全内存串联，中间模型不落盘；只落三件最终产物。"""
    try:
        run, report = nz.parse_input(args.input)
    except nz.UnrecognizedInputError as exc:
        print("输入不可识别: {}".format(exc))
        return EXIT_INPUT
    outdir = Path(args.out)
    narrative = None
    if args.narrative:
        narrative = _load_narrative(args.narrative)
        if narrative is False:
            return EXIT_USAGE
        violations = vc.validate_run(run, narrative)
        if violations:
            # 给模型一次修正机会的会话层约定：CLI 落盘违规清单供回传，不放行违规叙事
            outdir.mkdir(parents=True, exist_ok=True)
            _write(outdir / "validate.report.json",
                   _dump({"passed": False, "violations": violations}) + "\n")
            print("narrative 白名单核验未通过，{} 条违规（清单见 {}）。绝不放行违规叙事。".format(
                len(violations), outdir / "validate.report.json"))
            return EXIT_VALIDATE
        run["narrative"] = narrative
        run["narrative_check"] = {"passed": True, "violations": []}
    else:
        run["narrative"] = None
        run["narrative_check"] = {"passed": False, "violations": [], "reason": "no-narrative (fact mode)"}

    redacted, counts = rd.redact_tree(run)
    redacted["redaction"] = _redaction_stats(counts)
    try:
        html_text = bc.render_html(redacted)
        md_text = bc.render_markdown(redacted)
    except bc.BuildError as exc:
        print("构建错误: {}".format(exc))
        return EXIT_BUILD
    run_json_bytes = (_dump(redacted) + "\n").encode("utf-8")
    try:
        paths = bc.emit_atomic(outdir, {
            "casebook.html": html_text,
            "casebook.md": md_text,
            "run.json": run_json_bytes,
        })
    except rd.ResidualLeakError as exc:
        print("残留扫描不通过（硬门），产物不落盘。{}".format(exc))
        return EXIT_REDACT
    print("all 完成：{} 条记录，{} 警告，{} 降级。".format(
        report["record_count"], report["warnings"], report["parse_errors"]))
    levels = {}
    for c in redacted.get("claims", []):
        levels[c["evidence_level"]] = levels.get(c["evidence_level"], 0) + 1
    print("证据分级摘要: {}".format(
        json.dumps(levels, ensure_ascii=False) if levels else "（无主张记录）"))
    if report["parse_errors"] or report["warnings"]:
        print("降级说明：部分记录不可用或字段未识别，详见产物「复现与未知事项」区块。")
    for p in paths:
        print("产物: {}".format(p))
    return EXIT_OK


# ── 自检 ────────────────────────────────────────────────────────────

def selftest():
    """内置自检：脱敏规则向量、转义向量、证据判定向量、幂等向量。"""
    ok_all = True

    def check(label, ok):
        nonlocal ok_all
        ok_all = ok_all and ok
        print(("PASS" if ok else "FAIL") + " " + label)

    # 脱敏规则向量：命中样本必须被替换且原样不残留；安全样本必须原样保留
    leak_samples = [
        ("sk-abcdef0123456789abcdef01", "R-KEY-OPENAI"),
        ("AKIAABCDEFGHIJKLMNOP", "R-KEY-AWS"),
        ("ghp_abcdefghijklmnopqrstuvwxyz012345", "R-KEY-GITHUB"),
        ("xoxb-123456789012-abcdef", "R-KEY-SLACK"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4f", "R-JWT"),
        ("Bearer abcdefgh12345678", "R-BEARER"),
        ("postgres://admin:p4ssw0rd@db.internal:5432/app", "R-URLCRED"),
        ("mongodb+srv://user:pw@cluster.example.net/db", "R-CONN"),
        ("https://cdn.corp-assets.example/static/app.js", "R-URL"),
        ("file:///C:/notes/secret.txt", "R-FILEURI"),
        ("Set-Cookie: sessionid=abcdef0123456789; Path=/", "R-COOKIE"),
        ("C:\\Users\\demo\\Documents\\\u9879\u76ee\\\u62a5\u544a.md", "R-WINPATH"),
        ("C://Users//demo//app//config.ini", "R-WINPATH"),
        ("/home/demo/work/notes.md", "R-POSIXPATH"),
        ("/root/.ssh/config", "R-ROOTPATH"),
    ]
    for sample, rule in leak_samples:
        counts = {}
        out = rd.redact_text(sample, counts)
        check("脱敏命中 {} -> {}".format(rule, out), rule in counts and sample not in out)
    safe_samples = [
        "修复了 tests 目录下的解析逻辑",
        "步骤 3 完成，共 12 个工具调用",
        "source_ref: s1/L42/j/toolCalls[0].callId",
        "[REDACTED:R-KEY-OPENAI] 与 [PATH] 与 已投递",
    ]
    for sample in safe_samples:
        out = rd.redact_text(sample)
        check("脱敏不误伤: {}...".format(sample[:20]), out == sample)

    # 转义向量
    esc_cases = [
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ('<img src=x onerror="y">', "&lt;img src=x onerror=&quot;y&quot;&gt;"),
        ("a&b", "a&amp;b"),
    ]
    for raw, want in esc_cases:
        check("HTML 转义: {}...".format(raw[:20]), bc.esc(raw) == want)

    # 证据判定向量（五级 + Automation 封顶 + 词表外降档）
    evidence_cases = [
        ({"text": "已修复该问题"}, [{"etype": "check", "status": "fail"}], "failed"),
        ({"text": "已修复该问题"}, [{"etype": "check", "status": "pass"}], "external-verification"),
        ({"text": "已修复该问题"}, [{"etype": "tool_call"}], "tool-evidence"),
        ({"text": "已修复该问题"}, [], "unverified"),
        ({"text": "分析了现有实现"}, [], "self-report"),
    ]
    for claim, records, want in evidence_cases:
        got = rm.decide_evidence(claim, records)["level"]
        check("证据判定 {} -> {}".format(
            [r.get("status", r.get("etype")) for r in records] or claim["text"], got), got == want)
    check("Automation 封顶", rm.automation_cap("external-verification") == "tool-evidence")
    got = rm.decide_evidence({"text": "已修复"}, [{"etype": "check", "status": "yellow"}])
    check("词表外状态降档 + warning", got["level"] in ("unverified", "tool-evidence") and got["warnings"])

    # 幂等向量：同一输入两次脱敏 / 两次渲染逐字节一致
    tree = {"a": "sk-abcdef0123456789abcdef01", "b": ["C:\\Users\\\u4e2d\u6587\\x.md", {"cookie": "abc=1"}]}
    once, _ = rd.redact_tree(tree)
    twice, _ = rd.redact_tree(once)
    check("脱敏幂等", once == twice)
    synth_run = {
        "schema_version": rm.SCHEMA_VERSION,
        "generator": {"name": rm.GENERATOR_NAME, "version": rm.GENERATOR_VERSION},
        "source": {"kind": "dsh-jsonl", "mode": "full",
                   "inputs": [{"ordinal": 1, "name": "selftest.jsonl", "record_count": 2}],
                   "contract_version": "v2", "degradations": []},
        "task": {"goal": "自检合成任务", "started_at": None, "ended_at": None},
        "steps": [{"id": "step-1", "title": "改动", "source_ref": "s1/L2/j/type",
                   "tool_call_ids": ["tc-1"], "ts": None, "unknown_fields": []}],
        "tool_calls": [{"id": "tc-1", "name": "edit", "call_id": "call-1", "status": "ok",
                        "ts": None, "duration_ms": 12, "source_ref": "s1/L3/j/callId"}],
        "deliverables": [{"id": "d-1", "path": "out.md", "kind": "file", "source_ref": "s1/L2/j/type",
                          "evidence": {"level": "tool-evidence", "verification": "unverified"}}],
        "claims": [{"id": "c-1", "text": "已修复", "source_ref": "s1/L2/j/type",
                    "evidence_level": "tool-evidence", "verification": "unverified",
                    "verification_refs": ["tc-1"]}],
        "automation": [],
        "metrics": {},
        "narrative": None,
        "narrative_check": {"passed": False, "violations": [], "reason": "no-narrative"},
        "warnings": [],
        "redaction": {"applied": [], "residual_scan": "passed"},
    }
    h1, h2 = bc.render_html(synth_run), bc.render_html(synth_run)
    m1, m2 = bc.render_markdown(synth_run), bc.render_markdown(synth_run)
    check("渲染幂等（HTML/MD 逐字节一致）", h1 == h2 and m1 == m2)
    check("产物无脚本标签", "<script" not in h1.lower())
    check("产物无外链协议", "https://" not in h1 and "http://" not in h1 and "file://" not in h1)

    print("=" * 40)
    print("--selftest {}".format("全部通过" if ok_all else "存在失败项"))
    return EXIT_OK if ok_all else EXIT_BUILD


def run_fixtures():
    manifest = SKILL_ROOT / "tests" / "fixtures" / "fixtures.json"
    if not manifest.is_file():
        print("回归集清单不存在: {}".format(manifest))
        print("说明：完整 fixtures（good/bad 样本）由下一批次提供；"
              "本 CLI 已具备 --fixtures 接入点，清单就位后即可运行。")
        return EXIT_USAGE
    cases = json.loads(manifest.read_text(encoding="utf-8")).get("cases", [])
    failures = []
    import tempfile
    import subprocess
    for case in cases:
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "out"
            outdir.mkdir(parents=True, exist_ok=True)
            inp = Path(case["input"])
            if not inp.is_absolute():
                inp = SKILL_ROOT / inp
            cmd = [sys.executable, str(SCRIPT_DIR / "casebook.py"), "all",
                   str(inp), "--out", str(outdir)]
            if case.get("narrative"):
                nar = Path(case["narrative"])
                if not nar.is_absolute():
                    nar = SKILL_ROOT / nar
                cmd += ["--narrative", str(nar)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            got = proc.returncode
            want = case.get("expect_exit", 0)
            name = case.get("name", str(inp))
            if got != want:
                failures.append("{}: 期望 exit {}，实际 exit {}（stderr: {}）".format(
                    name, want, got, (proc.stderr or proc.stdout).strip()[:200]))
                continue
            products = ("casebook.html", "casebook.md", "run.json")
            if want == 0 and not all((outdir / f).is_file() for f in products):
                failures.append("{}: 期望成功但三件产物不齐".format(name))
            if want != 0 and any((outdir / f).exists() for f in products):
                failures.append("{}: 失败用例不应落盘产物".format(name))
    if failures:
        print("--fixtures 失败:")
        for f in failures:
            print("  - " + f)
        return EXIT_BUILD
    print("--fixtures 回归全过（{} 例）".format(len(cases)))
    return EXIT_OK


# ── CLI ─────────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="casebook.py",
        description="agent-run-casebook：把一次 Agent 运行导出变成可核验的离线案例页。")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("normalize", help="识别并解析输入，生成原始 run 模型（未脱敏）")
    p.add_argument("input")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("validate", help="schema / 引用 / narrative 白名单校验")
    p.add_argument("dir")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("redact", help="全树脱敏 run.raw.json → run.json（残留扫描硬门）")
    p.add_argument("dir")
    p.add_argument("--narrative", default=None)
    p.set_defaults(func=cmd_redact)

    p = sub.add_parser("build", help="渲染 casebook.html / casebook.md / run.json")
    p.add_argument("dir")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("all", help="normalize→validate→redact→build 全内存串联")
    p.add_argument("input")
    p.add_argument("--out", required=True)
    p.add_argument("--narrative", default=None)
    p.set_defaults(func=cmd_all)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if "--selftest" in argv:
        return selftest()
    if "--fixtures" in argv:
        return run_fixtures()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
