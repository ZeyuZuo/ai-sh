# AGENT.md — ai-sh 开发规范与实现注意事项

本文档面向 AI 编码助手（Claude Code、Cursor、Copilot 等）。在开始编写任何代码之前，请完整阅读本文件。

---

## 项目概述

`ai-sh` 是一个 Python 命令行工具，让用户用自然语言描述意图、AI 翻译成 shell 命令、确认后执行。详细需求见 `PRD.md`。

---

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.10+ | 使用 `match` 语句和 `|` 类型联合 |
| AI 接口 | OpenAI Python SDK（`openai` 包） | 通过 `base_url` 支持任意兼容接口 |
| CLI 框架 | `click` | 命令、选项、参数解析 |
| 终端 UI | `rich` | 面板、语法高亮、颜色、进度 |
| 交互输入 | `prompt_toolkit` | REPL 模式的行编辑、历史、补全 |
| 配置 | `tomllib`（标准库）+ 手动写入 | 读配置用标准库，写配置用字符串拼接 |
| 包管理 | `uv` | 依赖、虚拟环境、运行命令均优先使用 `uv` |
| 打包 | `pyproject.toml` + `hatchling` | 支持 `uv build` 和 `pip install ai-sh` |

---

## AI 接口规范

### 优先使用 SiliconFlow OpenAI 兼容接口

**第一版默认使用 SiliconFlow 的 OpenAI 兼容 API**。所有 AI 调用必须通过 `openai` Python SDK，通过 `base_url` 参数适配服务商。不直接使用 `anthropic` SDK 或任何厂商专有 SDK。

默认配置：

- `base_url`: `https://api.siliconflow.cn/v1`
- `model`: `deepseek-ai/DeepSeek-V3.2`
- `api_key`: 优先读取环境变量 `SILICONFLOW_API`

```python
import os

from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API") or config.api_key,
    base_url=config.base_url,  # 默认 "https://api.siliconflow.cn/v1"
)

response = client.chat.completions.create(
    model=config.model,  # 默认 "deepseek-ai/DeepSeek-V3.2"
    messages=messages,
    response_format={"type": "json_object"},  # 强制 JSON 输出
    temperature=0.2,  # 命令生成场景需要低随机性
)
```

### 兼容性注意事项

- `response_format={"type": "json_object"}` 并非所有兼容接口都支持，实现时需要 try/except，降级方案是在 prompt 中强调 JSON 格式并在客户端做解析容错
- `temperature` 参数各服务商行为可能略有差异，不依赖精确数值，保持在 0.1–0.3 区间即可
- 流式输出（streaming）在 v0.1 中不使用，保持简单
- 不使用任何 OpenAI 专有功能（`tools`/`function_calling` 的具体格式、`assistants` API 等）

### Prompt 设计原则

- System prompt 要求 AI **只返回 JSON**，不加 markdown fence（` ```json ``` `），方便直接 `json.loads()`
- 如果解析失败，用正则从响应中提取 JSON 块作为降级方案，不要直接报错退出
- 对话历史只保留最近 10 轮，超出时从头部裁剪，避免超出 context window
- 执行结果回写对话历史时只保留前 500 字符，避免 stdout 过长撑爆 context

---

## 项目结构约定

```
ai-sh/
├── src/
│   └── ai_sh/
│       ├── __init__.py
│       ├── cli.py          # click 入口，ai 和 ai-sh 两个命令
│       ├── config.py       # 配置读写，Config dataclass
│       ├── context.py      # 环境上下文收集
│       ├── llm.py          # OpenAI SDK 封装，prompt 管理
│       ├── safety.py       # 本地危险命令检测
│       ├── executor.py     # subprocess 执行，输出捕获
│       ├── history.py      # 对话历史 + 命令历史持久化
│       └── ui.py           # rich 渲染，交互提示
├── tests/
│   ├── test_safety.py
│   ├── test_context.py
│   └── test_llm.py         # 用 mock，不真实调用 API
├── pyproject.toml
├── README.md
├── PRD.md
└── AGENT.md                # 本文件
```

- 所有源码放在 `src/ai_sh/` 下，使用 `src` layout
- 不在根目录散落 `.py` 文件
- 测试文件与源文件结构对应，一一映射

---

## 模块职责边界

每个模块只做一件事，不互相越权：

- `cli.py`：解析参数，调用其他模块，不包含业务逻辑
- `config.py`：配置的读取和默认值，不做任何 I/O 之外的事
- `context.py`：收集环境信息，返回 dict，不调用 AI
- `llm.py`：封装 AI 调用，输入 messages，输出 `CommandResult`，不知道终端 UI
- `safety.py`：纯函数，输入命令字符串，输出判断结果，无副作用
- `executor.py`：执行命令，捕获输出，不做安全判断
- `history.py`：读写历史文件，不知道命令是否危险
- `ui.py`：只做渲染和用户输入，不调用 AI，不执行命令

**禁止跨层调用**：`safety.py` 不能 `import llm`，`llm.py` 不能 `import ui`，以此类推。

---

## 数据结构

使用 `dataclass` 或 `TypedDict`，不用裸 dict 传递核心数据：

```python
# llm.py
@dataclass
class CommandResult:
    command: str
    explanation: str
    risk_level: Literal["safe", "caution", "danger"]
    risk_reason: str = ""
    alternatives: list[str] = field(default_factory=list)

# safety.py
@dataclass
class SafetyVerdict:
    action: Literal["allow", "block"]
    reason: str = ""

# history.py
@dataclass
class HistoryEntry:
    timestamp: str        # ISO 8601
    user_input: str
    command: str
    executed: bool
    exit_code: int | None = None
```

