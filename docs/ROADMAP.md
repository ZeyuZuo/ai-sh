# tmksh 产品设计与开发计划

**文档状态：** 当前实施依据
**更新日期：** 2026-07-13
**当前版本：** v0.2

## 1. tmksh 是什么

tmksh 是当前 Shell 里的 AI 命令助手。

用户不需要进入另一个 Shell，也不需要记住多套入口。无论当前命令行是否为空、上一条命令是否失败，统一操作都是：

```text
按 Ctrl+G
    -> 进入 tmksh> 提示符
    -> 输入自然语言或特殊指令
    -> tmksh 返回结果
    -> 回到原 Shell
```

tmksh 可以生成或修改命令，但永远不执行命令。建议命令只会进入当前 Shell 的输入缓冲区，最终由用户检查、编辑并按 Enter 执行。

## 2. 不可改变的产品规则

- `Ctrl+G` 始终进入同一个 `tmksh>` 提示符。
- AI 生成的命令只展示或写入 Shell buffer，不由 tmksh 执行。
- `danger` 和本地硬拦截结果不能进入 buffer。
- 取消、空输入、API 失败和协议错误必须恢复原 buffer 与 cursor。
- 解释、检查和问答只显示文本，不修改 buffer。
- tmksh 不自动修改 `.bashrc`、`.zshrc` 或 Fish 配置。
- tmksh 不持续监听或上传终端输出。
- Bash、Zsh 和 Fish 的功能与安全语义必须一致。

## 3. 用户交互设计

### 3.1 统一入口

命令行为空时：

```text
$ <Ctrl+G>
tmksh> 找出当前目录最大的十个文件

safe · 查找并按大小排序文件
$ find . -type f -printf '%s %p\n' | sort -nr | head -n 10
```

命令行非空时，tmksh 在提示符前显示当前处理对象，但提示符仍然是 `tmksh>`：

```text
$ find src -type f <Ctrl+G>
current · find src -type f
tmksh> 只保留 Python 文件并按修改时间倒序排列

$ find src -type f -name '*.py' -printf '%T@ %p\n' | sort -nr
```

### 3.2 普通自然语言

普通自然语言遵循确定的默认规则：

| 当前状态 | 默认行为 |
|---|---|
| buffer 为空 | 生成一条新命令 |
| buffer 非空 | 根据用户要求修改当前命令 |

特殊指令用于覆盖默认行为。例如 buffer 非空但用户想忽略它并生成另一条命令时，使用 `/new`。

### 3.3 特殊指令语法

第一版特殊指令固定为：

```text
/fix [补充信息]
/explain [关注点]
/check [检查重点]
/new <任务>
/ask <问题>
/help
```

解析规则：

- 指令名由 tmksh 本地解析，不交给模型猜测。
- 指令名后的全部内容都是自然语言参数，不设计复杂 flags。
- 指令不区分大小写，但文档和输出统一使用小写。
- 未知指令不调用模型，直接显示 `/help` 和相近指令。
- 暂不增加 `/f`、`/e` 等短别名，避免形成难以维护的隐藏语法。

### 3.4 指令行为总表

| 输入 | 默认目标 | 返回类型 | 是否修改 buffer |
|---|---|---|---|
| 普通自然语言，空 buffer | 用户描述的新任务 | 命令 | 是 |
| 普通自然语言，非空 buffer | 当前 buffer | 命令 | 是 |
| `/fix` | 最近一条退出码非零的命令 | 修复命令 | 是 |
| `/explain` | 当前 buffer，否则上一条命令 | 文本解释 | 否 |
| `/check` | 当前 buffer，否则上一条命令 | 检查报告 | 否 |
| `/new` | 指令后的新任务 | 命令 | 是 |
| `/ask` | 指令后的问题 | 文本回答 | 否 |
| `/help` | 本地帮助 | 文本帮助 | 否 |

## 4. 核心使用流程

