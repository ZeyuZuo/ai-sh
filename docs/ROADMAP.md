# tmksh 产品与工程路线

**状态：** Draft  
**更新日期：** 2026-07-12  
**产品定位：** 在用户当前 Shell 中，用自然语言生成、解释和修正下一条可编辑命令。

## 1. 产品边界

tmksh 是 Shell 输入助手，不是另一个 Shell，也不是无人值守 Agent。

必须长期保持以下约束：

- AI 生成的命令只展示或写入当前 Shell buffer，tmksh 不执行。
- 用户按 Enter 后，命令由 Bash、Zsh 或 Fish 原生执行。
- `danger` 和本地硬拦截结果不能进入 buffer。
- 默认只发送完成当前请求所需的最少上下文。
- 不自动修改 Shell 配置，不启动后台常驻服务。
- 命令建议和自然语言问答继续使用独立路径。

## 2. 外部项目启发

路线参考了以下同类工具，但只吸收符合上述边界的能力：

| 项目 | 可借鉴能力 | 不采用的方向 |
|---|---|---|
| [ovh/shai](https://github.com/ovh/shai) | 失败命令修复、项目上下文文件 | Coding Agent、MCP、HTTP 服务 |
| [AI-Shell-Team/aish](https://github.com/AI-Shell-Team/aish) | 分层安全策略、多模型配置 | 完整 PTY Shell、沙箱执行、长期记忆 |
| [ShellGPT](https://github.com/TheR1D/shell_gpt) | Shell buffer 集成、命令解释、多后端 | 自动执行、函数调用 |
| [AIChat](https://github.com/sigoden/aichat) | Provider profiles、显式文件输入 | RAG、Agent、Web UI |
| [Butterfish](https://github.com/bakks/butterfish) | 失败上下文、Prompt 透明性 | Shell 包装器、自动补全调用、无人值守模式 |

## 3. 当前基线

已经具备：

- Bash Readline 和 Zsh ZLE Widget。
- `protocol_version=1` 的 JSON/NUL 机器协议。
- OpenAI-compatible 命令生成和独立 `ask` 问答。
- 当前 cwd、OS、Shell 和可用工具上下文。
- AI 风险等级与不可关闭的本地硬拦截。
- 失败时恢复原始 buffer 和 cursor。
- 有界 stdin、错误脱敏和本地建议历史。

当前主要缺口：

- 尚无 Fish 集成和正式 CI 发布链。
- 模型不了解项目约定，也不了解上一条失败命令。
- 非空 buffer 只能笼统视为“修改”，缺少明确的解释和检查操作。
- 单一 API 配置不利于本地、工作和个人环境切换。
- 用户难以确认实际发送给模型的上下文。

## 4. 实施路线

### P0：完成 v0.2 发布基础

先完成现有产品承诺，避免在跨 Shell 和发布质量不稳定时扩展上下文面。

工作项：

- 实现 `tmksh init fish`，与 Bash/Zsh 共用协议和风险语义。
- 建立 CI，覆盖 Python 3.10 和当前稳定版的 pytest、Ruff、构建。
- 增加 wheel 安装后的 CLI smoke test。
- 为 LLM 超时、限流、JSON mode 降级增加 mock 测试。
- 引入 mypy，先覆盖 config、protocol、suggestion 和 shell script renderer。
- 发布前统一版本号、README、迁移说明和 changelog。

完成标准：

- 三种 Shell 都支持生成、修改、取消、澄清、风险提示和失败恢复。
- 全新环境安装 wheel 后，`config`、建议、`ask`、`init` 和 `suggest` 可用。
- CI 全绿才能生成发布产物。

### P1：高价值上下文

#### 4.2.1 项目上下文文件

支持仓库级 `TMKSH.md`，用于声明构建命令、目录约束、工具偏好和项目术语。

实现约束：

- 从 cwd 向上查找，最多到 Git 根目录，不跨越仓库边界。
- 限制文件大小；读取失败时不阻断普通建议。
- 在请求中明确标记为数据上下文，降低 prompt injection 风险。
- `--debug-context` 能显示是否加载、来源和截断状态。

完成标准：模型能稳定遵循项目指定的测试工具和禁止目录，并有边界、截断及注入测试。

#### 4.2.2 上一条失败命令修复

Shell hook 只在本地保留上一条命令、退出码和有界输出摘要。用户主动按快捷键并请求修复时才发送。

实现约束：

- 默认不持续上传，不持久化完整终端输出。
- 对 API key、Bearer token、常见 credential 形式做脱敏。
- Bash 使用 `PROMPT_COMMAND`，Zsh 使用 `preexec/precmd`，Fish 使用 event hook。
- hook 失败不得影响正常 Shell 提示符。
- 修复结果仍只写入 buffer，不自动执行。

完成标准：失败命令可在三种 Shell 中被主动修复；成功命令、取消和 API 失败不会污染 buffer。

#### 4.2.3 Buffer 操作模式

为非空 buffer 区分三种明确意图：

- `modify`：生成替换后的命令。
- `explain`：解释命令，不修改 buffer。
- `check`：检查语义、可移植性和风险，不修改 buffer。

协议优先新增可选请求字段并保持 v1 老客户端可用；不要依赖模型猜测所有模式。

完成标准：解释和检查路径在任何结果下都不替换原 buffer，修改路径继续执行本地安全归一化。

### P2：配置与信任

#### 4.3.1 Provider Profiles

支持命名配置，例如 `personal`、`work` 和 `local`：

```bash
tmksh profile list
tmksh profile use local
tmksh profile show work
```

每个 profile 只抽象 OpenAI-compatible 的 `base_url`、`model`、API key 来源和 timeout。密钥优先来自环境变量，不在命令参数或列表输出中显示。

#### 4.3.2 上下文透明模式

增加 `tmksh --debug-context` 或等价诊断命令，展示：

- 上下文字段名称和来源。
- 各字段字符数及是否截断。
- 当前生效 profile、模型和 endpoint host。
- 已执行的脱敏类型。

默认不打印完整 stdin、Shell 输出、API key 或 Authorization 值。

#### 4.3.3 可配置安全策略

在内置硬拦截之上增加系统级和用户级策略：

- 受保护路径。
- 禁止生成的命令或子命令。
- 必须提升为 `caution` 的模式。
- `/etc/tmksh/policy.toml` 与 `~/.tmksh/policy.toml` 叠加。

用户策略只能收紧，不能关闭或覆盖内置硬拦截。

### P3：受控扩展

仅在 P0-P2 稳定后评估：

- `ask` 显式附加文件，并提供大小、类型和数量限制。
- `ask` 流式输出及可靠的 Ctrl+C 取消。
- 临时或命名问答会话，默认不持久化 stdin。
- 用户可编辑的 prompt 模板，但必须提供版本和恢复默认机制。
- 确定性请求缓存，缓存键必须包含模型、prompt 版本和上下文摘要。

## 5. 明确不做

- 自动执行、后台执行或跳过确认的危险模式。
- 完整 PTY Shell、作业控制或 Shell 历史替代品。
- 自动扫描并上传整个仓库。
- 默认长期记忆、遥测或云端历史同步。
- MCP、通用工具调用、RAG、HTTP Server 和多 Agent 编排。
- 自动修改 `.bashrc`、`.zshrc` 或 Fish 配置。

这些能力会扩大权限、安全和维护范围，并削弱“可检查的下一条命令”这一核心定位。

## 6. 工程原则

- 新上下文必须有来源、大小上限、截断标记、脱敏和测试。
- Shell 之间只允许交互适配层不同，后端协议和安全决策保持一致。
- 协议字段先向后兼容扩展；破坏性变更必须提升 `protocol_version`。
- 安全判断必须在模型输出后、本地展示或插入前执行。
- 对外部 API、文件和 Shell hook 的失败采用 fail closed 或保持原 buffer。
- 每个路线阶段单独提交，功能、测试和文档在同一提交中完成。

## 7. 推荐提交顺序

1. `Add Fish shell integration`
2. `Add release CI and wheel smoke tests`
3. `Load bounded project context from TMKSH.md`
4. `Capture failed command context in shell widgets`
5. `Add explain and check buffer modes`
6. `Add named provider profiles`
7. `Expose redacted context diagnostics`
8. `Add layered local safety policies`

每一步都应保持默认路径不执行命令，并通过现有协议、安全和 Shell 集成回归测试。
