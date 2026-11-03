# agent-run-casebook 变更说明

## v1.1.0（2026-11）

安全与判定修复版本（依据外部缺陷报告 P0-1 / P0-2 / P1-1 / P1-2 / P1-3）。

### 修复（P0）

- 脱敏新增 7 条 PII 规则（此前对 PII 完全失效且残留扫描误报通过）：
  私钥块（R-PRIVKEY）、中国身份证（R-CN-ID）、中国手机号（R-CN-MOBILE）、
  银行卡（R-BANKCARD）、IPv4（R-IPV4）、邮箱（R-EMAIL）、
  「密码/口令/password」前缀的自然语言明文凭据（R-INLINE-CRED）。
  附完整命中与不误伤回归向量（selftest 与单测双重覆盖）。
- 残留扫描拆分为两套独立机制，修复「检测集与替换集同源、盲区不可发现」的架构缺陷：
  （1）规则复检：生效规则表在剥占位符后的最终文本上重跑；
  （2）独立宽形态探测 RESIDUAL_SUSPICIOUS（邮箱 / 11 位以上长数字 / IPv4 / 私钥头 /
  明文凭据搭配），与替换集刻意不同源、只查不改，命中即拒绝产出（fail-closed）。
  新增 CLI 开关 `--strict-pii` / `--no-strict-pii`（默认开）；宽松模式下命中
  逐条记 `PII_SUSPECTED` 警告（含 JSON 路径 source_ref）供人工清洗定位。
- 已知取舍：长数字形态探测会对 11 位以上流水号 / 时间戳误报，属「宁可多脱」设计，
  确需放行时使用 `--no-strict-pii` 并按警告复核。

### 修复（P1）

- 叙事等级词黑名单由词表子串匹配升级为正则模式（NARRATIVE_LEVEL_PATTERNS）：
  补齐五级页面标签本体（外部复验 / 验证失败 / 工具证据 / 未验证 / Agent 自报）、
  「还没/尚未/未经验证」断言形态与「测试/回归/验收/检查/全部 + 通过(passed)」
  验收语境搭配；「通过 ssh 连接」等正常表达不再误伤（附正反向测试）。
- 事实候选单位表扩展：新增分钟 / 小时 / 天 / 周 / 年 / 美元 / 刀 / 倍 / GB / MB / KB
  等单位，并补汉字数字 + 单位规则（覆盖「两小时」「十次」「三百元」）；
  编造耗时 / 成本的叙事现在会被事实核验拦截（附正反向测试）。
- URL 分级脱敏替代旧 R-URL 无差别全抹：默认保留 host+path 作为引用出处，
  抹除 query（R-URL-QUERY）与内网域名（R-URL-INTERNAL，含 corp/internal/intra/
  local/lan/office 及其 bare-TLD 形态）；`--no-urls` 恢复全抹，`--keep-urls`
  仅保留 URL 凭据兜底。残留扫描中 http(s) 的绝对禁令相应降级为「仅禁 userinfo
  凭据形态」，普通外部引用不再被误杀；文件协议（file scheme）外链仍绝对禁止。

### 其他

- 版本号更新为 1.1.0（SKILL.md 与生成器版本同步）。
- SKILL.md 注意事项补充：残留扫描两套机制说明、URL 分级说明、PII 覆盖范围与
  「姓名等自然语言实体不自动脱敏」的边界声明。
- 回归 fixture bad-leak-marker 更新为宽形态探测 fail-closed 用例（旧样本依赖的
  http 绝对禁令已按设计降级）。

### 补充（P2，同批同版本）

- 主张抽取采用方案 A：assistant 的每一句自然语言陈述都进入证据面板——命中
  标记词的句子（claim_origin=marker）进入五级判定；普通陈述
  （claim_origin=statement）固定 Agent 自报、verification 恒为 unverified、
  不参与验证记录归属，不因工具或检查记录升级。页面证据面板明示该覆盖范围。
- 文本模式页面顶部新增显著降级横幅（无耗时 / Token / 成本、证据强度受限、
  契约版本未知）；examples/01-bugfix 补充合法 narrative.json，成为
  「完整模式 + 有叙事」主推示例（example.py 自动带 --narrative 构建）；
  input-contract.md 补充文本模式证据强度上限说明。
- 自定义词条脱敏 `--denylist <文件>`（all / redact）：UTF-8 每行一个词条，
  空行与 # 注释忽略，按长度降序做普通字符串替换，命中替换为
  [REDACTED:R-DENYLIST]，计入 applied 计数与残留扫描复检；占位符分段受
  保护，保证幂等。
