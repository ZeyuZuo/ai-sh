# ai-sh

把自然语言变成可检查、可解释、可拦截的 shell 命令建议。

`ai-sh` 是一个面向开发者和运维人员的命令行助手。你描述想做什么，它会结合当前目录、shell、操作系统和常用工具生成一条 shell 命令，解释它的作用并标记风险。默认 `ai` 只展示建议，永不执行；危险命令会在展示前被本地安全层拦截。

第一版默认使用 SiliconFlow 的 OpenAI 兼容 API：

- Base URL: `https://api.siliconflow.cn/v1`
- Model: `deepseek-ai/DeepSeek-V3.2`
- API Key: 环境变量 `SILICONFLOW_API`

## Highlights

- 自然语言生成 shell 命令
- 单次建议模式和显式 legacy REPL
- `ai --json` 和 `ai-sh suggest` 稳定机器接口
- 自动收集 cwd、shell、OS、用户名和 PATH 中的关键工具
- 每条命令都有解释和风险等级
- 本地硬拦截危险命令，不依赖模型自觉
- `safe` 和 `caution` 只展示，`danger` 直接拒绝，默认路径不执行任何命令
- 历史记录本地持久化，权限为 `600`
- 使用 `uv` 管理依赖、测试和构建

## Install

开发版：

```bash
git clone git@github.com:ZeyuZuo/ai-sh.git
cd ai-sh
uv sync
```

本地运行：

```bash
uv run ai --help
uv run ai-sh --help
```

首次使用前配置 API：

```bash
uv run ai-sh config
```

也可以一次性写入：

```bash
uv run ai-sh config \
  --base-url "https://api.siliconflow.cn/v1" \
  --model "deepseek-ai/DeepSeek-V3.2" \
  --api-key "your-siliconflow-api-key"
```

构建包：

```bash
uv build
```

如果你的机器没有 `.python-version` 指定的 Python，uv 可能会尝试下载解释器。也可以显式使用已有的 Python：

```bash
uv run --python 3.14 ai --help
uv build --python 3.14
```

## Configure

推荐用 `ai-sh config` 写入本地配置：

```bash
uv run ai-sh config
```

查看当前配置状态：

```bash
uv run ai-sh config --show
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

也可以生成默认配置文件：

```bash
uv run ai --init-config
```

配置文件位置：

```text
~/.ai-sh/config.toml
```

默认配置：

```toml
[api]
base_url = "https://api.siliconflow.cn/v1"
model = "deepseek-ai/DeepSeek-V3.2"
api_key = ""

[behavior]
default_confirm = "n"
history_limit = 50
context_commands = 5
language = "zh"

[safety]
hard_block_enabled = true
```

`base_url` 和 `model` 从 `~/.ai-sh/config.toml` 读取。`api_key` 的读取优先级是：已 export 的 `SILICONFLOW_API` 环境变量优先，其次是当前目录 `.env`、`~/.ai-sh/.env`，最后是配置文件中的 `api_key`。

## Usage

单次生成命令建议：

```bash
uv run ai "找出当前目录下超过 100MB 的文件"
```

该命令会展示建议、解释和风险，不会执行建议命令。

获取相同结构的 JSON 输出：

```bash
uv run ai --json "找出当前目录下超过 100MB 的文件"
```

Shell Widget 使用的版本化 stdin/stdout 协议由 `ai-sh suggest` 提供，格式、限制和退出码见 [Shell 原生交互改造方案](docs/SHELL_NATIVE_PLAN.md#7-后端结果协议)。

旧版 REPL 暂时保留为显式 legacy 命令：

```bash
uv run ai-sh repl
```

REPL 示例：

```text
ai> 找出最近一天修改的 python 文件
ai> 把刚才的结果只保留 src/ 目录下的
ai> 用 wc -l 统计一下行数
```

`--dry-run` 仅作为兼容参数保留；默认 `ai` 已经始终是 dry-run 语义。

## Safety Model

`ai-sh` 的安全策略是多层的：

1. 模型必须返回 JSON，其中包含 `risk_level`: `safe`、`caution` 或 `danger`。
2. 本地正则和参数解析只硬拦截灾难级危险命令。
3. `danger` 和命中本地硬拦截的命令直接拒绝。
4. `safe` 和 `caution` 命令只展示建议与风险，不进入执行流程。
5. 只有显式调用的 legacy REPL 暂时保留旧执行能力。

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
src/ai_sh/
  cli.py        # click 入口：ai 和 ai-sh
  config.py     # 配置读取和默认值
  context.py    # 环境上下文收集
  llm.py        # SiliconFlow/OpenAI 兼容调用和 JSON 解析
  suggestion.py # 建议生成编排和最终安全归一化
  protocol.py   # Shell Widget 使用的版本化机器协议
  safety.py     # 本地危险命令检测
  executor.py   # legacy REPL 的 subprocess 执行
  history.py    # 建议历史和 legacy REPL 上下文
  ui.py         # Rich 人类可读结果渲染
```

## Privacy

- API key 不写入历史。
- API key 不打印到终端。
- 历史记录只保存在本地 `~/.ai-sh/history.json`。
- 除了调用你配置的 API endpoint，项目不会把命令数据发送到其他远端。

## Status

包版本当前仍是 `0.1.0`，源码正在开发 v0.2。阶段一已经取消默认执行并统一结果模型；阶段二已经建立 `protocol_version=1` 的机器接口。legacy REPL 只用于迁移兼容。

v0.2 已确定改为 Shell 原生交互：通过快捷键把 AI 建议写入当前 Shell 的输入缓冲区，由用户编辑并按 Enter 执行；同时取消默认自动执行，并将管道问答与命令生成分离。目标逻辑和分阶段开发计划见 [Shell 原生交互改造方案](docs/SHELL_NATIVE_PLAN.md)。
