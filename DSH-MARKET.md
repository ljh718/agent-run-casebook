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

## 备选：直接安装入口（索引列表不出现时用）

添加索引后列表为空的常见原因与对策：

1. **网络原因**：`raw.githubusercontent.com` 在无代理环境经常不可达，DSH 拉取索引失败就不会出现列表。可改用 jsDelivr 镜像索引：

   ```text
   https://cdn.jsdelivr.net/gh/ljh718/agent-run-casebook@main/dsh-market/index.json
   ```

2. **市场服务未随 profile 启用**：插件市场属实验性 bundle，部分 profile 默认关闭。此时直接用下面的安装入口，不走浏览列表。

市场安装对话框（或 `dsh plugin add`）支持 tarball / Git / 本地路径，本 bundle 的三个入口：

- **本地 tarball（推荐，离线可用）**

  ```text
  C:\Users\刘俊涵\WorkBuddy\create\outputs\agent-run-casebook\v1.2.1\agent-run-casebook-dsh-bundle-v1.2.1.tgz
  ```

- **Git 地址（完整 pnpm 规格，含子目录）**

  ```text
  git+https://github.com/ljh718/agent-run-casebook.git#v1.2.1&path:/dsh-bundle
  ```

- **本地目录（linked 方式可能不执行 prepare；装完若 `~/.dsh/skills/agent-run-casebook` 未出现，把 `dsh-bundle/skill/` 内容手动复制过去即可）**

  ```text
  C:\Users\刘俊涵\WorkBuddy\create\outputs\github\agent-run-casebook\dsh-bundle
  ```

安装时 pnpm ≥ 10 若提示拦截 prepare 脚本，允许本包（agent-run-casebook）后重试；安装成功的标志是输出 `[agent-run-casebook] skill installed to ...`。

## 另外说明：技能可能已经装好了

`~/.dsh/skills/agent-run-casebook`（v1.2.1）此前已直接部署并通过自检——即使不经过市场安装，新建或刷新 DSH 会话后对 Agent 说「把这份 DSH /export 导出整理成案例页」即可使用。市场安装的意义是纳入 DSH 的插件管理视图。

## 备选：手动复制（原始方式）

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
