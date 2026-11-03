# agent-run-casebook 变更说明

## v1.0.2（2026-11）

发布包结构修正版本。

### 变更

- 为 WorkBuddy 开放平台生成专用上架包：保留 `{skill-name}/` 根目录，
  并移除 `examples/` 内的第三层嵌套目录，满足
  “根目录 / 二级目录 / 文件”的结构限制。
- 为 WorkBuddy 本地上传生成专用 ZIP：`SKILL.md` 直接位于 ZIP 根目录，
  避免导入器找不到技能定义。
- 版本号更新为 1.0.2；功能逻辑不变。

## v1.0.1（2026-11）

发布准备版本。

### 变更

- 补充 WorkBuddy 开放平台市场所需的 `display_name`、`display_name_en`、
  `category` 字段。
- 版本号更新为 1.0.1；功能逻辑不变。

## v1.0.0（2026-11）

首版发布。

### 能力

- 输入识别与归一化：DSH /export ZIP、单份 session JSONL、结构化 / 通用
  Markdown 会话；同文档作用域内 callId 与 toolCallId 配对；确定性 source_ref
  与页面锚点；未知字段只保留来源引用与警告。
- 五级证据：self-report / tool-evidence / external-verification / unverified /
  failed，全部由脚本按检查记录确定性判定；Automation 只标「已投递」且证据封顶。
- 叙事白名单：语言模型产出的叙事文件经 schema、引用、事实集、等级字样与
  长度五项核验；违规即拒或降级事实模式，绝不放行违规叙事。
- 全树脱敏：结构化敏感键、密钥与令牌样式、URL 凭据、连接串、Cookie、
  Windows / POSIX 中文路径；残留扫描为硬门，不通过不落盘任何产物。
- 离线渲染：无 JavaScript、无外部请求、全字段转义的单文件 HTML，
  Markdown 摘要与脱敏运行模型同步输出；同一输入重复构建逐字节一致。

### 边界

- 不做回放、跨 Agent 对比、日报聚合、自动发布、实时会话读取。
- 不打包原始附件字节与隐藏推理；附件只记元数据。
- 真实 DSH 导出样本暂缺，验收基于人工构造样例，实证验证待用户提供导出。

### 占位文件改造映射

- scripts/example.py：占位脚本改造为 examples 演示运行器（文件名不变）。
- assets/example_asset.txt：占位说明改造为页面设计基线注记（文件名不变）。
- references/api_reference.md：占位参考改造为 CLI 接口、运行模型与叙事协议
  参考（文件名不变）。
