# CLI 接口、运行模型与叙事协议参考

入口脚本为仓库内的 ../scripts/casebook.py，资源以脚本自身位置解析技能根，
与调用时的工作目录无关。子命令与自检：

| 命令 | 签名 | 职责 |
|---|---|---|
| normalize | casebook.py normalize 输入 --out 目录 | 识别、解析、配对，产出原始运行模型与解析报告 |
| validate | casebook.py validate 目录 | schema、引用、叙事白名单校验，产出校验报告 |
| redact | casebook.py redact 目录 | 全树脱敏原始模型（可附 --narrative），产出脱敏后模型 |
| build | casebook.py build 目录 [--out 目录] | 渲染 HTML 与 Markdown 摘要，原子落盘 |
| all | casebook.py all 输入 --out 目录 [--narrative 文件] | 全内存串联前四步，只落三件最终产物 |
| --selftest | 内置向量自检 | 脱敏、转义、证据判定、幂等 |
| --fixtures | 按 ../tests/fixtures/fixtures.json 回归 | good 全过，bad 逐条命中期望退出码 |

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 用法错误（参数缺失或非法） |
| 3 | 输入不可识别（含空文件、非 ZIP / JSONL / Markdown） |
| 4 | 校验失败（schema、引用或叙事违规，报告逐条列出） |
| 5 | 脱敏残留扫描不通过（硬门：不写出任何产物文件） |
| 6 | 构建错误（模板缺失、资源解析失败、产物含脚本标签） |

## 运行模型顶层字段

| 字段 | 说明 |
|---|---|
| schema_version / generator | 模型版本与生成器标识 |
| source | kind、mode（full / text）、inputs、contract_version、degradations |
| task | goal、started_at、ended_at（仅源数据存在时出现） |
| steps / tool_calls | 步骤（含完整原文 text）与工具调用（状态为原文） |
| deliverables | 交付物：path、kind、evidence（等级与验证状态） |
| claims | 助手主张原文、证据等级、验证状态、verification_refs |
| automation | kind、label（恒为「已投递」）、delivered_at |
| metrics | duration_ms / tokens / cost，缺键即隐藏 |
| narrative / narrative_check | 叙事内容与白名单核验结果 |
| redaction | 各规则命中计数与残留扫描结论 |
| warnings | code、source_ref、detail 三元组列表 |

中间文件（normalize 单步落盘的原始模型）首键带醒目警告字段
__WARNING_UNREDACTED__，含未脱敏内容，不得分享；all 主路径全程驻内存，
不落盘任何中间产物。

## 叙事文件协议（narrative 协议）

叙事是语言模型唯一被允许产出的数据，进入渲染前必须通过白名单核验：

```text
{
  "title": "面向读者的标题（不超过 200 字符）",
  "summary": "一段话摘要（不超过 500 字符）",
  "key_nodes": [
    { "ref": "step-1 或 tc-1 或 d-1 或 c-1",
      "heading": "节点标题（不超过 80 字符）",
      "blurb": "两三句说明（不超过 240 字符）" }
  ],
  "reader_notes": ["纯解释性文字，帮助读者理解证据含义"]
}
```

白名单规则（核验失败逐条列出，退出码 4）：

1. key_nodes 的 ref 必须是运行模型中已存在的 id（E-NARR-REF）。
2. 叙事全文中提取的事实候选（文件名、路径、带单位数字）必须能在事实集中
   找到完全一致项；新增文件、指标或无锚点主张即拒（E-NARR-FACT）。
3. 不得出现证据等级字样（已复验、已验证、已执行、已完成及各等级英文词）；
   等级只由页面从运行模型渲染（E-NARR-LEVEL）。
4. title / summary / heading / blurb 超长即拒（E-NARR-SIZE）。
5. schema 不合法即拒（E-NARR-SCHEMA）。

违规处置：all 模式落盘违规清单供会话层回传修正一次；再次违规或无叙事时
按事实模式渲染，页面明示「叙事未通过核验，已按事实模式渲染」，绝不放行
违规叙事。
