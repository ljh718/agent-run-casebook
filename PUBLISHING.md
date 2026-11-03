# 发布指南 / Publishing

本文说明如何把 `agent-run-casebook` 发布到 WorkBuddy 开放平台、WorkBuddy 本地导入和 DSH。

## 包的区别：不要混用

这个 skill 有三个 v1.2.0 上传包，对应三个入口的结构差异：

| 用途 | ZIP 根目录 | 使用位置 |
|---|---|---|
| WorkBuddy 开放平台上架 | `agent-run-casebook/` | open.workbuddy.cn |
| WorkBuddy 本地上传 | `SKILL.md` | WorkBuddy 客户端「添加技能 → 上传技能」 |
| DSH 便携包 | `agent-run-casebook/` | 解压到 `~/.dsh/skills/` 或 `~/.agents/skills/` |

历史版本：v1.1.0 及更早的上传包已归档（v1.2.0 修复了真实 DSH 会话实测发现的信封解析缺口、复检域失配与工具块统计翻倍问题，请勿继续使用旧包）。

## 1. WorkBuddy 开放平台

上架包：

- 文件：`outputs/agent-run-casebook/v1.2.0/agent-run-casebook-openplatform-v1.2.0.zip`
- SHA256：`fa40576409a22164846ba481fee26e12d4d52e415fade79a8b8acce5d9e88241`
- 大小：78,545 字节（18 个文件）
- ZIP 第一层：`agent-run-casebook/`
- 最深路径：`agent-run-casebook/<二级目录>/<文件>`
- 包含 `SKILL.md`、`CHANGELOG.md`、`requirements.txt`、`references/`、`scripts/`、`assets/`
- 已排除 `tests/`、`examples/`、缓存、生成产物、个人路径与秘密

上架入口：

1. 打开 [WorkBuddy 开放平台](https://open.workbuddy.cn/)。
2. 进入「发布管理 → 技能」，选择「创建」。
3. 上传 `agent-run-casebook-openplatform-v1.2.0.zip`。
4. 核对自动解析字段：
   - `name`: `agent-run-casebook`
   - `display_name`: `Agent 运行案例册`
   - `display_name_en`: `Agent Run Casebook`
   - `version`: `1.2.0`
   - `author`: `刘俊涵`
5. 补充市场展示分类、服务类目和头像。
6. 提交审核；审核通过后选择「公开发布」。

建议展示分类：

- 开发工具
- 效率工具
- 数据分析

建议介绍：

```text
把一次 Agent 运行导出变成可核验、可分享的离线案例页。支持 DSH /export ZIP、
session JSONL（含 v2/v4 官方信封事件格式）和结构化 Markdown；输出五级证据面板、
关键路径、交付物和来源锚点。默认全树脱敏，无 JavaScript、无外部请求，适合复盘、
汇报和成果展示。
```

## 2. WorkBuddy 本地上传

本地导入包：

- 文件：`outputs/agent-run-casebook/v1.2.0/agent-run-casebook-workbuddy-local-v1.2.0.zip`
- SHA256：`a0a8a57c45920baeda6441e9d20b9dbfe2361cd3afe162484d3a31aca2782aab`
- 大小：77,861 字节（18 个文件）
- ZIP 根目录直接包含 `SKILL.md`，没有外层 `agent-run-casebook/` 文件夹
- 已包含 `scripts/`、`references/`、`assets/`、`CHANGELOG.md`、`requirements.txt`

操作：

1. 打开 WorkBuddy。
2. 进入「专家·技能·连接器 → 技能」。
3. 点击「添加技能 → 上传技能」。
4. 选择 `agent-run-casebook-workbuddy-local-v1.2.0.zip`。

如果想手动安装，也可以把仓库内容复制到：

```text
~/.workbuddy/skills/agent-run-casebook
```

## 3. DSH 本地安装

便携包：

- 文件：`outputs/agent-run-casebook/v1.2.0/agent-run-casebook-dsh-v1.2.0.zip`
- SHA256：`187f0ed5c6e9308c843b8308163ddb1870c3125f69975d46bfc28ce17e4697e7`
- 大小：84,156 字节（25 个文件，额外含 `examples/` 三组示例输入）
- ZIP 第一层：`agent-run-casebook/`，解压到用户级技能目录即可

任选一个用户级位置解压：

```text
~/.dsh/skills/agent-run-casebook
~/.agents/skills/agent-run-casebook
```

也可以安装到项目级：

```text
<project-root>/.dsh/skills/agent-run-casebook
```

安装后新建或刷新 Session，然后输入：

```text
把这个 DSH /export 导出整理成案例页。
```

## 4. GitHub 发布

仓库根目录就是技能目录 `agent-run-casebook/` 的内容。推荐仓库设置：

- 仓库名：`agent-run-casebook`
- 描述：`Turn Agent runs into verifiable, shareable offline casebooks.`
- 可见性：Public
- 主分支：`main`
- 发布 Tag：`v1.2.0`

## 5. 质量结论与已知限制（v1.2.0）

- QA 终态结论：**通过**（`DSH信封修复复测报告.md` 第二轮复测，2026-11-03；第一轮不通过——两项 P0 修复实跑有效，但发现 P1-1 工具块统计翻倍与幽灵引用；第二轮确认 P1-1 修复有效，明确"通过，可进入打包阶段"）。
- 基线全绿：219 项 unittest（212→219，新增 7 例）、`--selftest`、`--fixtures`（10 例，含新增真实形态样本 good-dsh-v4-realform）、marketplace 校验器（6 条 W-UNKNOWN-FIELD 为上架展示字段候选信号，复核无风险）、examples 三例双跑逐字节一致。
- 真实三例验证：信封 tool/call 数与 run.json tool_calls 数精确相等（8 / 22 / 34），零幽灵共享、零 UNMERGED / DUPLICATE 警告；脱敏硬门在原 R-INLINE-CRED 假命中样本上 strict 默认档 exit 0。
- 已知限制（不阻断）：
  1. 真实 DSH /export ZIP 未直接实测（本机仅有内部持久化会话形态；对解压后 JSONL 的实测通过，/export ZIP 解包为既有已验证代码路径）；
  2. zstd 输入不支持：`session.v4.jsonl.zstd`（多帧 zstd）非 /export 产物，不读取（文档已声明）；
  3. 同名多次调用在「块序与 tool/call 序颠倒」的未观测形态下可能顺序错配（已声明，确定性，有警告兜底）；
  4. 无头行信封文件契约版本静默回退 v2（已声明于 `references/dsh-export.md`）；
  5. R-BANKCARD / R-IPV4 / R-CN-MOBILE 的既有灰区误伤取向不变；
  6. 超长会话 / 大型 ZIP 未压测（文档已声明）。
- **`redaction-report.txt` 是本地审计文件，含被替换的原文片段，仅供本人核对脱敏效果，不可分享、不可随产物外发。**

## 6. 发布前检查

在技能目录运行：

```bash
python scripts/casebook.py --selftest
python scripts/casebook.py --fixtures
```

两项都应返回 0。开放平台包不应包含测试夹具、生成产物、个人路径或秘密。
