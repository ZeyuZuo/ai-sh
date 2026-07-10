# ai-sh Shell 原生交互改造方案

**状态：** 已确认，待实施  
**目标版本：** v0.2  
**决策日期：** 2026-07-11  
**替代范围：** v0.1 的自动执行、三选项确认、默认 REPL 和管道分析交互

---

## 1. 决策摘要

ai-sh 从“生成并代替用户执行命令的 CLI”调整为“嵌入当前 Shell 的命令输入助手”。

核心交互是：用户在正常的 bash、zsh 或 fish 提示符中按快捷键，输入自然语言，ai-sh 将建议命令写入当前 Shell 的输入缓冲区。ai-sh 不执行命令，用户可以继续使用原生的光标移动、补全和编辑能力，最终由用户按 Enter 交给当前 Shell 执行。

产品边界调整为：

- ai-sh 负责理解意图、生成命令、解释风险和修改当前命令。
- Shell 负责编辑、补全、历史、作业控制、TTY 交互和命令执行。
- 任何 AI 生成的命令都不自动执行。
- 命令生成与自然语言问答分开，不再用同一个响应结构勉强承载两种任务。

一句话定位：

> 在你的命令行里，用自然语言补全下一条命令。

---

## 2. 改造原因

v0.1 已经完成“自然语言 -> 命令 -> 风险判断 -> 执行”的完整链路，但产品交互存在以下结构性问题。

### 2.1 执行权不符合用户预期

`safe` 命令生成后自动执行。用户没有机会检查模型是否误解了目录、范围或参数，风险完全依赖模型分类是否准确。

### 2.2 重复实现 Shell 已有能力

`[y]` 执行、`[e]` 编辑、`[n]` 取消和数字选择备选命令，本质上是在重复实现 Shell 已有的行编辑、命令历史和光标操作。用户需要学习一套只在 ai-sh 内有效的交互。

### 2.3 REPL 形成“终端里的另一个终端”

默认启动 ai-sh REPL 后，用户容易混淆当前输入是在真实 Shell 还是 ai-sh 会话中。退出、命令历史、快捷键和执行上下文也因此出现两套规则。

### 2.4 子进程执行破坏 Shell 语义

由 Python 子进程执行命令会造成：

- `cd`、`export`、alias 等操作无法改变当前 Shell 状态。
- `vim`、`ssh`、`top`、`less`、`sudo` 等交互命令无法自然继承当前 TTY。
- 作业控制、信号和 Shell 函数行为与用户直接执行不同。
- 捕获大量 stdout/stderr 会增加内存和超时处理复杂度。

### 2.5 命令生成与内容分析语义冲突

`git diff | ai "总结改动"` 需要返回自然语言答案，而不是 Shell 命令。v0.1 的模型响应要求必须返回命令或澄清问题，无法准确表达纯文本答案。

---

## 3. 产品目标

### 3.1 主要目标

- 用户始终停留在自己熟悉的 Shell 提示符中。
- 从自然语言请求到“可编辑命令”只需要一次快捷键和一次输入。
- AI 永不自动执行命令，Enter 是唯一正常执行入口。
- 当前命令可以继续用自然语言修改，不需要进入独立 REPL。
- `cd`、`export` 和交互式程序保持原生 Shell 行为。
- 风险提示清晰，但不为普通命令增加额外确认菜单。
- 管道内容分析返回自然语言答案，命令生成返回命令。

### 3.2 非目标

- 不接管 Shell 的命令执行、补全、历史或作业控制。
- 不生成多步骤自动化工作流。
- 不自动修改 `.zshrc`、`.bashrc` 或 fish 配置。
- 不通过 `eval` 自动执行模型返回内容。
- 不在 v0.2 引入后台常驻服务。
- 不保留备选命令编号菜单；用户通过自然语言继续修改当前命令。

---

## 4. 目标交互逻辑

### 4.1 首次生成命令

用户在正常 Shell 中按 `Ctrl+G`：

```text
$ <Ctrl+G>
想做什么：找出 src 下最近一天修改的 Python 文件
```

ai-sh 返回一行说明，并将命令放入当前 Shell 输入缓冲区：

```text
safe · 查找 src 下最近 24 小时修改的 Python 文件

$ find src -type f -name '*.py' -mtime -1
```

