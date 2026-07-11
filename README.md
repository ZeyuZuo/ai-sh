# tmksh

把自然语言变成可检查、可解释、可拦截的 shell 命令建议。

`tmksh` 是一个面向开发者和运维人员的命令行助手。你描述想做什么，它会结合当前目录、shell、操作系统和常用工具生成一条 shell 命令，解释它的作用并标记风险。默认 `tmksh` 只展示建议，永不执行；危险命令会在展示前被本地安全层拦截。

第一版默认使用 SiliconFlow 的 OpenAI 兼容 API：

- Base URL: `https://api.siliconflow.cn/v1`
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- API Key: 环境变量 `SILICONFLOW_API`

## Highlights

- 自然语言生成 shell 命令
- Bash、Zsh 和 Fish 原生命令行 Widget，默认快捷键 `Ctrl+G`
- 独立的 `tmksh ask` 管道内容分析和普通问答模式
- 单次建议模式，任何建议都不由 tmksh 执行
- `tmksh --json` 和 `tmksh suggest` 稳定机器接口
- 自动收集 cwd、shell、OS、用户名和 PATH 中的关键工具
- 每条命令都有解释和风险等级
- 本地硬拦截危险命令，不依赖模型自觉
- `safe` 和 `caution` 只展示，`danger` 直接拒绝，默认路径不执行任何命令
- 历史记录本地持久化，权限为 `600`
- 使用 `uv` 管理依赖、测试和构建

## Install

开发版：

```bash
git clone git@github.com:ZeyuZuo/tmksh.git
cd tmksh
uv sync
```

本地运行：

```bash
uv run tmksh --help
```

在当前 Shell 会话加载 Widget：

```bash
# Bash
eval "$(uv run tmksh init bash)"

# Zsh
eval "$(uv run tmksh init zsh)"

# Fish
uv run tmksh init fish | source
```

脚本只注册快捷键，不会修改 `.bashrc` 或 `.zshrc`。确认可用后，可由用户自行把对应的 `eval` 行加入 Shell 配置；正式安装后通常不需要其中的 `uv run`。

首次使用前配置 API：

```bash
uv run tmksh config
```

也可以一次性写入：

```bash
uv run tmksh config \
  --base-url "https://api.siliconflow.cn/v1" \
  --model "deepseek-ai/DeepSeek-V4-Flash" \
  --api-key "your-siliconflow-api-key"
```

构建包：

```bash
uv build
```

如果你的机器没有 `.python-version` 指定的 Python，uv 可能会尝试下载解释器。也可以显式使用已有的 Python：

```bash
uv run --python 3.14 tmksh --help
uv build --python 3.14
```

## Configure

推荐用 `tmksh config` 写入本地配置：

```bash
uv run tmksh config
```

查看当前配置状态：

```bash
uv run tmksh config --show
```

`--show` 不会打印 API key，只会显示是否已配置。

也可以设置环境变量覆盖配置文件里的 API key：

```bash
export SILICONFLOW_API="your-siliconflow-api-key"
```

注意需要使用 `export`，否则它只是当前 shell 的局部变量，`uv run` 启动的 Python 子进程读不到。

也可以在项目根目录创建 `.env`：

```bash
SILICONFLOW_API="your-siliconflow-api-key"
```

配置文件位置：

```text
~/.tmksh/config.toml
```

默认配置：

```toml
[api]
base_url = "https://api.siliconflow.cn/v1"
model = "deepseek-ai/DeepSeek-V4-Flash"
api_key = ""

[behavior]
history_limit = 50
language = "zh"
```

`base_url` 和 `model` 从 `~/.tmksh/config.toml` 读取。`api_key` 的读取优先级是：已 export 的 `SILICONFLOW_API` 环境变量优先，其次是当前目录 `.env`、`~/.tmksh/.env`，最后是配置文件中的 `api_key`。

从旧版升级时，tmksh 会在新文件不存在的前提下，把 `~/.ai-sh` 中的配置、`.env` 和建议历史复制到 `~/.tmksh`。旧目录不会自动删除，可在确认新版本工作正常后自行清理。旧配置中的废弃字段会被忽略。

## Usage

### Shell Widget

加载集成后，在正常 Shell 提示符中按 `Ctrl+G`：

```text
$ <Ctrl+G>
tmksh> 找出当前目录下最大的十个文件

safe · 查找并按大小排序文件
$ find . -type f -printf '%s %p\n' | sort -nr | head -n 10
```

建议命令只写入 Bash 的 `READLINE_LINE` 或 Zsh 的 `BUFFER`，不会执行。用户可以继续编辑，最终由当前 Shell 在用户按 Enter 后执行。

