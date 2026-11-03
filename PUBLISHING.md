# 发布指南 / Publishing

本文说明如何把 `agent-run-casebook` 发布到 WorkBuddy 开放平台、DSH 和 GitHub。

## 1. WorkBuddy 开放平台

上架包：

- 文件：`agent-run-casebook-openplatform-v1.0.1.zip`
- SHA256：`58fdec045d48b1f57341f9e679e957088731204f00b983058b78655680146cbd`
- 解压后大小：约 52 KB，低于 3 MB 限制
- ZIP 解压后第一层是 `agent-run-casebook/`
- 包内已排除测试夹具、生成产物、缓存和敏感样例

上架入口：

1. 打开 [WorkBuddy 开放平台](https://open.workbuddy.cn/)。
2. 登录并完成开发者实名认证。
3. 进入「发布管理 → 技能」，选择「创建」。
4. 上传 `agent-run-casebook-openplatform-v1.0.1.zip`。
5. 核对自动解析字段：
   - `name`: `agent-run-casebook`
   - `display_name`: `Agent 运行案例册`
   - `display_name_en`: `Agent Run Casebook`
   - `version`: `1.0.1`
   - `author`: `刘俊涵`
6. 补充市场展示分类、服务类目和头像。
7. 提交审核；审核通过后选择「公开发布」。

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

## 2. DSH 本地安装

已安装到以下用户级位置：

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

## 3. GitHub 发布

仓库根目录就是技能目录 `agent-run-casebook/` 的内容。推荐仓库设置：

- 仓库名：`agent-run-casebook`
- 描述：`Turn Agent runs into verifiable, shareable offline casebooks.`
- 可见性：Public
- 主分支：`main`
- 发布 Tag：`v1.0.1`

推荐 Release 说明：

```text
Agent Run Casebook v1.0.1

Turn one Agent run export into a verifiable, shareable offline casebook.

Highlights:
- DSH /export ZIP, session JSONL, and structured Markdown input
- Five-level evidence grading
- Full-tree redaction with a hard residual-scan gate
- Traceable source anchors
- Offline single-file HTML with no JavaScript and no external requests
- Deterministic rebuilds
```

## 4. 发布前检查

在技能目录运行：

```bash
python scripts/casebook.py --selftest
python scripts/casebook.py --fixtures
```

两项都应返回 0。开放平台包不应包含测试夹具、生成产物、个人路径或秘密。
