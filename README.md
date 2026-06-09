# ai-sh

把自然语言变成可确认、可解释、可拦截的 shell 命令。

`ai-sh` 是一个面向开发者和运维人员的命令行助手。你描述想做什么，它会结合当前目录、shell、操作系统和常用工具生成一条 shell 命令，解释它的作用并标记风险。只读或低风险命令默认自动执行；有风险的命令会先确认；危险命令会被拒绝。

第一版默认使用 SiliconFlow 的 OpenAI 兼容 API：

- Base URL: `https://api.siliconflow.cn/v1`
- Model: `deepseek-ai/DeepSeek-V3.2`
- API Key: 环境变量 `SILICONFLOW_API`

## Highlights

- 自然语言生成 shell 命令
- 单次模式和 REPL 连续对话
- 支持 `stdin` 上下文，例如 `git diff | ai "总结这次改动"`
- 自动收集 cwd、shell、OS、用户名和 PATH 中的关键工具
- 每条命令都有解释、风险等级和可选替代方案
- 本地硬拦截危险命令，不依赖模型自觉
- `safe` 命令默认自动执行，`caution` 命令确认一次，`danger` 命令直接拒绝
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

单次生成命令：

```bash
uv run ai "找出当前目录下超过 100MB 的文件"
```

如果输出里有备选命令，可以在确认提示处输入对应编号切换到备选命令，例如输入 `1` 使用第一个备选；切换后会重新展示命令并再次确认。

从管道读取上下文：

```bash
git diff | uv run ai "帮我总结这次改动"
cat error.log | uv run ai "这个报错是什么意思，怎么修"
```

进入 REPL：

```bash
uv run ai-sh
```

REPL 示例：

```text
ai> 找出最近一天修改的 python 文件
ai> 把刚才的结果只保留 src/ 目录下的
ai> 用 wc -l 统计一下行数
```

只生成和检查，不执行：

```bash
uv run ai --dry-run "删除 build 目录"
```

## Safety Model

`ai-sh` 的安全策略是多层的：

1. 模型必须返回 JSON，其中包含 `risk_level`: `safe`、`caution` 或 `danger`。
2. 本地正则和参数解析只硬拦截灾难级危险命令。
3. `danger` 命令直接拒绝，不进入确认流程。
4. `caution` 命令需要用户明确确认一次。
5. `safe` 且未命中硬拦截的命令默认自动执行；使用 `--dry-run` 可只查看不执行。

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
  safety.py     # 本地危险命令检测
  executor.py   # subprocess 执行和输出捕获
  history.py    # 历史持久化和 REPL 上下文
  ui.py         # rich 渲染和确认交互
```

## Privacy

- API key 不写入历史。
- API key 不打印到终端。
- 历史记录只保存在本地 `~/.ai-sh/history.json`。
- 除了调用你配置的 API endpoint，项目不会把命令数据发送到其他远端。

## Status

当前版本是 `0.1.0`。目标是先把自然语言到命令的核心工作流做稳：生成、解释、安全拦截、确认执行和 REPL 连续追问。