此时命令尚未执行。用户可以：

- 按 Enter，由当前 Shell 执行。
- 使用原生快捷键和光标继续编辑。
- 命令插入后，Ctrl+C、撤销和清空继续遵循当前 Shell 的原生行为。
- 再按 Ctrl+G，用自然语言修改当前命令。

### 4.2 修改当前命令

当输入缓冲区已有命令时，`Ctrl+G` 自动进入修改模式：

```text
$ find src -type f -name '*.py' -mtime -1 <Ctrl+G>
怎么修改：按修改时间倒序排列
```

返回后替换输入缓冲区：

```text
$ find src -type f -name '*.py' -mtime -1 -printf '%T@ %p\n' | sort -nr
```

发送给模型的上下文包括原始命令、修改请求、cwd、Shell、OS 和可用工具。原始命令本身取代 v0.1 中的备选命令菜单和大部分 REPL 追问。

### 4.3 需要澄清

如果缺少必要范围或路径，ai-sh 不修改当前缓冲区，而是在同一次 Widget 交互内提出澄清问题：

```text
需要澄清：要删除哪个目录？
回答：./build
```

澄清完成后再次生成命令。用户取消澄清时恢复原始缓冲区。

### 4.4 风险处理

| 风险结果 | Widget 行为 | 是否执行 |
|---|---|---|
| `safe` | 插入命令，显示简短说明 | 否 |
| `caution` | 插入命令，显示黄色风险原因 | 否 |
| `danger` | 不插入，显示拒绝原因并恢复原缓冲区 | 否 |
| 本地硬拦截 | 不插入，显示本地拦截原因并恢复原缓冲区 | 否 |

用户对 `safe` 或 `caution` 命令按 Enter，就是唯一一次明确执行确认。`danger` 和本地硬拦截结果不能通过 Widget 放入命令行。

本地硬拦截在 v0.2 中始终启用，不向普通配置暴露关闭选项。

### 4.5 API 失败和取消

发生网络错误、限流、响应解析失败，或用户在 Widget 请求和澄清过程中按 Ctrl+C 时：

- 不改变当前输入缓冲区。
- 在提示符上方显示一条可操作的错误信息。
- 不写入命令历史。
- 不输出 traceback，除非显式启用 debug。

### 4.6 管道分析和问答

内容分析使用独立的问答模式：

```bash
git diff | ai --ask "总结这次改动"
cat error.log | ai --ask "分析报错原因和修复方向"
```

问答模式只输出自然语言答案，不生成或执行命令。stdin 必须设置大小上限，并在读取过程中限制数据量，而不是读取完整内容后再截断。

### 4.7 无 Shell 集成时的降级方式

用户仍可直接运行：

```bash
ai "找出当前目录下超过 100MB 的文件"
```

该命令以适合人阅读的形式打印一条建议命令、解释和风险，但永不执行。机器调用必须使用显式的 JSON 格式选项，避免解析 Rich 输出。

---

## 5. 命令与配置结构

目标命令结构：

```text
ai <request>                 生成人类可读的命令建议，不执行
ai --ask <question>          回答问题，可读取 stdin
ai --json <request>          输出稳定的机器可读结果

ai-sh config                 配置 API
ai-sh config --show          查看脱敏后的配置状态
ai-sh init zsh               输出 zsh Widget 初始化脚本
ai-sh init bash              输出 bash Widget 初始化脚本
ai-sh init fish              输出 fish Widget 初始化脚本
ai-sh suggest                Shell Widget 使用的内部稳定接口
ai-sh repl                   v0.2 暂时保留的旧 REPL
```

安装 Shell 集成时只输出脚本，由用户明确写入配置：

```bash
eval "$(ai-sh init zsh)"
```

ai-sh 不主动修改任何 Shell 配置文件。

以下 v0.1 配置将被废弃：

- `behavior.default_confirm`：不再需要，ai-sh 不执行命令。
- `safety.hard_block_enabled`：不再允许在普通配置中关闭。

读取旧配置时保持兼容并忽略废弃项，首次展示配置时给出一次迁移提示。

---

## 6. Shell 集成设计

### 6.1 总体流程

