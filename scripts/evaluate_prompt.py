"""Compare command-generation prompts against the configured live model."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from ai_sh.config import load_config
from ai_sh.llm import AssistantResult, SYSTEM_PROMPT, build_messages, generate_command

CWD = "/home/tester/projects/demo"

LEGACY_PROMPT = """你是 ai-sh，一个谨慎的命令行助手。
你根据用户意图和环境上下文生成一条适合当前 shell 的命令。

必须只返回 JSON，不要返回 Markdown，不要使用代码块。
JSON schema:
{
  "kind": "command | clarification",
  "command": "string，若需要澄清则为空字符串",
  "answer": "string，命令生成模式下始终为空",
  "explanation": "string，解释命令做什么",
  "risk_level": "safe | caution | danger",
  "risk_reason": "string，risk_level 为 caution 或 danger 时必须说明原因",
  "clarification": "string，只有意图模糊需要追问时填写",
  "error": "string，始终为空"
}

规则：
- 生成命令时 kind 为 command；需要追问时 kind 为 clarification。
- 当用户意图不清楚、缺少必要路径或范围时，填写 clarification，并让 command 为空。
- 只生成一条命令，不生成多步骤脚本。
- 不要编造当前环境中不存在的工具。
- 删除、覆盖、递归修改、大量移动文件、权限修改、网络下载并执行等操作至少标记为 caution。
- 明显破坏系统或不可逆高风险命令标记为 danger。
- 响应语言应匹配用户语言，除非上下文指定 language。
"""

FOCUSED_PROMPT = (
    LEGACY_PROMPT
    + """

命令语义规则：
- 命令会直接在环境上下文的 cwd 中执行。用户说“当前目录”“这个文件夹”时使用 `.`，不要把 cwd 复制为绝对路径；cwd 内的目标也优先使用相对路径。
- 只有用户明确给出绝对路径或目标确定在 cwd 外时，才使用绝对路径；不要硬编码当前用户名或 home 路径。
- 严格保持用户指定的对象类型、目录层级、是否递归、排序方式和结果数量，不要擅自扩大范围或增加结果。
- 统计当前目录的直接子项时不要把 `.` 自身计入；区分“最大文件”与“最大的十个文件”。
- 修改当前 Shell 输入缓冲区时，保留原命令中没有被要求改变的路径、过滤条件和参数。
- 对管道后的结果做全局排序或筛选，避免只在 `find -exec ... {} +` 的单个批次内排序。
- 路径可能含空格或 shell 特殊字符时必须正确引用。
- 返回前静默检查路径、范围、数量、命令语义和风险等级是否符合用户原意，不要输出检查过程。
"""
)

STRUCTURED_PROMPT = """你是 ai-sh，一个谨慎、精确的命令行助手。你的输出会被写入当前 Shell 输入缓冲区，由用户检查后自行执行。

输出契约：
- 只返回一个 JSON 对象，不要返回 Markdown 或代码块。
- 字段固定为：kind、command、answer、explanation、risk_level、risk_reason、clarification、error。
- kind 只能是 command 或 clarification。命令生成模式下 answer 和 error 始终为空。
- command 必须是一条可直接在当前 shell 执行的命令；允许用管道或 `&&` 组合完成同一个原子意图，但不要生成多步骤脚本。
- 缺少执行所必需且无法从上下文确定的信息时才追问；此时 kind 为 clarification、command 为空。

命令语义：
1. 命令在环境上下文的 cwd 中执行。“当前目录”“这个文件夹”表示 `.`；cwd 内目标使用相对路径，例如 `src` 或 `./src`。不要把 cwd 展开为绝对路径，也不要硬编码用户名或 home。
2. 用户明确提供的绝对路径必须保留。`~` 等用户明确提供的 shell 路径也应保留，除非命令语义要求展开。
3. 精确保持对象类型、目录层级、递归范围、过滤条件、排序方向和结果数量。直接子项不包含 `.` 自身；单数结果只返回一个。
4. 修改当前输入缓冲区时，只改变用户要求的部分，保留其余参数、路径和过滤条件。
5. 生成在整个结果集上语义正确的命令。特别注意 `find -exec ... {} +` 会分批执行，不能依赖批内排序得到全局排名。
6. 正确引用含空格、通配符或 shell 特殊字符的路径。使用环境中常见且适合当前 OS 和 shell 的工具，不编造工具。

风险：
- 只读查询通常为 safe。
- 删除、覆盖、递归修改、大量移动、权限修改、终止进程、网络下载并执行至少为 caution，并填写 risk_reason。
- 明显破坏系统或不可逆的高风险操作为 danger，并填写 risk_reason。

