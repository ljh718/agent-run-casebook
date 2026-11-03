# 案例说明：失败测试 → 修改 → 回归通过

## 场景

一次典型的缺陷修复运行：先复现失败，第一次修复未过回归，补边界用例后通过。
输入为本目录下的 input.jsonl（人工构造、完全脱敏、符合导出契约）。

## 预期页面要点

- 首条修复主张显示「验证失败」徽标：其后的检查记录为 fail。
- 最终主张显示「外部复验」徽标：紧邻其前的检查记录为 pass，
  体现 failed 到 external-verification 的演进。
- 两个交付物卡片：src/dateutils.py 与 docs/fix-notes.md，均带证据徽标与来源锚点。
- 完整时间线折叠展示四个步骤与三次工具调用（状态与耗时来自源数据）。

## 构建方式

python scripts/casebook.py all input.jsonl --out <输出目录>

可选：按 references/api_reference.md 的叙事协议写一个 narrative 文件，
加 --narrative 参数体验叙事版页面；无叙事时按事实模式渲染。
