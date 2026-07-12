# Changelog

本项目的主要变化记录在此文件中。

## Unreleased

### Added

- 在统一 `tmksh>` 提示符中增加 `/fix [补充信息]`，修复最近一条非零退出命令。
- Bash、Zsh 和 Fish 集成会在本地保存最近失败命令、退出码、执行目录和 Shell 类型。
- `protocol_version=1` 增加可选 `failed_command` 上下文，并保持旧 JSON 和双字段 NUL 客户端兼容。

### Security

- `/fix` 结果经过与普通建议相同的 AI danger 判断和本地硬拦截。
- 失败状态钩子不捕获、不持久化也不上传 stdout/stderr；错误、取消和拦截不会修改原 buffer。

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
