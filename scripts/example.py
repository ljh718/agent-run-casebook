#!/usr/bin/env python3
"""example.py — examples 演示运行器（原占位脚本改造，文件名不变、内容替换）。

用途：把 examples/ 下的三个人工案例（01-bugfix / 02-research-report /
03-data-analysis）依次交给 casebook.py all 构建，产物写入指定输出目录，
用于安装后的快速演示与验收。

用法：
    python scripts/example.py [--out 输出目录]
缺省输出目录为系统临时目录下的 casebook-examples 子目录；产物不写入技能目录。

退出码：0 全部案例成功；1 存在失败案例；2 用法错误或 examples 目录缺失。
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
CASEBOOK = SCRIPT_DIR / "casebook.py"
EXAMPLES_DIR = SKILL_ROOT / "examples"

EXAMPLE_NAMES = ("01-bugfix", "02-research-report", "03-data-analysis")
PRODUCTS = ("casebook.html", "casebook.md", "run.json", "redaction-report.txt")


def find_input(case_dir):
    for name in sorted(case_dir.iterdir()):
        if name.is_file() and name.suffix.lower() in (".jsonl", ".md", ".zip"):
            return name
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="example.py",
        description="agent-run-casebook 示例运行器：把 examples 下的人工案例各构建一遍。")
    parser.add_argument("--out", default=None, help="产物输出目录（默认系统临时目录）")
    args = parser.parse_args(argv)

    if not EXAMPLES_DIR.is_dir():
        print("examples 目录不存在: {}".format(EXAMPLES_DIR))
        return 2
    out_root = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "casebook-examples"
    print("输出目录: {}".format(out_root))
    failures = []
    for name in EXAMPLE_NAMES:
        case_dir = EXAMPLES_DIR / name
        input_path = find_input(case_dir) if case_dir.is_dir() else None
        if input_path is None:
            print("[跳过] {}：无可用输入（缺 examples 案例或说明见其 notes.md）".format(name))
            failures.append(name)
            continue
        outdir = out_root / name
        cmd = [sys.executable, str(CASEBOOK), "all", str(input_path), "--out", str(outdir)]
        # P2-2：案例目录含 narrative.json 时按叙事版构建（01-bugfix 为完整模式 + 有叙事的主推示例）
        narr = case_dir / "narrative.json"
        if narr.is_file():
            cmd += ["--narrative", str(narr)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        ok = proc.returncode == 0 and all((outdir / p).is_file() for p in PRODUCTS)
        print("[{}] {} -> exit {}".format("成功" if ok else "失败", name, proc.returncode))
        if not ok:
            print((proc.stderr or proc.stdout or "").strip()[:500])
            failures.append(name)
        else:
            for p in PRODUCTS:
                print("    产物: {}".format(outdir / p))
    if failures:
        print("失败案例: {}".format(", ".join(failures)))
        return 1
    print("全部示例构建成功；产物未写入技能目录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