```text
用户按 Ctrl+G
    -> Widget 保存当前 buffer 和 cursor
    -> Widget 收集自然语言请求
    -> 调用 ai-sh suggest 的机器接口
    -> Python 收集环境并调用模型
    -> Python 解析结果并执行本地安全检查
    -> Widget 根据结构化结果替换或恢复 buffer
    -> 返回原生 Shell 编辑状态
```

Widget 与 Python 后端之间使用稳定的结构化协议。请求和当前 buffer 通过 stdin 传递，避免 Shell 字符串插值和将可能包含敏感信息的命令放入进程参数。后端 stdout 只输出协议数据，诊断信息写入 stderr。

### 6.2 bash

Shell 集成 MVP 优先实现 bash，因为项目主要运行在 Linux，bash 是必须覆盖的首要环境：

- 通过 `bind -x` 注册快捷键。
- 使用 `READLINE_LINE` 和 `READLINE_POINT` 操作当前输入。
- 保证取消和失败时恢复原始内容及光标位置。
- 默认绑定 `Ctrl+G`，允许用户覆盖。

### 6.3 zsh

zsh 与 bash 同属 Shell 集成 MVP，使用 ZLE：

- `BUFFER` 读取和替换当前命令。
- `CURSOR` 控制替换后的光标位置。
- `zle -M` 或提示符上方输出状态和风险。
- `zle reset-prompt` 恢复正常提示符。
- 默认绑定 `Ctrl+G`，允许用户覆盖。

### 6.4 fish

bash 和 zsh MVP 稳定后的兼容阶段支持 fish：

- 使用 `bind` 注册快捷键。
- 使用 `commandline` 读取和替换缓冲区。
- 保持与 zsh、bash 一致的风险和取消语义。

---

## 7. 后端结果协议

模型层和 Shell Widget 不直接共享厂商响应。Python 后端将结果规范化为版本化协议：

Widget 调用 `ai-sh suggest` 时，通过 stdin 发送一个 UTF-8 JSON 对象：

```json
{
  "protocol_version": 1,
  "request": "按修改时间倒序排列",
  "buffer": "find src -type f -name '*.py' -mtime -1"
}
```

协议输入限制：

- stdin JSON 总量不超过 128 KiB。
- `request` 必须是非空字符串，不超过 4096 字符。
- `buffer` 必须是字符串，不超过 32768 字符。
- `ai --json` 使用相同的 request 限制；其管道上下文最多读取 65536 字符并明确标记截断。
- 未知字段由当前协议版本忽略，便于向后兼容增加可选字段。

```json
{
  "protocol_version": 1,
  "kind": "command",
  "command": "find src -type f -name '*.py' -mtime -1",
  "answer": "",
  "explanation": "查找 src 下最近 24 小时修改的 Python 文件。",
  "risk_level": "safe",
  "risk_reason": "",
  "clarification": "",
  "error": ""
}
```

`kind` 的合法值：

- `command`：返回可插入输入缓冲区的命令。
- `answer`：问答模式返回自然语言答案。
- `clarification`：需要用户补充信息。
- `blocked`：AI danger 或本地安全规则拒绝。
- `error`：配置、网络、解析或内部错误。

协议要求：

- stdout 只能包含一个 JSON 对象。
- API key 和完整异常对象不得进入协议。
- 未知 `protocol_version` 必须拒绝处理，不能猜测。
- `command` 必须经过本地安全层后才能标记为可插入。
- Widget 不使用 `eval` 解释 JSON 中的命令。
- v0.2 不再提供 `alternatives`；用户通过修改模式获得新命令。

稳定退出码：

| 退出码 | 含义 |
|---:|---|
| `0` | 成功返回 command 或 answer |
| `2` | 请求 JSON、版本、类型或长度无效 |
| `20` | API 配置无效或缺失 |
| `21` | AI API 连接、限流、响应或解析失败 |
| `30` | 需要用户澄清 |
| `31` | AI danger 或本地安全规则拦截 |
| `70` | 未分类的内部错误 |
| `130` | 用户中断请求 |

---

## 8. 历史与隐私

