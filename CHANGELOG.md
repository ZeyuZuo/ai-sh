# Changelog

本项目的主要变化记录在此文件中。

## Unreleased

### Added

- 在统一 `tmksh>` 提示符中增加 `/fix [补充信息]`，修复最近一条非零退出命令。
- 完成 `/explain`、`/check`、`/new`、`/ask` 和 `/help`，与普通自然语言及 `/fix` 共用本地指令解析和分派。
- `/explain` 和 `/check` 优先分析当前 buffer，为空时回退到 Shell 保存的上一条命令；文本结果不修改 buffer 或 cursor。
- `/help` 和未知指令在本地返回，未知指令会提示相近的受支持指令，不调用 API。
- Bash、Zsh 和 Fish 集成会分别保存上一条命令，以及最近失败的命令、退出码、执行目录和 Shell 类型，供文本分析回退和 `/fix` 使用。
- `protocol_version` 保持为 1；JSON 请求支持可选 `failed_command` 和 `last_command`，NUL 输入兼容旧 2/6 字段帧，并以第 7 字段追加上一条命令。

### Changed

- 三种 Shell Widget 按响应 `kind` 统一处理 command、answer、clarification、blocked 和 error；只有成功的 command 结果可以替换 buffer。
- `/new` 始终忽略当前 buffer，`/ask` 始终使用纯文本问答路径且不写入建议历史。
- `/check` 报告由本地校验并规范化为风险、正确性、兼容性和建议四项，支持 `zh`、`en` 与自动语言配置。

### Fixed

- 修复 Bash `PROMPT_COMMAND` 中使用 `fc` 读取到上一条历史，导致失败退出码与旧命令错误配对的问题。
- 当前命令被 Bash 历史规则忽略时，不再把失败状态错误关联到旧历史命令。
- 修复 Bash `HISTCONTROL=erasedups` 复用历史编号时丢失失败命令状态的问题。
- 在其他 prompt hook 完成历史同步后更新 Bash 基线，避免误配其他终端追加的命令。

### Security

- `/fix` 结果经过与普通建议相同的 AI danger 判断和本地硬拦截。
- 失败状态钩子不捕获、不持久化也不上传 stdout/stderr；错误、取消和拦截不会修改原 buffer。
- 非 command 响应会清空协议中的 `command`；文本回答即使遇到异常载荷也不能写入 Shell buffer。

## 0.2.1 - 2026-07-12

### Fixed

- 修复复合命令控制符、根目录 glob 和 Shell `-c` 包装绕过危险 `rm` 本地拦截的问题。
- 普通命令建议模式现在会脱敏 API 错误中的 credential，并在失败时返回非零退出码。
- 普通命令建议模式在 Ctrl+C 时返回退出码 130。

### Security

- 扩展 API key、Bearer token、credential 和 access token 的错误信息脱敏。

## 0.2.0 - 2026-07-12

### Added

- Bash Readline、Zsh ZLE 和 Fish commandline 原生 Widget。
- `tmksh suggest` 的 `protocol_version=1` JSON/NUL 机器协议。
- `tmksh --json` 稳定机器输出。
- 独立的 `tmksh ask` 纯文本问答和有界 stdin 分析。
- `safe`、`caution`、`danger` 风险结果与不可关闭的本地硬拦截。
- Python 3.10/3.14 CI、Ruff、首批 strict mypy 和 wheel smoke test。
- LLM 超时、连接失败、限流和 JSON mode 降级的 mock 测试。

### Changed

- SiliconFlow 默认模型更新为 `deepseek-ai/DeepSeek-V4-Flash`。
- 默认产品形态从独立 CLI/REPL 改为 Shell 输入 buffer 助手。
- 所有命令建议仅展示或写入 buffer，最终由用户在当前 Shell 中执行。
- 项目、包和公开命令统一命名为 `tmksh`。
- 建议历史不再推断命令是否执行。

### Removed

- 自动执行和内部 subprocess 执行器。
- Legacy REPL、`y/e/n` 确认菜单和外部编辑器流程。
- `default_confirm`、`context_commands` 和可关闭硬拦截的配置能力。
- 备选命令编号菜单。

### Security

- 协议和用户错误会脱敏 API key、Bearer token 和常见 credential 表达。
- 危险或本地硬拦截结果不会修改 Shell buffer。
- Widget 取消、API 失败和协议错误会恢复原始 buffer 与 cursor。
