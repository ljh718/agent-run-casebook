# DSH 导出契约适配说明与已知限制

本技能适配 DSH 的会话日志导出契约（/export 产生的 ZIP 与逐行 JSONL 记录结构）。
DSH 处于预览期，官方契约可能演进；版本不匹配的字段一律降级并保留来源引用，
不猜测语义。v1.2.0 起同时支持官方信封事件格式（v2 与 v4 已知契约）。

## 输入形态（重要）

- **本技能支持的输入仍是官方 /export ZIP 与明文 JSONL**（含信封格式的
  session.v2.jsonl / session.v4.jsonl）。
- DSH 真实内部持久化为 session.v4.jsonl.zstd（多帧 zstd 压缩），**不是**
  /export 产物；本技能不读取 zstd 文件。需要复盘内部会话时，请先通过官方
  /export 得到 ZIP / JSONL，或自行解压为明文 JSONL 后再交给本技能。

## 信封事件格式（v2 / v4）

- 头行：`{"type":"session","version":4,...}`；version 2 与 4 为已知契约
  （同构核心事件），其他值整体降级 unknown 并出 CONTRACT_VERSION_MISMATCH。
  无头行的信封文件不会显式报版本错误——契约版本静默回退默认值 v2（P2-2
  行为声明）；真实导出恒有头行，不受影响。
- assistant/message 的 tool-call 块在真实 v4 数据中不带 callId：解析层把块
  记为 pending，同一文档作用域内与随后首个同名带 callId 的 tool/call 事件
  确定性合并（tool_call 统计不翻倍）；文档结束仍未消解的块按原位置保留为
  无 callId 工具调用并出 UNMERGED_TOOL_CALL_BLOCK 警告。
- 事件信封：`{"type","seq","time"(epoch ms),"data","surfaceOp"?}`；
  tool/result 另有顶层 `sourceEventSeqs`。
- 已知事件类型与映射（v1.2.0）：

| 信封 type | 映射 |
|------|------|
| user/message | user 事件（text 块按序拼接）；file 块 → deliverable（path=attachment.name） |
| assistant/message | assistant 事件 + tool-call 块 → tool_call；usage 数值 token 计入（cache 类不计，无 cost 不估算） |
| tool/call | tool_call（data.callId / data.name） |
| tool/result | tool_result（toolCallId=data.message.toolCallId；isError→fail 否则 ok） |
| session/title | 标题（run.task.title） |
| job/registered、job/settled、`*/delivery-accepted` | automation（只标已投递 + 证据封顶 tool-evidence；绝不从 settled 推断执行成功） |
| system/message | 结构排除（值不保留，仅 SYSTEM_RECORD 计数） |

- 同一 callId 的重复 tool_call 事件（assistant 工具块 + 独立 tool/call 事件）
  只保留首个，出 TOOL_CALL_DUPLICATE 警告。
- **未知事件处理策略**：step/*、turn/*、request/*、permission/preset、
  sandbox/mode、approval/policy、web/*、agent/inbox/*、session/title-llm-request
  及其他未列出类型 → 不猜语义：记 UNKNOWN_FIELD 警告并保留 source_ref，计入
  有效记录（防 0 条误报），不生成任何 user/assistant/claim 事件，不进入渲染。

## 适配范围

- 会话级：任务目标（首个用户消息）、起止时间、总耗时（仅当源数据两端时间戳齐备）。
- 记录级：用户消息、助手消息及其内嵌 toolCalls、独立工具调用与工具结果
  （callId 与 toolCallId 配对，规则见 input-contract.md）、检查记录、
  Automation / Schedule 投递记录、交付物路径。
- 附件：只记录安全的附件元数据，不读取附件字节；涉及附件内容的验证无法由本技能完成。

## 明确不做

- 不适配 Claude、Codex 等其他 Agent 的私有日志格式，也不做跨 Agent 运行对比。
- 不读取实时 Session，不自动调用 /export，不扫描个人目录寻找会话。
- 不打包原始附件字节、完整长日志、system 消息或隐藏推理。

## 已知限制

1. **真实样本验证范围**：v1.2.0 已用真实 DSH v4 会话（约 200 条信封事件）
   完成信封解析的实证验证并修复 0 条缺口；但成本 / 定时任务执行结果等字段
   的深度语义（如 usage 键名变体）仍以「符合已核实的字段形态」为准，键名
   变体不在上述确定性规则内时按未知处理。开发与回归使用人工脱敏信封样本
   （tests/fixtures/good/dsh-v4/input.jsonl）。
2. **契约演进**：记录中声明了版本且不在锁定集时，整体降级为 unknown 并出
   CONTRACT_VERSION_MISMATCH 警告；版本演进后需回到本文件与实现同步修订。
3. **未在官方文档明确的自有扩展字段**：保留字段名、来源引用与标量原值，
   归入「未识别字段（未解读）」折叠展示，不参与叙事与证据判定。
4. **文本模式**：Markdown 导出不含精确工具统计、Token、成本与细粒度计时，
   页面相应区块不渲染，并明示文本模式。
5. **未压测规模**：超长会话与多成员大型 ZIP 的性能与稳定性未做压测；
   建议先用小样本验证解析结果，再用于大型导出。