- Shell 的命令执行历史继续由 Shell 自己管理。
- ai-sh 只记录生成请求、建议命令、风险结果和是否被插入，不记录“已执行”，因为 ai-sh 不再知道用户是否按了 Enter。
- 问答 stdin 默认不持久化。
- REPL 输入历史文件和 ai-sh 历史文件权限必须为 `600`。
- 当前 buffer 只发送到用户配置的 API endpoint。
- API key 不得出现在 argv、日志、历史、协议或错误输出中。
- 后续如需遥测，必须单独设计并默认关闭；v0.2 不加入遥测。

---

## 9. 迁移策略

v0.2 是一次有意的行为变更，优先保证不会意外执行命令。

### 9.1 保留

- 现有 API 配置文件路径和 API key 读取优先级。
- 环境上下文收集。
- LLM JSON 容错和 OpenAI 兼容接口。
- 本地安全规则。
- Rich 人类可读输出。

### 9.2 调整

- `ai <request>` 从“生成并可能执行”改为“只生成和展示”。
- 默认 `ai-sh` 不再直接进入 REPL，而是展示 Shell 集成引导。
- 旧 REPL 暂时移动到 `ai-sh repl`，标记为 legacy。
- 命令执行模块只供 legacy REPL 使用，并计划在后续版本删除。
- 备选命令改为基于当前 buffer 的自然语言修改。

### 9.3 删除或废弃

- 删除 safe 自动执行。
- 删除 `[y/e/n]` 确认菜单。
- 废弃 `default_confirm`。
- 废弃可关闭的本地硬拦截配置。
- v0.3 删除 legacy REPL 和内部命令执行器，前提是 v0.2 Shell 集成已稳定。

---

## 10. 开发步骤

### 阶段 1：重构结果模型与执行边界

目标：先建立“AI 永不自动执行”的新底线，不依赖 Shell Widget 是否完成。

任务：

- 将 LLM 结果扩展为 `command`、`answer`、`clarification`、`blocked` 和 `error`。
- 将本地安全判断合并进统一结果规范化流程。
- 修改 `ai <request>`，只展示命令，不调用 executor。
- 移除默认流程中的确认菜单、编辑器和备选命令选择。
- 为旧 REPL 建立独立 legacy 路径，避免新旧逻辑混用。
- 修正命令超时时 stdout/stderr 可能为 bytes 的现有缺陷，保证 legacy 路径稳定。

验收：

- 所有 `ai` 调用都不会触发 `subprocess.run`。
- safe、caution、danger 和本地拦截分别有回归测试。
- 现有配置、解析和安全测试继续通过。

### 阶段 2：建立稳定的机器接口

目标：提供 Shell Widget 可以依赖的无 UI 后端。

任务：

- 实现 `ai-sh suggest`。
- 定义 `protocol_version=1` 的请求和响应格式。
- 分离 stdout 协议输出与 stderr 诊断信息。
- 使用 stdin 传递请求和当前 buffer。
- 定义配置错误、API 错误、澄清和拦截的稳定退出码。
- 对超长 request、buffer 和 stdin 设置读取上限。

验收：

- 特殊字符、引号、管道、换行和 Unicode 命令可以无损往返。
- 任意错误路径都只输出合法 JSON，不泄露 API key。
- 协议测试使用固定样例，避免后续 Widget 与后端静默不兼容。

### 阶段 3：实现 bash 与 zsh Widget MVP

目标：在 Linux 常用的 bash 和 zsh 中验证核心产品形态，而不是继续扩展旧 CLI UI。实现顺序先 bash、后 zsh，但两者都完成才算本阶段通过。

任务：

- 实现 `ai-sh init bash`，通过 Readline buffer 完成首个可用版本。
- 实现 `ai-sh init zsh`，复用相同后端协议和交互语义。
- 注册可配置快捷键，默认 `Ctrl+G`。
- 分别保存和恢复 bash 的 `READLINE_LINE`、`READLINE_POINT` 与 zsh 的 `BUFFER`、`CURSOR`。
- 支持空 buffer 生成和非空 buffer 修改。
- 支持 clarification、caution、blocked、error 和 Ctrl+C。
- 更新 README 安装和演示流程。

验收：

- 建议命令只进入输入缓冲区，不执行。
- 取消、API 失败和 danger 都完整恢复原 buffer 和 cursor。
- `cd`、`export`、`vim`、`ssh` 等命令在用户按 Enter 后分别由当前 bash 或 zsh 原生执行。
- bash 和 zsh 的生成、修改、风险与取消行为保持一致。
- Widget 不使用 `eval` 执行模型生成的命令。

