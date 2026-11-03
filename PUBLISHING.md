# 发布指南 / Publishing

本文说明如何把 `agent-run-casebook` 发布到 WorkBuddy 开放平台、WorkBuddy 本地导入和 DSH。

## 包的区别：不要混用

这个 skill 有两个 v1.0.2 上传包，对应两个入口的结构差异：

| 用途 | ZIP 根目录 | 使用位置 |
|---|---|---|
| WorkBuddy 开放平台上架 | `agent-run-casebook/` | open.workbuddy.cn |
| WorkBuddy 本地上传 | `SKILL.md` | WorkBuddy 客户端「添加技能 → 上传技能」 |

旧版 `agent-run-casebook-openplatform-v1.0.1.zip` 已废弃。它包含
`examples/01-bugfix/` 这类第三层目录，开放平台会报：

> 目录层级超限 — Skill 包仅支持两级目录结构（根目录/二级目录/文件）

## 1. WorkBuddy 开放平台

上架包：

- 文件：`open-platform-v1.0.2/agent-run-casebook-openplatform-v1.0.2.zip`
- SHA256：`db964ac8991dfcb3ed8deba23e14f3ee39692972910fb8feed538fd67da94962`
- 大小：48,063 字节
- ZIP 第一层：`agent-run-casebook/`
- 最深路径：`agent-run-casebook/<二级目录>/<文件>`
- 已移除造成第三层嵌套的 `examples/01-bugfix/`、`examples/02-research-report/`、`examples/03-data-analysis/`
- 已排除测试夹具、生成产物、缓存和个人路径

上架入口：

1. 打开 [WorkBuddy 开放平台](https://open.workbuddy.cn/)。
2. 进入「发布管理 → 技能」，选择「创建」。
3. 上传 `agent-run-casebook-openplatform-v1.0.2.zip`。
4. 核对自动解析字段：
   - `name`: `agent-run-casebook`
   - `display_name`: `Agent 运行案例册`
   - `display_name_en`: `Agent Run Casebook`
   - `version`: `1.0.2`
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

- 文件：`workbuddy-local-v1.0.2/agent-run-casebook-workbuddy-local-v1.0.2.zip`
- SHA256：`03243e71a67df5914cf9a057890e0f319ad36fd90be4f2253ce21d62ee4980f3`
- 大小：47,417 字节
- ZIP 根目录直接包含 `SKILL.md`，没有外层 `agent-run-casebook/` 文件夹
- 已包含 `scripts/`、`references/`、`assets/`

操作：

1. 打开 WorkBuddy。
2. 进入「专家·技能·连接器 → 技能」。
3. 点击「添加技能 → 上传技能」。
4. 选择 `agent-run-casebook-workbuddy-local-v1.0.2.zip`。

如果想手动安装，也可以把仓库内容复制到：

```text
~/.workbuddy/skills/agent-run-casebook
```

## 3. DSH 本地安装

任选一个用户级位置：

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
- 发布 Tag：`v1.0.2`

## 5. 发布前检查

在技能目录运行：

```bash
python scripts/casebook.py --selftest
python scripts/casebook.py --fixtures
```

两项都应返回 0。开放平台包不应包含测试夹具、生成产物、个人路径或秘密。