- 新增第四件产物 redaction-report.txt（脱敏审计报告）：逐条列出 detail_id、
  source_ref、规则、原文片段与占位符，文件头明示「本地审计用，不可分享」；
  run.json 的 redaction.details 只含 detail_id / source_ref / rule_id /
  replacement / offset / length，**不含原文片段**（上限 50 条，总数见
  details_total），保持可分享。可分享候选产物为 html / md / run.json。
- 契约版本不匹配（或完整模式契约未知）时页面顶部显示显著横幅，CLI stdout
  输出可操作提示；0 条有效记录的错误信息区分「格式不可识别」与「格式可识别
  但 0 条记录」。
- 耗时显示人性化：HTML / Markdown 以「6 分 00 秒」样式显示（向下取整，
  覆盖小时 / 分 / 秒，不足 1 秒保持毫秒），原始毫秒保留在 run.json 与
  HTML title、括注中，不四舍五入。
- 脱敏计数修正：applied 按 re.subn 实际替换次数累加（此前每串每规则只计 1）；
  denylist、PII、URL 等所有规则统一口径。验收向量：一条文本含 3 个 URL →
  计数 3。
- 产物契约更新：SKILL.md / api_reference.md / input-contract.md /
  evidence-model.md 统一改为四件产物并明确分享边界；example.py 产物校验
  同步为四件。
- QA 复测修复：句读切分对 URL 整体占位保护——URL 内部的 ? / ! 不再被当作
  切点（否则 query 值被切成独立主张绕过脱敏与形态探测）；审计明细
  replacement 的 URL scheme 统一掩码为 [SCHEME]://，消除 --no-urls 档
  R-URLCRED 明细文本自触发残留复检的假阳性（cred URL 在该档仍被整体抹除，
  由 R-URL 占位符守卫 + R-URL-CREDREST 兜底规则双层实现）；新增独立形态
  探测 R-SUS-URLKEY：query 高风险键（access_token / token / secret /
  api_key / apikey / session / sid / auth / code 等）出现在可分享产物即
  strict 硬门拦截（含 keep-urls 档显式保留的 query，keep-urls 非硬门豁免
  通道，需清洗或 --no-strict-pii）；「all 完成」警告计数改取最终模型
  （含 PII_SUSPECTED）；分步 build 不再覆盖 redact/all 阶段生成的含原文
  审计报告。

## v1.0.2（2026-11）

发布包结构修正版本。

### 变更

- 为 WorkBuddy 开放平台生成专用上架包：保留 `{skill-name}/` 根目录，
  并移除 `examples/` 内的第三层嵌套目录，满足
  “根目录 / 二级目录 / 文件”的结构限制。
- 为 WorkBuddy 本地上传生成专用 ZIP：`SKILL.md` 直接位于 ZIP 根目录，
  避免导入器找不到技能定义。
- 版本号更新为 1.0.2；功能逻辑不变。

## v1.0.1（2026-11）

发布准备版本。

### 变更

- 补充 WorkBuddy 开放平台市场所需的 `display_name`、`display_name_en`、
  `category` 字段。
- 版本号更新为 1.0.1；功能逻辑不变。

## v1.0.0（2026-11）

首版发布。

### 能力

- 输入识别与归一化：DSH /export ZIP、单份 session JSONL、结构化 / 通用
  Markdown 会话；同文档作用域内 callId 与 toolCallId 配对；确定性 source_ref
  与页面锚点；未知字段只保留来源引用与警告。
- 五级证据：self-report / tool-evidence / external-verification / unverified /
  failed，全部由脚本按检查记录确定性判定；Automation 只标「已投递」且证据封顶。
- 叙事白名单：语言模型产出的叙事文件经 schema、引用、事实集、等级字样与
  长度五项核验；违规即拒或降级事实模式，绝不放行违规叙事。
- 全树脱敏：结构化敏感键、密钥与令牌样式、URL 凭据、连接串、Cookie、
  Windows / POSIX 中文路径；残留扫描为硬门，不通过不落盘任何产物。
- 离线渲染：无 JavaScript、无外部请求、全字段转义的单文件 HTML，
  Markdown 摘要与脱敏运行模型同步输出；同一输入重复构建逐字节一致。

### 边界

- 不做回放、跨 Agent 对比、日报聚合、自动发布、实时会话读取。
- 不打包原始附件字节与隐藏推理；附件只记元数据。
- 真实 DSH 导出样本暂缺，验收基于人工构造样例，实证验证待用户提供导出。

### 占位文件改造映射

- scripts/example.py：占位脚本改造为 examples 演示运行器（文件名不变）。
- assets/example_asset.txt：占位说明改造为页面设计基线注记（文件名不变）。
- references/api_reference.md：占位参考改造为 CLI 接口、运行模型与叙事协议
  参考（文件名不变）。