### 4.1 生成新命令

```text
$ <Ctrl+G>
tmksh> 查找占用 8080 端口的进程

$ lsof -i :8080
```

生成结果必须经过模型风险分类和本地安全检查后才能进入 buffer。

### 4.2 修改当前命令

```text
$ git log <Ctrl+G>
current · git log
tmksh> 只显示最近五条，并包含文件改动统计

$ git log -5 --stat
```

模型必须保留用户没有要求改变的路径、过滤条件和参数。

### 4.3 修复上一条失败命令

```text
$ uv run pytest
ModuleNotFoundError: No module named 'yaml'

$ <Ctrl+G>
tmksh> /fix

$ uv add pyyaml
```

`/fix` 始终指向最近一条退出码非零的命令，不根据当前 buffer 猜测目标。

用户可以在同一行补充错误或约束：

```text
tmksh> /fix 报错是 No module named yaml
tmksh> /fix 不要使用 pip，这个项目使用 uv
```

第一版自动提供给模型的信息只有：

- 失败命令。
- 退出码。
- 执行时的 cwd。
- Shell 和操作系统。
- 用户在 `/fix` 后提供的补充信息。

第一版不自动捕获完整 stdout/stderr。Shell hook 无法在不包装命令或持续记录终端的情况下可靠取得已经输出的内容。未来如要增加自动输出捕获，必须单独设计、默认关闭并明确隐私影响。

如果没有可用的失败命令：

```text
tmksh> /fix
没有找到最近失败的命令。请先运行命令，或直接描述需要修复的问题。
```

原 buffer 保持不变。

### 4.4 解释命令

```text
$ find . -type f -print0 | xargs -0 du -h <Ctrl+G>
current · find . -type f -print0 | xargs -0 du -h
tmksh> /explain 为什么需要 print0 和 -0
```

解释显示在当前提示符上方。原 buffer 和 cursor 必须保持不变。

目标选择顺序：

1. 当前 buffer。
2. 上一条 Shell 命令。
3. 都不存在时提示用户先输入命令。

### 4.5 检查命令

```text
$ rm -rf build/* <Ctrl+G>
current · rm -rf build/*
tmksh> /check

风险      caution
正确性    不会匹配 build 下的隐藏文件
兼容性    Bash 和 Zsh 可用
建议      如需修改，请再次按 Ctrl+G 描述期望结果
```

`/check` 固定检查：

- 正确性：命令是否实现看起来想完成的任务。
- 风险：是否删除、覆盖、修改权限或执行远程内容。
- 兼容性：当前 OS、Shell 和可用工具是否支持。

`/check` 只报告，不自动应用修正。用户决定修改时，再按 `Ctrl+G` 用自然语言描述修改要求。

### 4.6 忽略当前命令重新生成

```text
$ git status <Ctrl+G>
current · git status
tmksh> /new 查找监听 8080 端口的进程

$ lsof -i :8080
```

`/new` 不把当前 buffer 作为修改目标。失败或取消时仍恢复原 buffer。

### 4.7 普通问答

```text
$ git status <Ctrl+G>
current · git status
tmksh> /ask git merge 和 rebase 有什么区别
```

答案显示在提示符上方，原 buffer 保持不变。该路径复用现有 `tmksh ask` 的纯文本提示词，不进入命令安全或建议历史。

### 4.8 帮助

```text
tmksh> /help

/fix [补充信息]       修复最近失败的命令
/explain [关注点]     解释当前或上一条命令
/check [检查重点]     检查正确性、风险和兼容性
/new <任务>           忽略当前 buffer 生成新命令
/ask <问题>           回答问题，不修改 buffer
/help                 显示本帮助
```

帮助由本地生成，不调用 API。

## 5. 结果和异常处理

