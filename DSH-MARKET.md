# agent-run-casebook 的 DSH 插件市场发布指南

本仓库同时以 **DSH bundle** 形式发布，可通过 DSH 插件市场（Discover 页）安装。

## 包结构

```text
dsh-bundle/            DSH bundle 包（市场安装的就是它）
├── package.json       声明 dsh.bundle.patch 与 prepare 脚本
├── cordis.patch.yml   空 patch 层（技能不需要 Host 插件行）
├── prepare.mjs        安装时把 skill/ 复制到 <dshHome>/skills/agent-run-casebook
└── skill/             技能文件本体（与根目录技能源码同版本）

dsh-market/index.json  市场索引（格式 1），列出本 bundle 与安装参数
```

## 在 DSH 中添加市场索引

1. 打开 DSH → 发现（Discover）页或插件市场设置。
2. 添加索引 URL：

   ```text
   https://raw.githubusercontent.com/ljh718/agent-run-casebook/main/dsh-market/index.json
   ```

3. 在列表中找到「Agent 运行报告生成器」（Agent Run Casebook）→ 安装。

## 安装行为

- 市场通过 pnpm 从 GitHub 安装 `dsh-bundle/` 目录（commit 固定）。
- pnpm ≥ 10 可能拦截 `prepare` 构建脚本；按提示允许本包（或在 profile 的
  `pnpm-workspace.yaml` 中加入 `allowBuilds: { "agent-run-casebook": true }` 后重试）。
- `prepare` 会把技能文件复制到 `<dshHome>/skills/agent-run-casebook`
  （`DSH_HOME` 未设置时默认 `~/.dsh`），DSH 新建或刷新会话后即可使用。
- 卸载 bundle 不会自动删除已复制的技能目录；如需彻底移除，请手动删除
  `<dshHome>/skills/agent-run-casebook`。

## 备选：不经过市场安装

市场安装对话框也接受 Git 地址 / tarball / 本地路径：

```bash
# pnpm 语义（DSH CLI 环境）
dsh plugin --profile <你的profile> add https://github.com/ljh718/agent-run-casebook.git
```

或直接把 `agent-run-casebook/`（仓库根目录的技能源码）复制到 `<dshHome>/skills/`。

## 版本更新

发新版本时：更新 `dsh-bundle/` 中的 package.json 版本与 `skill/` 内容，在
`dsh-market/index.json` 的 versions 中追加新条目（commit 固定到发版提交），
推送到 GitHub 后市场会自动拉取最新索引。
