# 发布指南 / Publishing

本文说明如何把 `agent-run-casebook` 发布到 WorkBuddy 开放平台、WorkBuddy 本地导入和 DSH。

## 包的区别：不要混用

这个 skill 有三个 v1.1.0 上传包，对应三个入口的结构差异：

| 用途 | ZIP 根目录 | 使用位置 |
|---|---|---|
| WorkBuddy 开放平台上架 | `agent-run-casebook/` | open.workbuddy.cn |
| WorkBuddy 本地上传 | `SKILL.md` | WorkBuddy 客户端「添加技能 → 上传技能」 |
| DSH 便携包 | `agent-run-casebook/` | 解压到 `~/.dsh/skills/` 或 `~/.agents/skills/` |

历史版本：v1.0.2 及更早的上传包已归档（v1.1.0 修复了外部缺陷报告中的 P0/P1/P2 共 11 项问题，请勿继续使用旧包）。

## 1. WorkBuddy 开放平台

上架包：

- 文件：`outputs/agent-run-casebook/v1.1.0/agent-run-casebook-openplatform-v1.1.0.zip`
- SHA256：`10cfbc1b0b3814e250240216e1c7bcd6f99230ec172161a3f5a1e4a05a9ce4da`
- 大小：67,311 字节（17 个文件）
- ZIP 第一层：`agent-run-casebook/`
- 最深路径：`agent-run-casebook/<二级目录>/<文件>`
- 包含 `SKILL.md`、`CHANGELOG.md`、`requirements.txt`、`references/`、`scripts/`、`assets/`
- 已排除 `tests/`、`examples/`、缓存、生成产物、个人路径与秘密

上架入口：

1. 打开 [WorkBuddy 开放平台](https://open.workbuddy.cn/)。
2. 进入「发布管理 → 技能」，选择「创建」。
3. 上传 `agent-run-casebook-openplatform-v1.1.0.zip`。
4. 核对自动解析字段：
   - `name`: `agent-run-casebook`
   - `display_name`: `Agent 运行案例册`
   - `display_name_en`: `Agent Run Casebook`
   - `version`: `1.1.0`
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
session JSONL 和结构化 Markdown；输出五级证据面板、关键路径、交付物和来源锚点。
默认全树脱敏，无 JavaScript、无外部请求，适合复盘、汇报和成果展示。
```

## 2. WorkBuddy 本地上传

本地导入包：

- 文件：`outputs/agent-run-casebook/v1.1.0/agent-run-casebook-workbuddy-local-v1.1.0.zip`
- SHA256：`b5ca38706ba1fac1ce47fb2ad4bc5cc6225a5db7b8cc0c278b7f7c6c89a10720`
- 大小：66,665 字节（17 个文件）
- ZIP 根目录直接包含 `SKILL.md`，没有外层 `agent-run-casebook/` 文件夹
- 已包含 `scripts/`、`references/`、`assets/`、`CHANGELOG.md`、`requirements.txt`

操作：

1. 打开 WorkBuddy。
2. 进入「专家·技能·连接器 → 技能」。
3. 点击「添加技能 → 上传技能」。
4. 选择 `agent-run-casebook-workbuddy-local-v1.1.0.zip`。

如果想手动安装，也可以把仓库内容复制到：

```text
~/.workbuddy/skills/agent-run-casebook
```

## 3. DSH 本地安装

便携包：

- 文件：`outputs/agent-run-casebook/v1.1.0/agent-run-casebook-dsh-v1.1.0.zip`
- SHA256：`4dcfee9880aa375f4eed729b1447530ad0f9a3f085644e96622774edc5d5ee18`
- 大小：72,922 字节（24 个文件，额外含 `examples/` 三组示例输入）
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
- 发布 Tag：`v1.1.0`

## 5. 质量结论与已知限制（v1.1.0）

- QA 终态结论：**通过**（外部缺陷修复复测报告 §11 R4 轮，2026-11-03）。基线全绿：185 项 unittest、`--selftest`、`--fixtures`（8 例）、marketplace 校验器、三示例双跑逐字节一致。
- 外部缺陷报告 P0-1/P0-2（PII 脱敏、宽形态探测）、P1-1/P1-2/P1-3（等级词、事实数字、URL 分级）、P2-1~P2-6 全部修复并复测通过；复测中发现并关闭的 F-1（claim 句读切 URL 泄漏 query 凭据）、F-2（`--no-urls` 假阳性硬门）与 M-1~M-3 均已验证。
- 已知限制（不阻断）：
  1. 真实 DSH /export 样本仍未实测（文档已声明）；
  2. `redaction-report.txt` 的 1000 条明细上限行为未实测；
  3. R-BANKCARD 粗筛对 16-19 位长单号可能误报，属声明内取舍；
  4. `--keep-urls` 档保留含风险键（token/secret/api_key/session/sid/auth/code）的 query 会被 `R-SUS-URLKEY` 硬门拦截（exit 5），为文档化的 fail-closed 有意行为。
- **`redaction-report.txt` 是本地审计文件，含被替换的原文片段，仅供本人核对脱敏效果，不可分享、不可随产物外发。**

## 6. 发布前检查

在技能目录运行：

```bash
python scripts/casebook.py --selftest
python scripts/casebook.py --fixtures
```

两项都应返回 0。开放平台包不应包含测试夹具、生成产物、个人路径或秘密。