| 结果 | 用户看到的行为 | Buffer 行为 |
|---|---|---|
| `safe` 命令 | 显示说明 | 写入新命令 |
| `caution` 命令 | 显示风险原因 | 写入新命令 |
| `danger` | 显示拒绝原因 | 恢复原内容 |
| 本地硬拦截 | 显示本地规则原因 | 恢复原内容 |
| 文本回答 | 显示回答 | 恢复原内容和 cursor |
| 需要澄清 | 继续显示 `tmksh>` 接收补充 | 澄清完成前不修改 |
| 空输入或 Ctrl+C | 不请求 API | 恢复原内容和 cursor |
| API 或协议错误 | 显示可操作错误 | 恢复原内容和 cursor |

同一次调用最多澄清三轮。超过限制后停止请求并恢复原 buffer。

## 6. 多套 Config 的用户设计

多模型和多环境继续使用现有 `config` 命令，不新增顶层 `profile` 命令。

目标命令：

```bash
tmksh config                 # 编辑当前配置
tmksh config list            # 列出所有配置
tmksh config add work        # 新建 work 配置
tmksh config use work        # 设置默认配置
tmksh config show            # 脱敏显示当前配置
tmksh config show local      # 脱敏显示指定配置
tmksh config remove local    # 删除非当前配置
```

`config list` 示例：

```text
NAME       MODEL                              ENDPOINT                    ACTIVE
personal   deepseek-ai/DeepSeek-V4-Flash      api.siliconflow.cn         *
work       company/deepseek-v4                llm.example.com
local      qwen3                              127.0.0.1:11434
```

规则：

- API key 永远不在 `list` 或 `show` 中显示。
- 当前配置不能直接删除，必须先切换到其他配置。
- 配置名只允许字母、数字、`-` 和 `_`。
- 环境变量 `TMKSH_CONFIG=work` 可以只为当前命令临时选择配置，不改变默认值。
- 旧版单配置文件自动迁移为 `default` 配置，不丢失 endpoint、model 或 API key。

## 7. 后续能力的含义

### 7.1 上下文诊断

上下文诊断用于回答“tmksh 到底把什么发给了模型”和“为什么生成了错误平台的命令”。它不是日常交互入口。

计划命令：

```bash
tmksh context
```

只显示来源和摘要：

```text
cwd             /home/user/project
shell           bash
os              Ubuntu 24.04
tools           git, rg, uv
current_buffer  42 chars
stdin           not included
config          personal
model           deepseek-ai/DeepSeek-V4-Flash
endpoint        api.siliconflow.cn
```

不显示 API key、完整凭据或默认打印完整 stdin。

### 7.2 用户安全策略

用户安全策略是在不可关闭的内置硬拦截之上，增加个人或组织规则。例如禁止生成生产环境删除命令，或把强制推送提升为 `caution`。

用户策略只能收紧限制，不能关闭或覆盖内置安全规则。该能力主要面向运维和企业环境，不是近期核心交互。

### 7.3 项目上下文文件

`TMKSH.md` 用于描述项目工具和约束，例如测试命令、禁止修改的目录或部署环境。该能力放在最后实现，前面的统一交互、失败修复和配置管理稳定后再设计其查找边界、大小限制和 prompt injection 防护。

## 8. 重新设计后的开发步骤

### 阶段 0：v0.2 发布基础

**状态：已完成。**

- Bash、Zsh、Fish Widget。
- 稳定机器协议和本地安全归一化。
- CI、Ruff、首批 strict mypy、构建和 wheel smoke test。
- 独立 `ask` 模式、错误脱敏和发布文档。

### 阶段 1：`/fix` 和失败命令状态

**状态：已完成（2026-07-13）。**

开发顺序：

1. 定义本地特殊指令解析结果，不把 `/fix` 当普通 prompt。
2. 扩展 Bash、Zsh、Fish hook，在本地保存上一条命令、退出码和 cwd。
3. 扩展机器请求，携带可选的失败命令上下文。
4. 增加独立 fix prompt，输出仍使用命令结果和安全归一化。
5. 实现 `/fix [补充信息]`，成功时替换 buffer，其他路径完整恢复。
6. 为三种 Shell 增加成功、无失败记录、取消、API 错误和危险结果测试。

