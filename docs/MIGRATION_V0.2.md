# 从 v0.1 升级到 v0.2

v0.2 将 tmksh 从“生成并执行命令的 CLI”改为“当前 Shell 的命令输入助手”。这是有意的安全行为变更。

## 配置和本地数据

- 默认目录是 `~/.tmksh`。
- 当目标文件不存在时，tmksh 会从旧 `~/.ai-sh` 复制 `config.toml`、`.env` 和 `history.json`。
- API key 优先级仍是 `SILICONFLOW_API`、当前目录 `.env`、`~/.tmksh/.env`、配置文件。
- 旧目录不会自动删除。
- 旧配置中的 `default_confirm`、`context_commands` 和 `hard_block_enabled` 会被忽略。
- 旧历史中的 `executed` 和 `exit_code` 字段会被兼容读取但不再写入。

确认新配置和历史可用后，可以自行删除 `~/.ai-sh`。

## 命令行为

以下能力已经删除：

- 默认或 `safe` 命令自动执行。
- `tmksh repl`。
- `y/e/n` 执行确认和外部编辑器流程。
- `--dry-run`；所有建议现在天然都是未执行状态。

直接调用仍然可用，但只展示建议：

```bash
tmksh "找出当前目录最大的十个文件"
```

管道分析应迁移到独立问答命令：

```bash
git diff | tmksh ask "总结这些修改"
```

## 启用 Shell Widget

初始化脚本只影响当前会话，不会修改 Shell 配置文件：

```bash
# Bash
eval "$(tmksh init bash)"

# Zsh
eval "$(tmksh init zsh)"

# Fish
tmksh init fish | source
```

默认快捷键是 `Ctrl+G`。建议命令会进入当前输入 buffer，用户可以继续编辑，按 Enter 后由当前 Shell 原生执行。

## 机器调用

不要解析 Rich 人类输出。机器调用使用：

```bash
tmksh --json "列出 Python 文件"
```

Shell 集成或其他客户端使用 `tmksh suggest` 和 `protocol_version=1`。退出码及字段定义见 [Shell 原生交互改造方案](SHELL_NATIVE_PLAN.md#7-后端结果协议)。