当输入行已经有命令时，Widget 会把它作为修改上下文：

```text
$ find src -type f <Ctrl+G>
tmksh> 按修改时间倒序排列

$ find src -type f -printf '%T@ %p\n' | sort -nr
```

自定义快捷键：

```bash
eval "$(tmksh init bash --key-binding '\C-x\C-a')"
eval "$(tmksh init zsh --key-binding '^X^A')"
tmksh init fish --key-binding '\cx\ca' | source
```

### CLI

单次生成命令建议：

```bash
uv run tmksh "找出当前目录下超过 100MB 的文件"
```

该命令会展示建议、解释和风险，不会执行建议命令。

获取相同结构的 JSON 输出：

```bash
uv run tmksh --json "找出当前目录下超过 100MB 的文件"
```

分析管道内容时使用独立问答模式：

```bash
git diff | uv run tmksh ask "总结这些修改"
journalctl -u my-service -n 200 | uv run tmksh ask "分析失败原因"
```

也可以不使用管道，直接提问：

```bash
uv run tmksh ask "解释 git rebase 和 merge 的区别"
```

`tmksh ask` 直接输出自然语言答案，不生成命令、不进入命令安全或执行流程，也不写入建议历史。管道输入按原始 UTF-8 数据流读取，最多保留 64 KiB；超过限制时 stderr 会显示截断警告，模型也会收到内容不完整的标记。问答失败返回非零退出码。

Shell Widget 使用的版本化 stdin/stdout 协议由 `tmksh suggest` 提供，格式、限制和退出码见 [Shell 原生交互改造方案](docs/SHELL_NATIVE_PLAN.md#7-后端结果协议)。

## Safety Model

`tmksh` 的安全策略是多层的：

1. 模型必须返回 JSON，其中包含 `risk_level`: `safe`、`caution` 或 `danger`。
2. 本地正则和参数解析只硬拦截灾难级危险命令。
3. `danger` 和命中本地硬拦截的命令直接拒绝。
4. `safe` 和 `caution` 命令只展示或填入当前 Shell；`caution` 会同时显示风险原因。
5. tmksh 不提供执行路径；用户按 Enter 后由当前 Shell 原生执行。

本地硬拦截覆盖这些高风险模式：

- `rm -rf /` 及变体
- `rm -rf ~` 及变体
- `mkfs.*`
- `dd ... of=/dev/sd*`
- 重定向写入磁盘设备
- fork bomb
- `base64 -d ... | bash`
- `curl ... | sh` / `wget ... | bash`
- `chmod -R 777 /`

测试只把危险命令作为字符串送入安全检查，不会执行这些命令。

## Development

安装依赖：

```bash
uv sync
```

运行测试：

```bash
uv run pytest tests/
```

运行 lint：

```bash
uv run ruff check .
```

格式化：

```bash
uv run ruff format .
```

构建：

```bash
uv build
```

## Project Layout

```text
src/tmksh/
  answer.py     # 独立问答编排和 stdin 流式限长读取
  cli.py        # click 入口：tmksh 单一命令
  config.py     # 配置读取和默认值
  context.py    # 环境上下文收集
  llm.py        # 命令 JSON 与问答纯文本的独立提示词、调用和解析
  suggestion.py # 建议生成编排和最终安全归一化
  protocol.py   # Shell Widget 使用的版本化机器协议
  shell/        # Bash、Zsh 和 Fish Widget 初始化脚本
  safety.py     # 本地危险命令检测
  history.py    # 本地建议历史
  ui.py         # Rich 人类可读结果渲染
```

## Privacy

- API key 不写入历史。
- API key 不打印到终端。
- 历史记录只保存在本地 `~/.tmksh/history.json`。
- `tmksh ask` 的问题和 stdin 内容不写入持久化历史。
- 除了调用你配置的 API endpoint，项目不会把命令数据发送到其他远端。

## Status

当前版本是 `0.2.0`。默认路径已经取消所有执行能力，并提供 `protocol_version=1` 机器接口、Bash/Zsh/Fish Shell Widget，以及独立的 `tmksh ask` 问答模式。版本变化见 [CHANGELOG](CHANGELOG.md)，从 v0.1 升级见 [迁移说明](docs/MIGRATION_V0.2.md)。

v0.2 已确定改为 Shell 原生交互：通过快捷键把 AI 建议写入当前 Shell 的输入缓冲区，由用户编辑并按 Enter 执行；同时取消默认自动执行，并将管道问答与命令生成分离。当前产品路线见 [产品与工程路线](docs/ROADMAP.md)，Shell 原生改造的设计背景见 [Shell 原生交互改造方案](docs/SHELL_NATIVE_PLAN.md)。
