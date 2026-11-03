#!/usr/bin/env python3
"""casebook.py — agent-run-casebook 唯一 CLI 入口。

子命令（设计蓝图 3）：
    normalize <input> --out <dir>          解析输入 → run.raw.json（未脱敏，带醒目警告）+ normalize.report.json
    validate  <dir>                        schema / 引用 / narrative 白名单校验 → validate.report.json
    redact    <dir> [--narrative <file>]   全树脱敏 run.raw.json（+ 可选 narrative）→ run.json
    build     <dir> [--out <dir>]          渲染 casebook.html / casebook.md（+ run.json 原子副本）
    all       <input> --out <dir> [--narrative <file>] [--denylist <file>]
                                           normalize→validate→redact→build 全内存串联，只落四件产物
    --selftest                             内置自检：脱敏 / 转义 / 证据判定 / 幂等向量
    --fixtures                             按 tests/fixtures/fixtures.json 跑回归集（缺失时清晰报错）

脱敏档位（redact / build / all 共用）：
    --strict-pii / --no-strict-pii         独立宽形态探测（RESIDUAL_SUSPICIOUS）硬门开关，默认开；
                                           关闭时命中仅记 PII_SUSPECTED 警告放行
    --no-urls                              旧行为：所有 http(s) URL 全抹
    --keep-urls                            host+path 与 query 原样保留（内网域名也放行），
                                           仅 URL 凭据兜底；query 含高风险键
                                           （access_token / token / secret 等）时仍被
                                           strict 硬门拦截，需清洗或 --no-strict-pii
    --denylist <file>                      自定义词条脱敏（all / redact；UTF-8 每行一词条，
                                           # 注释；普通字符串替换，长度降序）
    （默认：保留 host+path 作为出处，抹 query 与内网域名）

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


REPORT_NAME = "redaction-report.txt"
PRODUCTS = ("casebook.html", "casebook.md", "run.json", REPORT_NAME)


def _audit_entries(audit):
    """为审计明细分配确定性 detail_id（run.json 与报告共用同一编号）。"""
    return [dict(e, detail_id="d{}".format(i + 1)) for i, e in enumerate(audit or [])]


def _redaction_stats(counts, strict_pii=True, url_mode="default", entries=(),
                     denylist=()):
    """P2-6：redaction 统计块。applied 按实际替换次数；details 不含原文片段
    （snippet 只进 redaction-report.txt，run.json 保持可分享）。"""
    details = [{k: ent[k] for k in ("detail_id", "source_ref", "rule_id",
                                    "replacement", "offset", "length")}
               for ent in list(entries)[:rd.DETAIL_RUNJSON_LIMIT]]
    return {"applied": [{"rule": k, "count": v} for k, v in sorted(counts.items())],
            "residual_scan": "passed",
            "strict_pii": bool(strict_pii),
            "url_mode": url_mode,
            "denylist_terms": len({t for t in denylist if t}),
            "details_total": len(list(entries)),
            "details": details}


def _write_redaction_report(outdir, entries):
    """P2-3 / P2-6：脱敏审计报告（含原文片段）。本地审计用，明确标注不可分享；
    由 emit_atomic 硬门之外单独落盘（硬门产物保持零明文）。"""
    def clean(cell):
        return str(cell).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
    lines = [
        "# agent-run-casebook 脱敏审计报告（{}）".format(REPORT_NAME),
        "# 本地审计用，不可分享：本文件包含被替换的原文敏感片段。",
        "# 可分享产物为 casebook.html / casebook.md / run.json（均不含原文敏感片段）；本文件仅用于人工复核脱敏是否误伤。",
        "# 偏移为该规则应用时文本坐标（信息性）；词条命中按长度降序替换。",
        "",
        "detail_id\tsource_ref\trule_id\toffset\tlength\t原文片段\t占位符",
    ]
    for e in entries:
        snippet = e.get("snippet", "（run.json 不含原文片段；原文仅见于 redact/all 阶段生成的报告）")
        lines.append("\t".join([
            clean(e.get("detail_id", "")), clean(e.get("source_ref", "")),
            clean(e.get("rule_id", "")), str(e.get("offset", "")),
            str(e.get("length", "")), clean(snippet), clean(e.get("replacement", ""))]))
    _write(Path(outdir) / REPORT_NAME, "\n".join(lines) + "\n")


def _load_denylist_or_exit2(path):
    """--denylist 文件缺失或不可读 → 用法错误（exit 2）。"""
    p = Path(path)
    if not p.is_file():
        print("denylist 文件不存在: {}".format(p))
        return False
    try:
        return rd.load_denylist(p)
    except (OSError, UnicodeDecodeError) as exc:
        print("denylist 文件读取失败（需 UTF-8）: {}".format(exc))
        return False


def _url_mode(args):
    """URL 分级档位：--no-urls 全抹 / --keep-urls 保留 query（风险键仍被 strict 硬门拦截）/ 默认保留 host+path。"""
    if getattr(args, "no_urls", False):
        return "no-urls"
    if getattr(args, "keep_urls", False):
        return "keep-urls"
    return "default"


def _handle_suspects(redacted, strict_pii):
    """独立宽形态探测（RESIDUAL_SUSPICIOUS，与替换集不同源）。
    strict：命中即硬门拒绝（调用方负责返回 exit 5）；宽松：记 PII_SUSPECTED 警告放行。
    返回 (suspects, blocked)。"""
    suspects = rd.suspect_scan_tree(redacted)
    if not suspects:
        return [], False
    if strict_pii:
        return suspects, True
    for rid, path in suspects:
        redacted.setdefault("warnings", []).append({
            "code": "PII_SUSPECTED", "source_ref": path,
            "detail": "形态探测命中疑似敏感信息（--no-strict-pii 已放行，建议人工清洗输入后重建）: {}".format(rid)})
    return suspects, False


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
    denylist = ()
    if getattr(args, "denylist", None):
        denylist = _load_denylist_or_exit2(args.denylist)
        if denylist is False:
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
    audit = []
    redacted, counts = rd.redact_tree(run, url_mode=_url_mode(args),
                                      denylist=denylist, audit=audit)
    entries = _audit_entries(audit)
    redacted["redaction"] = _redaction_stats(counts, args.strict_pii,
                                             _url_mode(args), entries, denylist)
    suspects, blocked = _handle_suspects(redacted, args.strict_pii)
    if blocked:
        detail = "; ".join("{}@{}".format(r, p) for r, p in suspects[:10])
        print("残留扫描（独立宽形态探测）不通过（硬门），run.json 不落盘。命中: {}".format(detail))
        return EXIT_REDACT
    payload = (_dump(redacted) + "\n").encode("utf-8")
    hits = rd.residual_scan_bytes(payload, strict_pii=args.strict_pii,
                                  url_mode=_url_mode(args), denylist=denylist)
    if hits:
        print("残留扫描不通过（硬门），run.json 不落盘。命中: {}".format(", ".join(hits)))
        return EXIT_REDACT
    outdir = Path(args.dir)
    outdir.mkdir(parents=True, exist_ok=True)
    _write(outdir / "run.json", payload.decode("utf-8"))
    _write_redaction_report(outdir, entries)
    print("redact 完成 → {}".format(outdir / "run.json"))
    print("脱敏审计报告（本地审计用，不可分享）→ {}".format(outdir / REPORT_NAME))
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
        }, strict_pii=args.strict_pii, url_mode=_url_mode(args))
    except rd.ResidualLeakError as exc:
        print("残留扫描不通过（硬门），产物不落盘。{}".format(exc))
        return EXIT_REDACT
    # P2-3：build 从 run.json.details 重建审计报告（不含原文片段；
    # 原文片段仅存在于 redact / all 阶段生成的报告——同目录已存在时不覆盖）
    report_path = outdir / REPORT_NAME
    if report_path.is_file():
        print("脱敏审计报告已存在，保留 redact/all 阶段版本（含原文片段）: {}".format(report_path))
    else:
        _write_redaction_report(outdir, run.get("redaction", {}).get("details", []))
    for p in paths:
        print("产物: {}".format(p))
    return EXIT_OK


def cmd_all(args):
    """主路径：全内存串联，中间模型不落盘；只落四件最终产物。"""
    denylist = ()
    if getattr(args, "denylist", None):
        denylist = _load_denylist_or_exit2(args.denylist)
        if denylist is False:
            return EXIT_USAGE
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

    audit = []
    redacted, counts = rd.redact_tree(run, url_mode=_url_mode(args),
                                      denylist=denylist, audit=audit)
    entries = _audit_entries(audit)
    redacted["redaction"] = _redaction_stats(counts, args.strict_pii,
                                             _url_mode(args), entries, denylist)
    suspects, blocked = _handle_suspects(redacted, args.strict_pii)
    if blocked:
        detail = "; ".join("{}@{}".format(r, p) for r, p in suspects[:10])
        print("残留扫描（独立宽形态探测）不通过（硬门），产物不落盘。命中: {}".format(detail))
        return EXIT_REDACT
    if suspects:
        print("提示：--no-strict-pii 下检测到 {} 处疑似敏感信息，已记入 warnings（PII_SUSPECTED），"
              "产物仍会写出，请人工复核清洗。".format(len(suspects)))
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
        }, strict_pii=args.strict_pii, url_mode=_url_mode(args), denylist=denylist)
    except rd.ResidualLeakError as exc:
        print("残留扫描不通过（硬门），产物不落盘。{}".format(exc))
        return EXIT_REDACT
    # P2-3：审计报告在硬门产物之后单独落盘（含原文片段，不可分享，不参与残留扫描）
    _write_redaction_report(outdir, entries)
    print("all 完成：{} 条记录，{} 警告，{} 降级。".format(
        report["record_count"], len(redacted.get("warnings", [])), report["parse_errors"]))
    src = redacted.get("source", {})
    if any(w.get("code") == "CONTRACT_VERSION_MISMATCH" for w in redacted.get("warnings", [])) \
            or (src.get("contract_version") == "unknown"
                and src.get("kind") in ("dsh-zip", "dsh-jsonl")):
        print("提示：输入契约版本未被当前版本锁定，部分字段可能无法识别、整体降级；"
              "页面顶部已显示横幅。如可提供真实 DSH /export 导出样本，可据此完成适配。")
    levels = {}
    for c in redacted.get("claims", []):
        levels[c["evidence_level"]] = levels.get(c["evidence_level"], 0) + 1
    print("证据分级摘要: {}".format(
        json.dumps(levels, ensure_ascii=False) if levels else "（无主张记录）"))
    if report["parse_errors"] or report["warnings"]:
        print("降级说明：部分记录不可用或字段未识别，详见产物「复现与未知事项」区块。")
    for p in paths:
        print("产物: {}".format(p))
    print("产物: {}（本地审计用，不可分享）".format(outdir / REPORT_NAME))
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
        ("https://api.example.com/cb?access_token=abc123", "R-URL-QUERY"),
        ("https://wiki.corp.cn/rag-eval", "R-URL-INTERNAL"),
        ("xhttps://keys.internal/leak", "R-URL-INTERNAL"),
        ("file:///C:/notes/secret.txt", "R-FILEURI"),
        ("Set-Cookie: sessionid=abcdef0123456789; Path=/", "R-COOKIE"),
        ("-----BEGIN OPENSSL PRIVATE KEY-----\nMIIEvQIB\n-----END OPENSSL PRIVATE KEY-----",
         "R-PRIVKEY"),
        ("-----BEGIN OPENSSL PRIVATE KEY-----", "R-PRIVKEY"),
        ("110105199003074512", "R-CN-ID"),
        ("13812345678", "R-CN-MOBILE"),
        ("138-1234-5678", "R-CN-MOBILE"),
        ("+86 138-1234-5678", "R-CN-MOBILE"),
        ("6222021234567890123", "R-BANKCARD"),
        ("部署到 106.53.62.135", "R-IPV4"),
        ("zhang.wei@corp.cn", "R-EMAIL"),
        ("服务器密码 Ljh071823!", "R-INLINE-CRED"),
        ("password=hunter2x", "R-INLINE-CRED"),
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
        "参考 https://arxiv.org/abs/2309.15217 与 https://docs.ragas.io/en/stable/ 撰写。",
    ]
    for sample in safe_samples:
        out = rd.redact_text(sample)
        check("脱敏不误伤: {}...".format(sample[:20]), out == sample)

    # URL 分级向量：默认保留 host+path、抹 query、抹内网域名；档位行为各自生效
    out = rd.redact_text("见 https://api.example.com/cb?access_token=abc123 说明")
    check("URL 默认档保留 host+path", "https://api.example.com/cb" in out)
    check("URL 默认档抹 query", "access_token" not in out)
    check("URL 默认档保留公网外链",
          rd.redact_text("见 https://arxiv.org/abs/2309.15217") == "见 https://arxiv.org/abs/2309.15217")
    check("URL no-urls 全抹",
          "[REDACTED:R-URL]" in rd.redact_text("见 https://arxiv.org/abs/2309.15217", url_mode="no-urls"))
    check("URL keep-urls 放行 query",
          "access_token" in rd.redact_text("https://api.example.com/cb?access_token=abc123",
                                           url_mode="keep-urls"))

    # 残留扫描向量：规则复检剥占位符；独立宽形态探测 strict 开关；fail-closed
    check("残留扫描不误报占位符",
          rd.residual_scan_text("密码 [REDACTED:R-INLINE-CRED] [PATH] https://arxiv.org/abs/2309.15217") == [])
    check("形态探测: 长数字（strict 默认命中）",
          "R-SUS-DIGITS" in rd.residual_scan_text("订单 202611030000123"))
    check("形态探测: --no-strict-pii 跳过",
          not [h for h in rd.residual_scan_text("订单 202611030000123", strict_pii=False)
               if h.startswith("R-SUS")])
    check("形态探测: 邮箱 / IPv4 / 私钥头 / 明文凭据",
          all(rid in rd.residual_scan_text(t) for rid, t in (
              ("R-SUS-EMAIL", "mail a@b.cn"),
              ("R-SUS-IPV4", "host 10.1.2.3"),
              ("R-SUS-PRIVKEY", "-----BEGIN PRIVATE KEY-----"),
              ("R-SUS-CREDWORD", "password=abcd1234"))))
    check("形态探测: 高风险 query 键兜底",
          all(rid in rd.residual_scan_text(t) for rid, t in (
              ("R-SUS-URLKEY", "see https://a.example/cb?access_token=abc123"),
              ("R-SUS-URLKEY", "回调 https://a.example/set?sid=x1 完成"),
              ("R-SUS-URLKEY", "参数 ?client_secret=abcdef 结尾")))
          and "R-SUS-URLKEY" not in
          rd.residual_scan_text("https://a.example/cb?[REDACTED:R-URL-QUERY]"))
    check("--no-urls 档 cred URL 整体抹除且无假阳性",
          rd.redact_text("回调 https://user:secret@example.com/x", url_mode="no-urls")
          == "回调 [REDACTED:R-URL]"
          and rd.residual_scan_text("回调 [REDACTED:R-URL]", url_mode="no-urls") == [])
    check("形态探测: 定位路径",
          ("R-SUS-DIGITS", "$.claims[0].text") in rd.suspect_scan_tree(
              {"claims": [{"text": "订单 202611030000123"}]}))

    # P2-6：计数按实际替换次数累加；审计明细采集（含原文片段，仅供报告）
    counts = {}
    out = rd.redact_text("https://a.example/1 https://b.example/2 https://c.example/3",
                         counts, url_mode="no-urls")
    check("替换计数按次数累加（3 个 URL → 3）",
          counts.get("R-URL") == 3 and out.count("[REDACTED:R-URL]") == 3)
    counts = {}
    rd.redact_text("13812345678 13812345678 13812345678", counts)
    check("手机号计数 3", counts.get("R-CN-MOBILE") == 3)
    audit = []
    rd.redact_tree({"task": {"goal": "手机 13812345678 与 13987654321"}}, audit=audit)
    check("审计明细采集（含定位与原文片段）",
          len(audit) == 2 and all(a["rule_id"] == "R-CN-MOBILE" for a in audit)
          and all(a["source_ref"] == "$.task.goal" for a in audit)
          and audit[0]["snippet"] == "13812345678")

    # P2-3：denylist 普通字符串替换、长度降序、占位符保护、幂等、残留复检
    counts = {}
    out = rd.redact_text("客户张伟使用了 Atlas-内部代号", counts,
                         denylist=["Atlas-内部代号", "张伟"])
    check("denylist 命中（长度降序）",
          out == "客户[REDACTED:R-DENYLIST]使用了 [REDACTED:R-DENYLIST]"
          and counts.get("R-DENYLIST") == 2)
    check("denylist 普通字符串替换（不按 regex 解释）",
          rd.redact_text("a.c$^ 匹配测试", denylist=["c$^"]) == "a.[REDACTED:R-DENYLIST] 匹配测试")
    once = rd.redact_text("客户张伟", denylist=["张伟"])
    check("denylist 幂等", rd.redact_text(once, denylist=["张伟"]) == once)
    out = rd.redact_text("已脱敏 [REDACTED:R-URL] 与 张伟R-URL尾", denylist=["R-URL"])
    check("denylist 占位符受保护",
          out.count("[REDACTED:R-URL]") == 1 and out.endswith("[REDACTED:R-DENYLIST]尾"))
    check("denylist 残留复检命中",
          "R-DENYLIST" in rd.residual_scan_text("涉及张伟", denylist=["张伟"]))
    check("denylist 残留复检不误报占位符",
          "R-DENYLIST" not in rd.residual_scan_text(
              "[REDACTED:R-DENYLIST] 已清洗完毕", denylist=["R-URL"]))

    # P2-5：耗时人性化显示（向下取整；原始毫秒保留在 run.json 与 title）
    check("耗时格式化", bc._fmt_duration(360000) == "6 分 00 秒"
          and bc._fmt_duration(1500) == "1 秒"
          and bc._fmt_duration(80) == "80 ms"
          and bc._fmt_duration(3900000) == "1 小时 05 分 00 秒")

    # P2-1：claim_origin 常量与证据面板说明由渲染层保证（页面测试见 tests/）

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
                    "claim_origin": "marker",
                    "evidence_level": "tool-evidence", "verification": "unverified",
                    "verification_refs": ["tc-1"]}],
        "automation": [],
        "metrics": {},
        "narrative": None,
        "narrative_check": {"passed": False, "violations": [], "reason": "no-narrative"},
        "warnings": [],
        "redaction": {"applied": [], "residual_scan": "passed", "strict_pii": True,
                      "url_mode": "default", "denylist_terms": 0,
                      "details_total": 0, "details": []},
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
            products = ("casebook.html", "casebook.md", "run.json", REPORT_NAME)
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

def _add_redaction_flags(p):
    """redact / build / all 共用的脱敏档位参数。"""
    p.add_argument("--strict-pii", action=argparse.BooleanOptionalAction, default=True,
                   help="独立宽形态探测硬门（默认开；--no-strict-pii 仅记 PII_SUSPECTED 警告）")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--no-urls", action="store_true",
                   help="所有 http(s) URL 全抹（旧行为）")
    g.add_argument("--keep-urls", action="store_true",
                   help="host+path 与 query 原样保留（内网域名也放行），仅 URL 凭据兜底；"
                        "query 含高风险键（access_token / token / secret 等）时仍被 "
                        "strict 硬门拦截，需清洗或 --no-strict-pii")


def _add_denylist_flag(p):
    """P2-3：--denylist <file>（适用于 all / redact；UTF-8 每行一词条，# 注释）。"""
    p.add_argument("--denylist", default=None, metavar="FILE",
                   help="自定义脱敏词条文件（每行一个词条，普通字符串替换，不可分享产物含审计报告）")


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
    _add_redaction_flags(p)
    _add_denylist_flag(p)
    p.set_defaults(func=cmd_redact)

    p = sub.add_parser("build", help="渲染 casebook.html / casebook.md / run.json")
    p.add_argument("dir")
    p.add_argument("--out", default=None)
    _add_redaction_flags(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("all", help="normalize→validate→redact→build 全内存串联")
    p.add_argument("input")
    p.add_argument("--out", required=True)
    p.add_argument("--narrative", default=None)
    _add_redaction_flags(p)
    _add_denylist_flag(p)
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
