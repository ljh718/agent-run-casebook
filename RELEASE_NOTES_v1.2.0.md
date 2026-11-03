# RELEASE NOTES — agent-run-casebook v1.2.0

发布日期：2026-11-03

v1.2.0 是 DSH 官方信封事件格式解析修复版本。全部修复均由真实 DSH 会话数据实测发现并驱动，经 skill-qa 两轮独立复测后通过发布。

## 一、官方信封格式解析（P0 修复）

真实 DSH 会话验证发现，此前的 JSONL 解析只认合成格式 `{"type":"user"|...}`，官方信封事件 `{"type":"user/message","data":{...}}` 全部落入「无已知 type」分支——对真实会话产出 **0 条有效记录**。

修复：新增 `scripts/dsh_events.py` 信封解析模块并接入 normalize：

- 支持 v2 / v4 已知契约（头行 version，其他值警告并整体降级 unknown）；
- user/message、assistant/message（含 tool-call 块）、tool/call、tool/result、session/title、system/message 排除等完整映射；
- epoch 毫秒时间戳 → 确定性 ISO 8601 UTC（重复构建逐字节一致）；
- automation 事件沿用「只标已投递」语义，绝不从 settled 推断执行成功；
- 未知事件「不猜语义」策略：仅 UNKNOWN_FIELD 警告 + 保留 source_ref，计入有效记录防 0 条误报，不生成任何事件。

合成格式解析完全不变，向后兼容全部既有 fixtures 与测试。

## 二、残留复检域失配（P0 修复）

真实数据复检发现第二处 P0：R-INLINE-CRED 在真实会话上应用 8 处、逐叶复检零命中，却在硬门字节扫描上命中假阳性（exit 5、产物零落盘）。根因是规则应用域为字符串叶，而复检跑在序列化/渲染字节流上，JSON 字面转义会跨叶凑满凭据形态。

修复：新增 `residual_scan_tree` 按脱敏树逐字符串叶复检（机制 A/B/C + 负向集 + marker 全套），run.json / HTML / MD 统一按树扫描（`emit_atomic` 增 `scan_tree` 参数，未传时保持旧字节扫描向后兼容）。「应用后不被复检命中」不变式恢复，fail-closed 硬门与脱敏语义不放松。

## 三、真实 v4 形态工具块统计翻倍与幽灵引用（P1-1 修复）

第一轮复测发现：真实 v4 会话中 assistant/message 的 tool-call 块 0/22 带 callId，同 callId 去重永不触发——每次调用产出两条 tool_call（块副本 call_id=None），三例真实会话统计精确翻倍（16/8、44/22、68/34），且 `call_id_to_id[None]` 被副本覆盖导致多步骤错误引用同一幽灵条目（实测 35 次步骤引用中 13 次指向同一幽灵）。

修复：None 键不再入映射；无 callId 块记为 pending，同一文档作用域内与随后首个同名带 callId 的 tool/call 事件确定性合并（FIFO），未消解块保留原位并出 UNMERGED_TOOL_CALL_BLOCK 警告（消除静默虚增）。

## 四、QA 验证结论

- **第一轮复测（《DSH信封修复复测报告.md》）：不通过**——信封解析与复检域两项 P0 修复实跑确认有效，但发现 P1-1 统计翻倍与幽灵引用。
- **第二轮复测（同报告「第二轮复测」章节）：通过，允许进入打包阶段**。基线全绿：219 项 unittest、`--selftest`、`--fixtures`（10 例，含新增真实形态样本 good-dsh-v4-realform）、marketplace 校验器、examples 三例双跑逐字节一致。
- **真实三例指标**：信封 tool/call 数与 run.json tool_calls 数精确相等——**8 / 22 / 34**（d47b5e1b / 3d4ffcf7 / 605fcc51），零幽灵共享、零 UNMERGED / DUPLICATE 警告；状态分布恢复（2 ok/6 fail、19 ok/3 fail、34 ok）。

## 五、已知限制

1. 真实 DSH /export ZIP 未直接实测（本机仅有内部持久化会话形态；对解压后 JSONL 的实测通过，/export ZIP 解包路径为既有已验证代码）。
2. zstd 输入不支持：`session.v4.jsonl.zstd`（多帧 zstd）非 /export 产物，不读取（文档已声明）。
3. `redaction-report.txt` 是本地审计文件，含被替换的原文片段，仅供本人核对脱敏效果，**不可分享、不可随产物外发**。
4. 同名多次调用在「块序与 tool/call 序颠倒」的未观测形态下可能顺序错配（已声明，确定性，有警告兜底）。
5. 无头行信封文件契约版本静默回退 v2（已声明于 references/dsh-export.md）。
6. v1.1.0 既有灰区（R-BANKCARD / R-IPV4 / R-CN-MOBILE 误伤取向）不变；超长会话 / 大型 ZIP 未压测。

## 六、升级方式

- WorkBuddy 本地：重新上传 `agent-run-casebook-workbuddy-local-v1.2.0.zip`。
- DSH / agents：解压 `agent-run-casebook-dsh-v1.2.0.zip` 覆盖 `~/.dsh/skills/agent-run-casebook` 或 `~/.agents/skills/agent-run-casebook`。
- 开放平台：上传 `agent-run-casebook-openplatform-v1.2.0.zip` 重新提审。

详见 `PUBLISHING.md`。
