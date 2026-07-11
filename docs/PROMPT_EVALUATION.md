# 命令生成 Prompt 评测

## 目标

让模型生成的命令符合 Shell 用户的执行直觉，而不只是语法可运行：

- 当前目录使用 `.`，cwd 内目标优先使用相对路径。
- 保持对象类型、直接或递归范围、排序方向和结果数量。
- 修改 Shell buffer 时只改变用户要求的部分。
- 排名和排序作用于完整结果集，避免 `find -exec ... {} +` 的批内排序错误。
- 正确处理隐藏目录、空格路径、显式绝对路径和 `~`。
- 只读、删除和设备操作使用正确的风险等级。

## 方法

评测使用用户配置的 `deepseek-ai/DeepSeek-V4-Flash`，固定 Linux 环境上下文和温度。`scripts/evaluate_prompt.py` 包含 18 个案例、80 条检查，覆盖：

1. 当前目录直接文件和目录计数。
2. 单个最大文件与十个最大 Python 文件。
3. Git 状态、端口查询和 Zsh 隐藏文件。
4. 显式 `/var/log`、`~/Downloads` 和含空格路径。
5. 直接层级、递归搜索、排除目录和最近修改时间。
6. 两种已有 Shell buffer 修改。
7. 模糊删除请求和格式化设备的风险判断。

在线 API 的连接超时不计作 prompt 语义失败；相同 prompt 和案例以较低并发重试。正则检查用于提供一致量尺，最终命令还要人工检查 Shell 语义，避免把有效的等价写法误判，或遗漏批内排序一类问题。

## 候选对比

| 版本 | 自动检查 | 人工复核 | 结论 |
|---|---:|---:|---|
| 原始基线 | 75/80 | 75/80 | 相对路径表现尚可，但目录计数会包含 `.`，部分对象类型不精确。 |
| 精简规则 | 74/80 | 74/80 | 规则过于抽象，模型仍忽略 `-mindepth`，并出现批内排序。 |
| 结构化规则 | 75/80 | 74/80 | 更长但没有更稳定；自动检查漏掉一条 `find -exec ls` 的全局排序错误。 |
| 迭代规则 | 77/80 | 77/80 | 原始两个问题和 buffer 保真均修复，只剩 `*/` 漏隐藏目录。 |

最终生产版在迭代规则上加入两条由失败案例驱动的正向形态：

- 直接子目录排名使用 `find . -mindepth 1 -maxdepth 1 -type d ...`。
- 修改时间排序使用 `find ... -printf '%T@ %p\n' | sort -rn`。

最终 18 个案例在成功响应与超时重试的合并结果中通过 80/80 条检查。此前不稳定的直接子目录案例复测为 6/6；buffer 全局排序连续复测两次均为 6/6。在线模型仍有随机性，因此这些结果表示 prompt 显著提高约束遵循率，不表示模型输出可以绕过本地安全检查或用户确认。

## 运行

完整对比：

```bash
.venv/bin/python scripts/evaluate_prompt.py --max-workers 4 --output /tmp/prompt-eval.json
```

只测试生产 prompt 的单个案例：

```bash
.venv/bin/python scripts/evaluate_prompt.py \
  --prompt production \
  --case direct-child-counts \
  --output /tmp/prompt-eval.json
```

评测会调用真实 API，不属于常规单元测试或 CI。
