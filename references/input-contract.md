# 输入契约：支持的输入、识别规则与降级口径

本文件说明归一化层（references 同级的 ../scripts/normalize.py）接受什么输入、
如何识别、字段如何落位、以及所有降级行为的确定性口径。

## 支持的输入

| 输入形态 | kind | mode | 说明 |
|---|---|---|---|
| DSH /export ZIP | dsh-zip | full | 成员内的 JSONL 与 Markdown 分别解析，其余成员跳过并计数 |
| 单份 session.v2.jsonl 或 session.jsonl | dsh-jsonl | full | 逐行 JSON 记录，坏行降级不中断 |
| DSH「复制会话为 Markdown」文本 | dsh-markdown | text | 具备用户 / 助手 / 工具标题结构 |
| 通用 Markdown 会话 | generic-markdown | text | 有标题结构但无角色标题；按纯文本处理 |

文本模式（mode=text）下工具统计、耗时、Token、成本必然缺失，页面信息密度降低，
这是设计内行为而非缺陷；缺失指标不渲染、不估算。

## 文本模式的证据强度上限（页面顶部有显著横幅提示）

- 无独立检查记录 → 主张不可判为 external-verification / failed；
- 交付物最高为 tool-evidence（来源为助手 / 工具侧文本）或 self-report（用户侧）；
- 契约版本恒为 unknown（属文本模式的预期降级，不额外显示契约横幅）；
- 工具状态只能从正文行的受控词表行嗅探，嗅探不到即无验证记录。
以上上限意味着文本模式案例页的证明力天然弱于完整模式，页面顶部横幅会明示
这一点；使用者应优先提供 DSH /export ZIP 或 session JSONL。

## 识别规则（确定性嗅探）

1. 文件头两字节为 PK 魔数 → dsh-zip。
2. 首个非空行可解析为 JSON 对象 → dsh-jsonl。
3. 存在 Markdown 标题行 → 含用户 / 助手 / 工具 / user / assistant / tool 角色词 → dsh-markdown，否则 generic-markdown。
4. 其余一律判定为不可识别，CLI 以退出码 3 结束；空文件、目录、缺失文件同样不可识别。

嗅探只判断格式，不判断用户意图；意图判断由会话层的语言模型完成。

## 记录级字段与配对

JSONL 记录按 type 字段落位：user、assistant（含 toolCalls 数组）、tool 与 tool_call
（携带 callId）、tool_result（携带 toolCallId）、check 与 verification（携带 status）、
automation 与 schedule。配对规则：

- 配对只在同一文档作用域内进行：JSONL 的作用域是整份文件，ZIP 成员的作用域是单个成员，Markdown 的作用域是整份文档。
- toolResult 的 toolCallId 找到同作用域内一致的 callId 才回写状态与耗时；跨作用域不配对并产出 UNPAIRED_TOOL_CALL 警告。
- 检查记录（check / tool_result 的状态字段）是证据判定的唯一输入，词表见 evidence-model.md。

## source_ref 生成规则

- JSONL 记录：s<输入序号>/L<物理行号>/j<JSON 路径>。
- ZIP 成员内记录：s<序号>@<成员名>/L<行号>/j<路径>。
- Markdown 区块：s<序号>/h<层级>:<标题锚>/L<物理行号>。
- HTML 锚点 id 取 source_ref 的 sha1 前 10 位，同一输入重跑逐字节一致。

## 未知字段处置

不在契约已知键集内的记录级字段：保留字段名、来源引用与标量原值（仅标量），
写入所属记录的 unknown_fields 并产出 UNKNOWN_FIELD 警告；页面在折叠时间线内
以「未识别字段（未解读）」区块展示（限前 20 条，其余仅计数）。未知字段不参与
叙事、不参与证据判定、不做任何语义猜测。

## 降级与失败行为

| 情形 | 行为 |
|---|---|
| 个别坏 JSON 行 | 计入 degradations（PARSE_ERROR）并继续解析，页面降级清单可见 |
| 整文件无可识别记录 | UnrecognizedInputError，CLI 退出码 3，不产出产物；错误信息区分「格式不可识别」与「格式可识别但 0 条有效记录」 |
| 契约版本不在锁定集 | contract_version 置 unknown，产出 CONTRACT_VERSION_MISMATCH 警告，整体降级并保留来源引用；页面顶部显示契约版本横幅，CLI stdout 输出可操作提示（建议提供真实 DSH 导出样本以适配） |
| system / developer 消息与隐藏推理 | 结构排除，从源头不进入运行模型，只记排除计数 |
