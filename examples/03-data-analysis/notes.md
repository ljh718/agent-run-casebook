# 案例说明：数据分析与失败复验（ZIP 导出）

## 场景

数据分析运行：CSV 数据 → 图表交付物 + 一项复验失败 + 一条 Automation 投递
记录 + 一条坏 JSONL 行。用于演示证据不夸大、「已投递」特例与部分降级。
输入为本目录下的 export.zip（人工构造、完全脱敏、符合导出契约：
data/sales.csv 数据成员 + session.v2.jsonl 会话成员）。

## 预期页面要点

- 图表交付物卡片：charts/chart-01.svg，kind 识别为 chart。
- 「已生成图表」主张显示「验证失败」徽标：紧随其后的检查记录为 fail，
  页面绝不把失败复验显示为已通过。
- Automation 记录只显示「已投递」徽标，绝不显示「已执行 / 已完成 / 已验证」；
  即使其他主张存在验收记录，也不回写投递条目。
- 降级清单含一条 PARSE_ERROR（坏 JSONL 行，PARTIAL_RECORDS）：
  页面明示部分记录不可用，不产出看似完整的成功页。
- data/sales.csv 为非会话成员，不计入记录、仅在输入来源中体现跳过计数。

## 构建方式

python scripts/casebook.py all export.zip --out <输出目录>
