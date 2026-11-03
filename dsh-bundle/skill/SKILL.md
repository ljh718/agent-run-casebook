---
name: agent-run-casebook
description: 把用户明确提供的一次 Agent 运行导出（DSH /export ZIP、session JSONL 或结构化会话 Markdown）解析、脱敏并渲染成可核验的离线单文件案例页：任务目标、关键路径、交付物、五级证据面板与来源锚点一一对应。当用户要求把 /export 或会话记录整理成案例页、复盘页或可分享页，或按证据分级整理一次运行成果时使用；不做逐帧回放、跨 Agent 对比、日报聚合，也不自动扫描个人目录或发布到任何平台。Turn an explicitly provided Agent run export (DSH /export ZIP, session JSONL, or structured Markdown) into a verifiable offline single-file casebook with five-level evidence grading and traceable source anchors. Use when the user asks to turn an export or session log into a shareable review page; not for full replay, cross-agent diffing, daily digests, auto-publishing, or scanning personal directories.
description_zh: 把一次 Agent 运行导出变成可核验、可分享的离线案例页：五级证据分级、全树脱敏、来源锚点可回溯，缺失指标不估算。
description_en: Turn one Agent run export into a verifiable, shareable offline casebook with five-level evidence grading, full-tree redaction, and traceable source anchors.
display_name: Agent 运行报告生成器
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
version: 1.2.1
author: 刘俊涵
agent_created: true
---

# Agent 运行案例册

把一次 Agent 运行导出变成可核验、可演示、可分享的离线单文件案例页。做：解析归一化、五级证据分级、全树脱敏、无 JavaScript 离线渲染、来源锚点回溯。不做：逐帧回放、跨 Agent 对比、日报聚合、自动发布、读取实时会话、估算缺失指标。

## 触发条件

应触发：

- 用户提供 DSH /export ZIP，要求整理成案例页、复盘页或可分享页。
- 用户给出 session.v2.jsonl、session.v4.jsonl 或 session.jsonl，要求生成运行报告。
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
4. 运行 `python scripts/casebook.py all <输入> --out <输出目录> --narrative <叙事文件路径> [--denylist <词条文件>]` 完成校验、脱敏与构建；无叙事时省略 --narrative 参数按事实模式渲染；也可分步运行 validate / redact / build。姓名、公司名等自然语言实体不自动脱敏，请通过 --denylist 词条文件提供（每行一个词条，UTF-8，# 注释）。
5. 向用户报告产物路径、证据分级摘要与降级说明；叙事核验未通过时如实说明已按事实模式渲染。

## 输出规范

- 四件产物写入 --out 指定目录：casebook.html（离线单文件页）、casebook.md（Markdown 摘要）、run.json（脱敏后的运行模型）、redaction-report.txt（脱敏审计报告）。
- **可分享候选产物为 casebook.html / casebook.md / run.json**（页面与运行模型不含原文敏感片段）；**redaction-report.txt 为本地审计用，不可分享**，仅供使用者复核脱敏是否有误伤。报告含原文片段的版本由 all / redact 阶段生成；分步流程中 build 从 run.json 重建的报告不含原文（同目录已存在时不覆盖，保留含原文版本）。
- 主张抽取覆盖：证据面板同时包含标记词命中句（进入五级判定）与普通 assistant 陈述（仅作 Agent 自报，不因工具或检查记录升级；claim_origin 区分 marker / statement）。
- 缺失指标（耗时 / Token / 成本）整个区块不渲染、不估算；页面耗时以人性化格式显示（如 6 分 00 秒），原始毫秒保留在 run.json 与悬停提示中。
- 文本模式与契约版本不匹配时，页面顶部显示显著降级横幅；文本模式的证据强度上限说明见 references/input-contract.md。
- 无复验记录的主张显示「未验证」；Automation 投递只显示「已投递」。

## 注意事项

- 证据等级只由脚本按检查记录确定性判定，叙事文件中不得携带或修改等级；等级定义见 references/evidence-model.md。
- 脱敏残留扫描为硬门：不通过即非零退出且不产出任何文件。残留扫描是**两套独立机制**：
  （1）规则复检——把生效脱敏规则在最终产物上重跑一遍（占位符不计），验证替换确实生效；
  （2）独立宽形态探测（RESIDUAL_SUSPICIOUS）——检测集刻意比替换集宽、且不同源，只查不改，
  专用于发现「替换规则漏掉了什么」。默认 `--strict-pii` 开启，形态探测命中即 exit 5 不落盘
  （fail-closed，要求使用者清洗输入后重建）；`--no-strict-pii` 时放行，但逐条记 `PII_SUSPECTED`
  警告（含 JSON 路径 source_ref），由使用者自行复核清洗。
- URL 分级脱敏（默认档）：保留 http(s) 的 host+path 作为引用出处，抹除 query（可能携带
  token）与内网域名（corp / internal / intra / local / lan / office）；URL 内嵌凭据一律抹除。
  `--no-urls` 恢复全抹（旧行为）；`--keep-urls` 连 query 与内网域名也放行，仅保留凭据兜底。
  残留扫描相应只对「带 userinfo 凭据的外链」与文件协议（file scheme）外链保持绝对禁止，普通外链放行。
  独立形态探测兜底：query 中的高风险键（access_token / token / secret / api_key /
  apikey / session / sid / auth / code 等）一旦出现在可分享产物中，默认 strict 模式
  exit 5（含 keep-urls 档显式保留的 query）；需清洗输入或改用 `--no-strict-pii`。
- PII 规则覆盖私钥块、中国身份证、中国手机号、银行卡、IPv4、邮箱与「密码/口令/password」
  前缀的自然语言明文凭据；姓名、公司名等自然语言实体不在自动脱敏范围，请用
  `--denylist <文件>` 提供词条（命中替换为 [REDACTED:R-DENYLIST]，计入审计报告）。
  长数字形态探测可能对 11 位以上流水号/时间戳误报（默认硬门拦截），属「宁多脱不少漏」的
  有意取舍；确需放行请使用 `--no-strict-pii` 并按 PII_SUSPECTED 警告逐条复核。
- v1.2.0 起支持 DSH 官方信封事件格式（type 形如 user/message / assistant/message /
  tool/call / tool/result，头行 type=session 携带 version）：契约版本 v2 与 v4 为已知，
  其他版本整体降级并出警告；未识别的信封事件类型只记 UNKNOWN_FIELD 警告并保留来源
  引用，不猜语义、不生成 user/assistant/claim 事件。适配说明、真实内部持久化形态
  （session.v4.jsonl.zstd，多帧 zstd）与已知限制见 references/dsh-export.md。
- 脚本资源以技能目录为基准（内部按脚本自身位置解析），与调用时的工作目录无关。
- CLI 子命令、退出码与运行模型字段见 references/api_reference.md。

## 自检与示例

- 结构自检：`python scripts/casebook.py --selftest`；回归集：`python scripts/casebook.py --fixtures`，样本定义在 tests/fixtures/fixtures.json。
- examples/ 目录提供三个人工案例（bugfix / research-report / data-analysis），可用 `python scripts/example.py --out <目录>` 一键演示；01-bugfix 为「完整模式 + 有叙事」的主推示例（含 narrative.json）；构建产物不随技能分发。
