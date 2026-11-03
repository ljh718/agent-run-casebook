# agent-run-casebook v1.1.0 发布说明

发布日期：2026-11-03
上一版本：v1.0.2
QA 结论：**通过**（外部缺陷修复复测报告 §11 R4 轮，2026-11-03）

本版本修复了外部缺陷报告（基于 v1.0.2）中的全部 P0/P1/P2 共 11 项问题，并关闭了复测过程中新发现的 F-1/F-2 与三个次要项。全程未新增功能面，属缺陷修复与加固版本。

## P0（阻断级）

- **P0-1 PII 脱敏覆盖不足**：新增手机号（含格式变体）、邮箱、身份证、银行卡、内外网 IPv4、内联凭据、OPENSSL 私钥块等脱敏规则；strict 模式默认开启，残留扫描通过后才产出可分享产物。
- **P0-2 宽形态敏感探测缺失**：新增独立宽形态探测（如 13 位订单号等疑似敏感长数字串），strict 档直接拦截（exit 5 不落盘），`--no-strict-pii` 档降级为 `PII_SUSPECTED` 警告并计入 run.json 审计。

## P1（严重）

- **P1-1 等级词拦截**：叙事中"外部复验 / 验证失败 / 工具证据（未复验）/ 还没验证 / 测试全部通过"等等级词与事实主张冲突时拦截（E-NARR-LEVEL），同时避免对正常句式误伤。
- **P1-2 事实数字拦截**：叙事中出现 run 模型中不存在的事实数字（耗时 / 成本等，含汉字数字）时拦截（E-NARR-FACT）；引用 run 模型真实存在数值时放行。
- **P1-3 URL 分级**：default 档保留 host+path、抹除 query 与 userinfo、抹除内网域名；`--keep-urls` / `--no-urls` 两档语义明确定义并文档化。

## P2（体验与文档）

- **P2-1 主张覆盖（方案 A）**：statement 主张固定 `self-report/unverified`，marker 主张按五级判定并挂验证引用，杜绝虚升格。
- **P2-2 文本模式**：文本输入自动显示"证据强度受限"横幅，input-contract.md 明确文本模式证据上限。
- **P2-3 denylist 计数**：denylist 词条与各规则替换次数按真实替换次数计数，report 头部明示"本地审计用，不可分享"，details 不含原文片段。
- **P2-4 契约提示**：schemaVersion 未锁定时页面横幅 + CLI 提示；"可识别但 0 条"与"不可识别"两种失败可区分。
- **P2-5 耗时人性化**：页面显示"6 分 00 秒"式可读耗时，run.json 保留原始 ms 值。
- **P2-6 上限与计数**：details 上限 50（附 `details_total`）、审计报告上限 1000，applied 计数不受截断影响。

## 复测中发现并关闭的问题

- **F-1（高·阻断）**：claim 句读在 URL 的 `?` 处切分，query 凭据（如 `access_token=abc123`）脱离 URL 形态逃过脱敏进入可分享产物。修复：句读切分前对 URL 子串做占位保护，从源头保证 URL 完整性；`access_token` / `sid=x1~x3` 等残留实测为 0。另新增 `R-SUS-URLKEY` 宽探测作为纵深兜底（keep-urls 档保留风险键 query 时 exit 5，文档化 fail-closed 行为）。
- **F-2（中）**：`--no-urls` 档被自身审计明细中的 `https://` scheme 假阳性卡死（正当输入 exit 5 被拒）。修复：details 的 replacement scheme 统一掩码为 `[SCHEME]://`，复检不再自触发。
- **M-1**：`all` 汇总行警告计数与 run.json 的 PII_SUSPECTED 口径对齐。
- **M-2**：分步流程的报告覆盖语义修正（build 不覆盖已有含原文报告），SKILL.md 与 api_reference.md 同步口径。
- **M-3**：api_reference.md 注明 details.offset 为"规则应用时文本坐标（信息性）"与 `[SCHEME]://` 掩码。

## QA R4 终态基线（全部实跑 exit 0）

- `python -m unittest discover -s tests -v`：**185 例 OK**
- `python scripts/casebook.py --selftest`：全部 PASS
- `python scripts/casebook.py --fixtures`：回归全过（8 例）
- marketplace 校验器（`--platform workbuddy --channel marketplace`）：通过（6 条 W-UNKNOWN-FIELD 为校验器词表滞后，人工复核可接受）
- 三示例双跑 `diff -r` 逐字节一致；t01/t02/cite2/cite3/u3/t09 对抗样本全部达标，未发现泄漏路径

## 已知限制（不阻断）

1. 真实 DSH /export 样本未实测（文档已声明）。
2. `redaction-report.txt` 1000 条明细上限行为未实测。
3. R-BANKCARD 粗筛对 16-19 位长单号可能误报，属声明内取舍。
4. `--keep-urls` 档保留含风险键（token/secret/api_key/session/sid/auth/code）的 query 会被 `R-SUS-URLKEY` 硬门拦截（exit 5）。

## 安全提示

`redaction-report.txt` 是本地审计文件，含被替换的原文片段，仅供本人核对脱敏效果，**不可分享、不可随产物外发**。

## 升级

从 v1.0.2 升级请直接替换安装目录内容或重新上传对应 v1.1.0 包（三个包的用途与结构见 `PUBLISHING.md`）。输入契约向后兼容 v1.0.2 的 JSONL / Markdown / ZIP 输入；旧 run.json 产物不可与新版本混用重建。