验收标准：

- 用户只需 `Ctrl+G` 后输入 `/fix` 即可处理最近失败命令。
- `/fix` 不依赖持续监听终端输出。
- 不记录或上传完整 stdout/stderr。
- 修复命令不会自动执行，并经过与普通建议相同的本地安全检查。

### 阶段 2：统一特殊指令和文本操作

**状态：已完成（2026-07-13）。**

开发顺序：

1. 完成 `/help` 和未知指令的纯本地处理。
2. 实现 `/explain`，目标选择为当前 buffer、上一条命令。
3. 实现 `/check` 的正确性、风险、兼容性结构化输出。
4. 实现 `/new`，明确忽略当前 buffer。
5. 实现 `/ask`，复用现有纯文本问答路径。
6. 统一 Widget 对 command、answer、clarification、blocked 和 error 的处理。
7. 保证自然语言默认规则仍是空 buffer 生成、非空 buffer 修改。

验收标准：

- 所有特殊指令都从同一个 `tmksh>` 输入。
- `/explain`、`/check`、`/ask` 在任何结果下都不修改 buffer。
- `/new` 不把当前 buffer 发送为修改目标。
- 未知指令和 `/help` 不调用 API。

### 阶段 3：多套 Config

开发顺序：

1. 设计可迁移的多配置文件结构。
2. 将现有单配置迁移为 `default`，保留原有密钥读取优先级。
3. 实现 `config list/add/use/show/remove`。
4. 支持 `TMKSH_CONFIG` 临时选择。
5. 让 Widget、CLI、`ask` 和机器协议使用同一个配置解析入口。
6. 增加配置名校验、脱敏、权限和迁移测试。

验收标准：

- 旧用户升级后无需重新输入配置。
- 切换配置不会泄露或覆盖其他配置的 API key。
- `config show/list` 只显示脱敏信息。

### 阶段 4：上下文诊断

- 实现 `tmksh context`。
- 显示上下文字段、来源、长度、截断状态和当前配置。
- 默认不显示完整命令内容、stdin 和任何密钥。
- 为调试输出增加脱敏回归测试。

### 阶段 5：可配置安全策略

- 定义用户级和可选系统级策略文件。
- 支持 `block` 和 `caution` 规则。
- 用户规则只能加强内置安全判断。
- 在三种 Shell 和 JSON 协议中保持相同结果。

### 阶段 6：`TMKSH.md` 项目上下文

这是当前路线的最后阶段。

- 从 cwd 向上查找，但不跨越 Git 仓库边界。
- 设置文件大小上限和明确截断标记。
- 将内容标记为不可信数据，防御其中的 prompt injection。
- 读取失败不能阻断普通命令建议。
- `tmksh context` 必须能显示是否加载及来源。

## 9. 明确不做

- 自动执行、后台执行或无人值守 Agent。
- 完整 PTY Shell、作业控制或 Shell 历史替代品。
- 自动记录和上传完整终端输出。
- 自动扫描并上传整个代码仓库。
- MCP、RAG、多 Agent 和 HTTP Server。
- 默认长期记忆、遥测或云端历史同步。
- 自动修改用户 Shell 配置。

## 10. 提交和测试要求

- 每个阶段拆分为可回滚提交，不把协议、Shell hook 和 UI 全塞进一个提交。
- 任何协议变化必须提供旧客户端兼容测试；无法兼容时提升 `protocol_version`。
- Shell 行为必须同时覆盖 Bash、Zsh 和 Fish。
- 所有写入 buffer 的命令必须经过本地安全检查。
- 所有不应修改 buffer 的路径必须断言原内容和 cursor 完整恢复。
- 每个阶段完成时同步 README、CHANGELOG 和本文档状态。