### 阶段 4：拆分问答模式

目标：让管道分析场景符合用户预期。

任务：

- 实现 `ai --ask`。
- 为问答使用独立 system prompt 和结果解析。
- 对 stdin 做流式限长读取和截断提示。
- 问答模式不进入命令安全或执行流程。
- 增加 diff、日志和普通问题的测试样例。

验收：

- `git diff | ai --ask "总结改动"` 返回文本答案，不生成命令。
- 问答失败时返回非零退出码和用户可理解的错误。
- stdin 内容不写入持久化历史。

### 阶段 5：支持 fish 并加固跨 Shell 兼容性

目标：在 bash 和 zsh MVP 稳定后补齐 fish，并覆盖 PRD 声明支持的三个 Shell。

任务：

- 实现 `ai-sh init fish` 和 fish commandline 替换。
- 统一三种 Shell 的提示、风险、取消和错误语义。
- 增加 Shell 初始化脚本快照测试和可用环境下的集成测试。

验收：

- 同一请求在三个 Shell 中产生一致的后端结果。
- 每个 Shell 都能在失败时恢复 buffer 和 cursor。
- 初始化脚本可重复加载，不产生重复绑定或错误。

### 阶段 6：工程化与发布

目标：把功能可用提升到可稳定发布。

任务：

- 建立 CI，运行 Python 3.10 及当前稳定版的 pytest、Ruff 和构建。
- 为 OpenAI 客户端增加 mock 测试，覆盖超时、限流和 JSON mode 降级。
- 引入 mypy 并先覆盖结果协议、配置和 Shell 后端边界。
- 增加 wheel 安装后的命令入口测试。
- 更新 PRD、README、迁移说明和 changelog。
- 发布 v0.2 tag 和构建产物。

验收：

- CI 全绿后才能发布。
- 从全新环境安装 wheel 后，配置、建议、问答和 Shell init 均可运行。
- 文档不再描述 safe 自动执行或默认 REPL 为主要交互。

---

## 11. 预计文件改动

| 文件或模块 | 主要改动 |
|---|---|
| `src/ai_sh/llm.py` | 区分命令与问答结果，输出统一协议模型 |
| `src/ai_sh/cli.py` | 改为只建议；增加 suggest、ask、init、legacy repl 路由 |
| `src/ai_sh/safety.py` | 对规范化 command 做最终插入前检查 |
| `src/ai_sh/ui.py` | 保留人类可读展示，删除默认确认和编辑流程 |
| `src/ai_sh/executor.py` | 仅供 legacy REPL，v0.3 删除 |
| `src/ai_sh/history.py` | 记录建议而非推断执行状态，收紧文件权限 |
| `src/ai_sh/shell/` | 新增 zsh、bash、fish 初始化脚本生成器 |
| `tests/` | 增加协议、无执行保证、Widget 和 API mock 测试 |
| `README.md` | 以快捷键填充命令作为第一使用路径 |
| `docs/PRD.md` | 同步 v0.2 产品目标和范围 |

---

## 12. 完成定义

v0.2 只有同时满足以下条件才视为完成：

- 默认交互中不存在任何 AI 自动执行路径。
- zsh、bash、fish 至少能完成生成、修改、取消和风险提示。
- 用户按 Enter 后，命令由当前 Shell 原生执行。
- `cd`、`export` 和交互式程序行为与手写命令一致。
- danger 和本地硬拦截不会修改当前输入缓冲区。
- 管道分析通过 `ai --ask` 返回自然语言答案。
- 旧配置可以无损读取并给出明确迁移提示。
- CI 覆盖单元测试、lint 和包构建。
- README、PRD 和实际行为一致。

---

## 13. 实施优先级

最高优先级是阶段 1 至阶段 3：先取消自动执行，再完成机器协议，最后用 bash 和 zsh Widget 验证新产品形态。考虑项目以 Linux 为主要平台，阶段 3 内部先实现 bash，但不能以缺少 zsh 支持的状态结束该阶段。

在 bash 和 zsh MVP 完成人工可用性验证前，不继续投入复杂 REPL、备选命令菜单或执行器功能。MVP 验证通过后，再扩展问答、fish 和发布工程化。