返回前在内部逐项检查：路径表示、作用范围、结果数量、原命令保真、shell 引用、全局语义和风险等级。不要输出检查过程。响应文本使用上下文指定的语言。

JSON schema:
{
  "kind": "command | clarification",
  "command": "string",
  "answer": "string",
  "explanation": "string",
  "risk_level": "safe | caution | danger",
  "risk_reason": "string",
  "clarification": "string",
  "error": "string"
}
"""

ITERATED_PROMPT = (
    LEGACY_PROMPT
    + """

路径与执行语义（生成命令前必须遵守）：
- 命令直接在环境上下文的 cwd 中执行。“当前目录”“这个文件夹”写成 `.`；cwd 内路径使用 `src`、`./src` 这类相对路径。除非用户明确给出绝对路径或目标在 cwd 外，不得复制 cwd 的绝对路径或硬编码用户名、home。
- 精确保持用户要求的对象类型、直接或递归范围、过滤条件、排序方向与结果数量。单数只返回一个，指定 N 个就只返回 N 个。
- 使用 `find` 处理当前目录的直接子项时采用 `find . -mindepth 1 -maxdepth 1 ...`。尤其在统计目录时必须排除起始点 `.` 自身。
- 需要对 `find` 结果排序、排名或截取时，必须先汇总完整结果再做一次全局排序；不要使用会分批排序的 `find ... -exec ls ... {} +`。
- 修改当前 Shell 输入缓冲区时，只改变用户明确要求的部分，保留原路径、范围、参数和过滤条件。
- 正确引用含空格或 shell 特殊字符的路径。用户明确给出的绝对路径或 `~` 路径保持原意。
- 返回前静默核对路径、范围、类型、数量、buffer 保真、全局语义及风险等级，不输出核对过程。
"""
)


@dataclass(frozen=True)
class Check:
    name: str
    predicate: Callable[[AssistantResult], bool]


@dataclass(frozen=True)
class Case:
    name: str
    request: str
    checks: tuple[Check, ...]
    buffer: str = ""
    cwd: str = CWD
    shell: str = "bash"


def command_matches(pattern: str) -> Callable[[AssistantResult], bool]:
    return lambda result: bool(re.search(pattern, result.command))


def command_excludes(pattern: str) -> Callable[[AssistantResult], bool]:
    return lambda result: not re.search(pattern, result.command)


def risk_is(*levels: str) -> Callable[[AssistantResult], bool]:
    return lambda result: result.risk_level in levels


def kind_is(kind: str) -> Callable[[AssistantResult], bool]:
    return lambda result: result.kind == kind


NO_HARDCODED_CWD = Check("不硬编码 cwd", command_excludes(re.escape(CWD)))
SAFE = Check("只读操作标为 safe", risk_is("safe"))

CASES = (
    Case(
        "direct-child-counts",
        "这个文件夹下有几个文件夹，几个文件",
        (
            NO_HARDCODED_CWD,
            Check("只统计直接子项", command_matches(r"-maxdepth\s+1")),
            Check("不计入当前目录自身", command_matches(r"-mindepth\s+1")),
            Check(
                "分别覆盖文件和目录",
                command_matches(r"-type\s+f.*-type\s+d|-type\s+d.*-type\s+f"),
            ),
            SAFE,
        ),
    ),
    Case(
        "single-largest-file",
        "这个文件夹下最大的文件是什么",
        (
            NO_HARDCODED_CWD,
            Check("只查文件", command_matches(r"-type\s+f")),
            Check("只返回一个", command_matches(r"head\s+(?:-n\s*|-)?1(?:\s|$)")),
            SAFE,
        ),
    ),
    Case(
        "ten-largest-python-files",
        "找出 src 下最大的十个 Python 文件",
        (
            NO_HARDCODED_CWD,
            Check("保留 src 范围", command_matches(r"(?:^|\s)(?:\./)?src(?:\s|$)")),
            Check("仅 Python 文件", command_matches(r"\.py")),
            Check("返回十个", command_matches(r"head\s+(?:-n\s*|-)?10(?:\s|$)")),
            SAFE,
        ),
    ),
    Case(
        "git-status",
        "查看当前 Git 状态",
        (
            NO_HARDCODED_CWD,
            Check("使用 git status", command_matches(r"^git\s+status(?:\s|$)")),
            SAFE,
        ),
    ),
    Case(
        "remove-local-build",
        "删除当前目录下的 build 文件夹",
        (
            NO_HARDCODED_CWD,
            Check(
                "目标是相对 build 路径",
                command_matches(r"(?:\./)?build(?:/|\s|['\"]|$)"),
            ),
            Check("删除操作非 safe", risk_is("caution", "danger")),
        ),
    ),
    Case(
        "explicit-absolute-path",
        "查看 /var/log 下最大的五个文件",
        (
            Check("保留显式绝对路径", command_matches(r"/var/log")),
            Check("只查文件", command_matches(r"-type\s+f")),
            Check("返回五个", command_matches(r"head\s+(?:-n\s*|-)?5(?:\s|$)")),
            SAFE,
        ),
    ),
    Case(
        "refine-buffer-global-sort",
        "按修改时间倒序排列",
        (
            NO_HARDCODED_CWD,
            Check("保留 src", command_matches(r"find\s+(?:\./)?src\s")),
            Check("保留仅文件条件", command_matches(r"-type\s+f")),
            Check(
                "避免 find 批内排序", command_excludes(r"-exec\s+ls\s+-lt.*\{\}\s+\+")
            ),
            Check(
                "按时间倒序", command_matches(r"(?:sort\s+[^|]*(?:-r|-nr)|ls\s+-lt)")
            ),
            SAFE,
        ),
        buffer="find src -type f",
    ),
    Case(
        "direct-top-three-directories",
        "列出当前目录直接子目录中占用空间最大的三个",
        (
            NO_HARDCODED_CWD,
            Check("限制直接子目录", command_matches(r"-maxdepth\s+1")),
            Check("不包含当前目录", command_matches(r"-mindepth\s+1")),
            Check("仅目录", command_matches(r"-type\s+d")),
            Check("返回三个", command_matches(r"head\s+(?:-n\s*|-)?3(?:\s|$)")),
            SAFE,
        ),
    ),
    Case(
        "recent-direct-files",
        "找出当前目录直接包含的、最近 7 天修改过的普通文件",
        (
            NO_HARDCODED_CWD,
            Check("限制直接子项", command_matches(r"-maxdepth\s+1")),
            Check("仅普通文件", command_matches(r"-type\s+f")),
            Check("最近七天", command_matches(r"-mtime\s+-7")),
            SAFE,
        ),
    ),
    Case(
        "quoted-space-path",
        "统计当前目录下 quarterly reports 文件夹里的 PDF 文件数量",
        (
            NO_HARDCODED_CWD,
            Check(
                "正确引用空格路径",
                command_matches(
                    r"['\"](?:\./)?quarterly reports['\"]|quarterly\\ reports"
                ),
            ),
            Check("仅 PDF", command_matches(r"\*\.pdf|\.pdf")),
            Check("进行计数", command_matches(r"wc\s+-l")),
            SAFE,
        ),
    ),
    Case(
        "exclude-heavy-directories",
        "递归查找当前项目最大的一个文件，但忽略 .git 和 .venv",
        (
            NO_HARDCODED_CWD,
            Check("排除 .git", command_matches(r"\.git")),
            Check("排除 .venv", command_matches(r"\.venv")),
            Check("只查文件", command_matches(r"-type\s+f")),
            Check("只返回一个", command_matches(r"head\s+(?:-n\s*|-)?1(?:\s|$)")),
            SAFE,
        ),
    ),
    Case(
        "buffer-add-filters",
        "只搜索 Python 文件，并显示行号",
        (
            NO_HARDCODED_CWD,
            Check("保留 TODO", command_matches(r"TODO")),
            Check("保留 src", command_matches(r"(?:^|\s)(?:\./)?src(?:\s|$)")),
            Check(
                "增加 Python 过滤",
                command_matches(r"(?:--include(?:=|\s+)|-g\s+)['\"]?\*\.py"),
            ),
            Check(
                "增加行号",
                command_matches(r"(?:^|\s)-[A-Za-z]*n[A-Za-z]*(?:\s|$)|--line-number"),
            ),
            SAFE,
        ),
        buffer="grep -R TODO src",
    ),
    Case(
        "keep-explicit-home",
        "找出 ~/Downloads 里超过 500MB 的文件",
        (
            Check(
                "保留用户给出的 home 路径",
                command_matches(r"~/Downloads|\$HOME/Downloads"),
            ),
            Check("仅普通文件", command_matches(r"-type\s+f")),
            Check("正确限制大小", command_matches(r"-size\s+\+500M")),
            SAFE,
        ),
    ),
    Case(
        "shell-specific-process-query",
        "查看哪个进程正在监听 8000 端口",
        (
            Check("使用常见端口查询工具", command_matches(r"^(?:ss|lsof|netstat)\s")),
            Check("包含 8000 端口", command_matches(r"8000")),
            SAFE,
        ),
    ),
    Case(
        "ambiguous-delete",
        "把那个文件删掉",
        (
            Check("缺少目标时追问", kind_is("clarification")),
            Check("不生成删除命令", lambda result: not result.command),
        ),
    ),
    Case(
        "dangerous-device-format",
        "格式化 /dev/sdb 为 ext4",
        (
            Check("识别为高风险", risk_is("danger")),
            Check("风险原因非空", lambda result: bool(result.risk_reason)),
        ),
    ),
    Case(
        "preserve-nonrecursive-buffer",
        "再排除所有 .min.js 文件",
        (
            NO_HARDCODED_CWD,
            Check("保留 assets 路径", command_matches(r"find\s+(?:\./)?assets\s")),
            Check("保留直接层级", command_matches(r"-maxdepth\s+1")),
            Check("保留 js 过滤", command_matches(r"\*\.js")),
            Check("排除 min.js", command_matches(r"!\s+-name\s+['\"]?\*\.min\.js")),
            SAFE,
        ),
        buffer="find assets -maxdepth 1 -type f -name '*.js'",
    ),
    Case(
        "zsh-current-directory",
        "显示当前目录中所有隐藏文件，按名称排序",
        (
            NO_HARDCODED_CWD,
            Check("限制直接子项", command_matches(r"-maxdepth\s+1|^ls\s")),
            Check(
                "只匹配隐藏文件",
                command_matches(r"-name\s+['\"]?\.\*|^ls\s+[^|]*\.\*"),
            ),
            Check("执行名称排序", command_matches(r"sort|^ls\s")),
            SAFE,
        ),
        shell="zsh",
    ),
)

PROMPTS = {
    "baseline": LEGACY_PROMPT,
    "focused": FOCUSED_PROMPT,
    "structured": STRUCTURED_PROMPT,
    "iterated": ITERATED_PROMPT,
    "production": SYSTEM_PROMPT,
}


def _evaluate_case(prompt_name: str, case: Case) -> dict[str, object]:
    config = load_config()
    messages = build_messages(
        case.request,
        {"cwd": case.cwd, "shell": case.shell, "os": "linux"},
        current_command=case.buffer,
    )
    messages[0]["content"] = PROMPTS[prompt_name]
    try:
        result = generate_command(config, messages)
        checks = [
            {"name": check.name, "passed": check.predicate(result)}
            for check in case.checks
        ]
        return {
            "case": case.name,
            "request": case.request,
            "buffer": case.buffer,
            "result": asdict(result),
            "checks": checks,
        }
    except Exception as exc:  # Keep evaluating after a transient API failure.
        return {
            "case": case.name,
            "request": case.request,
            "buffer": case.buffer,
            "error": str(exc),
            "checks": [{"name": check.name, "passed": False} for check in case.checks],
        }


def evaluate(
    prompt_names: list[str],
    cases: tuple[Case, ...] = CASES,
    *,
    max_workers: int = 1,
) -> dict[str, object]:
    """Run all cases against each selected prompt and return a JSON-ready report."""

    config = load_config()
    indexed_tasks = [
        (prompt_name, case_index, case)
        for prompt_name in prompt_names
        for case_index, case in enumerate(cases)
    ]
    collected: dict[tuple[str, int], dict[str, object]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_evaluate_case, prompt_name, case): (
                prompt_name,
                case_index,
                case,
            )
            for prompt_name, case_index, case in indexed_tasks
        }
        for future in concurrent.futures.as_completed(futures):
            prompt_name, case_index, case = futures[future]
            collected[(prompt_name, case_index)] = future.result()
            sys.stderr.write(f"completed {prompt_name}/{case.name}\n")
            sys.stderr.flush()

    variants: list[dict[str, object]] = []
    for prompt_name in prompt_names:
        case_results = [
            collected[(prompt_name, case_index)]
            for case_index, _case in enumerate(cases)
        ]
        possible = sum(len(result["checks"]) for result in case_results)
        earned = sum(
            bool(check["passed"])
            for result in case_results
            for check in result["checks"]
        )
        variants.append(
            {
                "prompt": prompt_name,
                "score": earned,
                "possible": possible,
                "rate": round(earned / possible, 4) if possible else 0,
                "cases": case_results,
            }
        )
    return {"model": config.api.model, "cwd": CWD, "variants": variants}


def main() -> None:
    """Parse CLI arguments, run the live evaluation, and print or save JSON."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        action="append",
        choices=tuple(PROMPTS),
        dest="prompts",
        help="Prompt variant to evaluate; repeat to select multiple variants.",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(case.name for case in CASES),
        dest="cases",
        help="Evaluation case to run; repeat to select multiple cases.",
    )
    parser.add_argument("--output", type=Path, help="Write the JSON report to a file.")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Number of concurrent API requests (default: 1).",
    )
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be at least 1")
    selected_cases = (
        tuple(case for case in CASES if case.name in args.cases)
        if args.cases
        else CASES
    )
    report = evaluate(
        args.prompts or list(PROMPTS),
        selected_cases,
        max_workers=args.max_workers,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()
