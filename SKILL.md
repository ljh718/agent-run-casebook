---
name: agent-run-casebook
description: 把用户明确提供的一次 Agent 运行导出（DSH /export ZIP、session JSONL 或结构化会话 Markdown）解析、脱敏并渲染成可核验的离线单文件案例页：任务目标、关键路径、交付物、五级证据面板与来源锚点一一对应。当用户要求把 /export 或会话记录整理成案例页、复盘页或可分享页，或按证据分级整理一次运行成果时使用；不做逐帧回放、跨 Agent 对比、日报聚合，也不自动扫描个人目录或发布到任何平台。Turn an explicitly provided Agent run export (DSH /export ZIP, session JSONL, or structured Markdown) into a verifiable offline single-file casebook with five-level evidence grading and traceable source anchors. Use when the user asks to turn an export or session log into a shareable review page; not for full replay, cross-agent diffing, daily digests, auto-publishing, or scanning personal directories.
description_zh: 把一次 Agent 运行导出变成可核验、可分享的离线案例页：五级证据分级、全树脱敏、来源锚点可回溯，缺失指标不估算。
description_en: Turn one Agent run export into a verifiable, shareable offline casebook with five-level evidence grading, full-tree redaction, and traceable source anchors.
display_name: Agent 运行案例册
display_name_en: Agent Run Casebook
category: productivity
examples_zh:
  - "把这个 DSH /export 导出整理成可分享的案例页。"
  - "读取这份 session.v2.jsonl，生成带证据分级的运行报告。"
  - "把这次失败测试到回归通过的过程整理成复盘页。"
examples_en:
  - "Turn this DSH /export archive into a shareable casebook."
  - "Read this session.v2.jsonl and build an evidence-graded run report."
  - "Summarize this failing-test-to-passing-regression run for review."
version: 1.0.1
author: 刘俊涵
agent_created: true
---

# Agent 运行案例册

把一次 Agent 运行导出变成可核验、可演示、可分享的离线单文件案例页。做：解析归一化、五级证据分级、全树脱敏、无 JavaScript 离线渲染、来源锚点回溯。不做：逐帧回放、跨 Agent 对比、日报聚合、自动发布、读取实时会话、估算缺失指标。

## 触发条件

应触发：

- 用户提供 DSH /export ZIP，要求整理成案例页、复盘页或可分享页。
- 用户给出 session.v2.jsonl 或 session.jsonl，要求生成运行报告。
- 用户粘贴结构化会话 Markdown（用户 / 助手 / 工具标题），要求按证据分级整理成果。
- 用户要求把一次「失败测试 → 修改 → 回归通过」的任务整理成可核验材料。

不应触发：

- 只想逐帧回放原始轨迹。
- 想跨多个 Agent 对比同一任务。
- 想按天聚合生成日报或周报。
- 想自动抓取个人目录里的历史会话或实时会话。

## 工作流程

1. 识别用户明确提供的输入文件（ZIP / JSONL / Markdown）；识别规则与降级口径见 references/input-contract.md。
2. 运行 `python scripts/casebook.py normalize <输入> --out <工作目录>` 生成原始运行模型；该中间文件含未脱敏内容，不得分享给用户。
3. 依据事实筛选 3-7 个关键节点、撰写面向读者的标题与摘要，产出叙事文件；叙事只能改表述、选步骤、加读者解释，不得新增事实、指标、交付物或证据等级。schema 与白名单规则见 references/api_reference.md。
4. 运行 `python scripts/casebook.py all <输入> --out <输出目录> --narrative <叙事文件路径>` 完成校验、脱敏与构建；无叙事时省略 --narrative 参数按事实模式渲染；也可分步运行 validate / redact / build。
5. 向用户报告产物路径、证据分级摘要与降级说明；叙事核验未通过时如实说明已按事实模式渲染。

## 输出规范

- 三件产物写入 --out 指定目录：casebook.html（离线单文件页）、casebook.md（Markdown 摘要）、run.json（脱敏后的运行模型）。
- 缺失指标（耗时 / Token / 成本）整个区块不渲染、不估算；文本模式在页面明示降级。
- 无复验记录的主张显示「未验证」；Automation 投递只显示「已投递」。

## 注意事项

- 证据等级只由脚本按检查记录确定性判定，叙事文件中不得携带或修改等级；等级定义见 references/evidence-model.md。
- 脱敏残留扫描为硬门：不通过即非零退出且不产出任何文件。
- 当前无真实 DSH 导出样本，验收基于符合官方契约的人工构造样例；真实样本验证待用户提供导出后补充，适配说明与已知限制见 references/dsh-export.md。
- 脚本资源以技能目录为基准（内部按脚本自身位置解析），与调用时的工作目录无关。
- CLI 子命令、退出码与运行模型字段见 references/api_reference.md。

## 自检与示例

- 结构自检：`python scripts/casebook.py --selftest`；回归集：`python scripts/casebook.py --fixtures`，样本定义在 tests/fixtures/fixtures.json。
- examples/ 目录提供三个人工案例（bugfix / research-report / data-analysis），可用 `python scripts/example.py --out <目录>` 一键演示；构建产物不随技能分发。