---

## 安全实现要点

### 硬拦截模式

`safety.py` 中的正则模式列表是安全底线，**不得删减，只可增加**。

每个模式必须有注释说明它防御什么攻击：

```python
HARD_BLOCK_PATTERNS: list[tuple[str, str]] = [
    # (pattern, human-readable reason)
    (r"rm\s+-rf\s+/(?:\s|$)", "删除根目录"),
    (r"rm\s+-rf\s+~(?:\s|$)", "删除用户主目录"),
    (r"mkfs\.", "格式化磁盘分区"),
    (r"dd\s+.*of=/dev/(?:sd|nvme|disk)", "直接写入磁盘设备"),
    (r":\(\)\{.*\}\;:", "fork bomb"),
    (r"base64\s+-d.*\|\s*(?:ba|z|fi)?sh", "远程代码执行管道"),
    (r"chmod\s+-R\s+777\s+/(?:\s|$)", "全盘权限放开"),
]
```

### 命令执行隔离

- 用 `subprocess.run()` 执行命令，**不用 `os.system()`、`eval()`、`exec()`**
- 设置 `shell=True` 时要明确注释原因（需要支持管道和重定向）
- 设置执行超时（默认 30 秒），超时后向用户报告而非永久挂起
- 不以 root 身份运行，不做 privilege escalation

### API Key 保护

- 读取优先级：环境变量 `SILICONFLOW_API` > 配置文件 `~/.ai-sh/config.toml`
- **任何日志、错误信息、历史记录中不得出现 API Key 的任何部分**
- 配置文件权限在写入时设置为 `0o600`

---

## 错误处理规范

- 所有对外部系统的调用（API、文件、subprocess）必须有 try/except
- 错误信息面向用户，说明发生了什么、能做什么，不暴露 stack trace（除非 `--debug` 模式）
- 使用自定义异常类，不 raise 裸 `Exception`：

```python
# 在 ai_sh/exceptions.py 中定义
class AiShError(Exception): ...
class ApiError(AiShError): ...
class ConfigError(AiShError): ...
class SafetyBlockedError(AiShError): ...
class ExecutionError(AiShError): ...
```

- 网络超时、API 限流（429）要给出明确提示，不让用户盯着光标发呆

---

## 测试要求

- `safety.py` 必须有完整的单元测试，覆盖所有硬拦截模式和边缘情况
- `llm.py` 的测试使用 `unittest.mock.patch` mock OpenAI 客户端，不发真实请求
- `context.py` 的测试在隔离环境中运行，不依赖真实文件系统状态
- 不为 `ui.py` 写测试（终端 UI 交互测试性价比低）
- 运行测试：`pytest tests/`，CI 中必须全部通过才能合并

---

## 代码风格

- 格式化工具：`ruff format`
- Lint 工具：`ruff check`
- 类型检查：`mypy --strict`（逐步达到，不要求一次性全过）
- 函数签名必须有类型标注
- 公共函数必须有 docstring（一句话说明作用即可）
- 不用 `print()`，全部通过 `rich.console.Console` 或标准 `logging` 输出

---

## 禁止事项

在实现过程中，以下事情**一律不做**：

1. **不自动执行命令**——任何情况下，用户没有明确输入 `y` 确认，命令不执行
2. **不修改用户的 shell 配置文件**（`.bashrc`、`.zshrc` 等），除非用户明确要求且二次确认
3. **不在后台启动常驻进程**
4. **不联网下载任何额外依赖**（安装时通过 pip 的正常依赖除外）
5. **不硬编码任何 API Key**，哪怕是测试用途
6. **不把用户命令数据发送到除用户配置的 API endpoint 之外的任何地方**
7. **不忽略 `SafetyBlockedError`**——拦截后必须向用户展示原因，不静默跳过

---

## 开发优先级

原始实现顺序如下，每步可独立运行：

1. **最小可用版本**：`config.py` + `llm.py` + `cli.py`（单次模式，无安全检查，无历史）
2. **安全层**：加入 `safety.py` 和拦截流程
3. **环境感知**：加入 `context.py`，让命令更准确
4. **交互 UI**：用 `rich` 美化输出，加入三选项确认
5. **历史与 REPL**：`history.py` + `ai-sh` 交互模式
6. **管道输入**：支持 `cat file | ai "..."`
7. **打包发布**：完善 `pyproject.toml`，测试 `pip install`

当前用户要求完整交付 v0.1，因此可以在保持模块边界和测试覆盖的前提下完成全部步骤。

---

## 给 AI 助手的特别提示

- 遇到需要选择「用哪个库」的情况，优先参考上方技术栈表，不要引入新依赖
- Python 依赖管理、运行命令和构建发布优先使用 `uv`，例如 `uv sync`、`uv run pytest tests/`、`uv build`
- 每次修改 `safety.py` 后必须同步更新 `tests/test_safety.py`
- 生成 prompt 字符串时，放在 `llm.py` 的模块级常量里，不要内联在函数调用中
- 如果某个需求在 PRD 和 AGENT.md 中有冲突，以 AGENT.md 为准（因为 AGENT.md 包含更晚的技术决策）
- 不要「顺手」加功能，严格以 PRD 的 v0.1 范围为边界
