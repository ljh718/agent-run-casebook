# Agent Run Casebook

**中文**：把一次 Agent 运行导出变成可核验、可分享的离线案例页。支持 DSH `/export` ZIP、`session.v2.jsonl` / `session.jsonl` 和结构化 Markdown 会话；输出包含任务、关键路径、交付物、五级证据面板和可回溯的来源锚点。

**English**: Turn one Agent run export into a verifiable, shareable offline casebook. Supports DSH `/export` ZIP, session JSONL, and structured Markdown transcripts. Output includes the task, key path, deliverables, five-level evidence panel, and traceable source anchors.

## 核心能力 / Highlights

- **五级证据分级 / Five-level evidence**: `self-report` / `tool-evidence` / `external-verification` / `unverified` / `failed`。
- **全树脱敏 / Full-tree redaction**: 密钥、Token、Cookie、连接串、Windows/POSIX 路径统一处理；残留扫描失败时不产出任何文件。
- **来源锚点 / Source anchors**: 关键结论可回跳到脱敏后的输入片段，避免只信 Agent 自报。
- **离线单文件 HTML / Offline HTML**: 无 JavaScript、无外部请求、CSS 内联、CSP 限制。
- **确定性构建 / Deterministic build**: 同一输入重复构建，产物逐字节一致。
- **明确降级 / Honest degradation**: 缺失指标不渲染、不估算；Automation/Schedule 只标「已投递」。

## 产物 / Output

对一次运行输入执行后，输出目录会包含：

```text
casebook.html   # 离线单文件案例页
casebook.md     # Markdown 摘要
run.json        # 脱敏后的结构化运行模型
```

## 快速开始 / Quick Start

### WorkBuddy / DSH 技能用法

把整个 `agent-run-casebook/` 目录安装到对应技能目录后，对 Agent 说：

```text
把这个 DSH /export 导出整理成案例页。
```

或：

```text
读取这份 session.v2.jsonl，生成一份带证据分级的运行报告。
```

### 本地命令行

依赖：Python 3.10+，无第三方必需依赖。

```bash
# 自检
python scripts/casebook.py --selftest

# 回归样本
python scripts/casebook.py --fixtures

# 一键构建
python scripts/casebook.py all <input> --out <output-dir>

# 可选：先用模型生成 narrative.json，再构建叙事模式
python scripts/casebook.py all <input> --out <output-dir> --narrative <narrative.json>
```

支持输入：

- DSH `/export` ZIP
- `session.v2.jsonl` / `session.jsonl`
- 结构化 Markdown 会话

## 安装 / Install

### DSH 插件市场（推荐 / Recommended）

在 DSH 的发现页 / 市场设置中添加本仓库的索引 URL：

```text
https://raw.githubusercontent.com/ljh718/agent-run-casebook/main/dsh-market/index.json
```

国内网络拉取失败时，使用 jsDelivr 镜像索引：

```text
https://cdn.jsdelivr.net/gh/ljh718/agent-run-casebook@main/dsh-market/index.json
```

添加后在列表中选择「Agent 运行报告生成器 / Agent Run Casebook」安装。索引拉取失败或想离线安装时，可用 Release 中的 tarball 或仓库内 `dsh-bundle/` 目录直接安装，详见 `DSH-MARKET.md`。

### WorkBuddy

将 `agent-run-casebook/` 目录复制到：

```text
~/.workbuddy/skills/agent-run-casebook
```

### DSH（手动复制）

任选一个用户级位置：

```text
~/.dsh/skills/agent-run-casebook
~/.agents/skills/agent-run-casebook
```

也可放到项目级：

```text
<project-root>/.dsh/skills/agent-run-casebook
```

### 开放平台 / Open Platform

上传 `agent-run-casebook-openplatform-v1.2.1.zip` 到 WorkBuddy 开放平台；ZIP 解压后第一层应为 `agent-run-casebook/`。

## 目录结构

```text
agent-run-casebook/
├── SKILL.md
├── scripts/
├── references/
├── assets/
├── tests/
├── examples/
├── CHANGELOG.md
└── requirements.txt
```

## 安全边界 / Security

- 只处理用户明确提供的输入，不扫描个人目录。
- 不读取实时 Session，不自动发布到任何平台。
- `normalize` 生成的中间 `run.raw.json` 含未脱敏内容，不能分享。
- 真实 DSH 大型导出尚未实测；当前验收基于符合官方契约的人工样本。

详细限制见 `references/dsh-export.md`。

## License

版权与许可证信息见 `LICENSE`。
