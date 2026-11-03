# 案例说明：失败测试 → 修改 → 回归通过（完整模式 + 有叙事，主推示例）

## 场景

一次典型的缺陷修复运行：先复现失败，第一次修复未过回归，补边界用例后通过。
输入为本目录下的 input.jsonl（人工构造、完全脱敏、符合导出契约）。
本目录另含 narrative.json（通过全部白名单核验的合法叙事），
`python scripts/example.py` 会自动以 `--narrative` 构建本案例——
这是「完整模式 + 有叙事」的主推示例，页面包含叙事概览与关键路径锚点。

## 预期页面要点

- 页面顶部无降级横幅（完整模式）；标题取自 narrative.json。
- 首条修复主张显示「验证失败」徽标：其后的检查记录为 fail。
- 最终主张显示「外部复验」徽标：紧邻其前的检查记录为 pass，
  体现 failed 到 external-verification 的演进。
- 证据面板同时包含标记词命中句与普通 assistant 陈述（后者仅作 Agent 自报）。
- 两个交付物卡片：src/dateutils.py 与 docs/fix-notes.md，均带证据徽标与来源锚点。
- 完整时间线折叠展示四个步骤与三次工具调用（状态与耗时来自源数据，
  耗时以人性化格式显示、原始毫秒保留在 title 与 run.json）。
- 产物为四件：casebook.html / casebook.md / run.json / redaction-report.txt
  （报告为本地审计用，不可分享）。

## 构建方式

python scripts/casebook.py all input.jsonl --out <输出目录> --narrative narrative.json

无叙事时省略 --narrative 参数按事实模式渲染；自定义词条脱敏可加
--denylist <文件>（每行一个词条，用于客户名 / 公司名等自然语言实体）。
