"""DGM Self-Evolution — Agent 通过修改自己的 system prompt 来提升 eval 分数

流程:
1. 用当前 prompt 跑 eval → 基准分
2. Agent 分析失败任务，修改 context.py 的 SYSTEM_PROMPT_STATIC
3. 重跑 eval → 新分数
4. 如果变高 → 保留修改；变低或不变 → 回滚
5. 循环

用法:
    cd nano-claude-code
    python eval/evolve.py [--generations 5] [--max-rounds 2]
"""

import sys
import os
import json
import shutil
import subprocess
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

CONTEXT_FILE = Path(__file__).parent.parent / "context.py"
EVAL_SCRIPT = Path(__file__).parent / "run_eval.py"


def verify_context_syntax() -> tuple[bool, str]:
    """验证 context.py 语法是否正确"""
    result = subprocess.run(
        [sys.executable, "-c", f"import ast; ast.parse(open(r'{CONTEXT_FILE}').read()); print('OK')"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.strip()


def fix_broken_context(error_msg: str, config: dict) -> bool:
    """让 Agent 修复被写坏的 context.py"""
    from agent import AgentState, run as agent_run, TextChunk, ToolStart, ToolEnd, TurnDone
    from context import build_system_prompt

    console.print(f"[red]context.py 语法错误，让 Agent 修复...[/red]")
    console.print(f"[dim]{error_msg[:300]}[/dim]")

    prompt = f"""context.py 文件有语法错误，请修复。

错误信息:
```
{error_msg}
```

请用 Read 工具读取 context.py，找到语法错误并用 Edit 修复。
注意保持 SYSTEM_PROMPT_STATIC 的完整性。"""

    state = AgentState()
    system = build_system_prompt()
    config_copy = {**config, "permission_mode": "accept-all"}

    for event in agent_run(prompt, state, config_copy, system):
        if isinstance(event, TextChunk):
            console.print(event.text, end="")
        elif isinstance(event, ToolStart):
            console.print(f"\n  [dim]🔧 {event.name}[/dim]")

    console.print()

    ok, err = verify_context_syntax()
    if ok:
        console.print("[green]语法修复成功[/green]")
    else:
        console.print(f"[red]修复失败，将回滚: {err[:100]}[/red]")
    return ok


def run_eval(config: dict, max_rounds: int) -> tuple[float, list[dict]]:
    """运行 eval 并返回 (得分百分比, 结果列表)"""
    # 先验证 context.py 语法
    ok, err = verify_context_syntax()
    if not ok:
        return -1.0, [{"error": err}]

    # 用子进程跑 eval，避免模块缓存问题
    cmd = [
        sys.executable, "-u", str(EVAL_SCRIPT),
        "--max-rounds", str(max_rounds),
        "--model", config["model"],
    ]
    result = subprocess.run(
        cmd, timeout=None, cwd=str(Path(__file__).parent.parent),
    )

    # 找最新的 result 文件
    eval_dir = Path(__file__).parent
    result_files = sorted(eval_dir.glob("result_*.json"), key=lambda f: f.stat().st_mtime)
    if not result_files:
        return 0.0, []

    latest = json.loads(result_files[-1].read_text())
    # 返回效率分（综合通过率和速度）
    efficiency = latest.get("efficiency", 0.0)
    pct = latest.get("pct", 0.0)
    return efficiency, pct, latest.get("results", [])


def analyze_and_evolve(
    score: float,
    results: list[dict],
    generation: int,
    config: dict,
) -> bool:
    """让 agent 分析失败原因并修改 system prompt，返回是否做了修改"""
    from agent import AgentState, run as agent_run, TextChunk, ToolStart, ToolEnd, TurnDone
    from context import build_system_prompt

    failed = [r for r in results if not r.get("passed")]
    if not failed:
        console.print("[green]所有任务都通过了，无需进化[/green]")
        return False

    failed_names = ", ".join(r["name"] for r in failed)

    # 读取当前 prompt 内容给 Agent 看
    current_context = CONTEXT_FILE.read_text(encoding="utf-8")

    prompt = f"""你需要改进一个 AI coding agent 的 system prompt，提升它解决编程问题的能力。

# 当前评测结果
得分: {score:.0f}%，失败任务: {failed_names}

# 失败详情
{json.dumps(failed, indent=2, ensure_ascii=False)}

# 当前的 context.py
```python
{current_context}
```

# 你的任务
重写 {CONTEXT_FILE} 中 SYSTEM_PROMPT_STATIC 变量的内容（三引号之间的文本）。

你可以自由修改 {CONTEXT_FILE} 的任何部分 — prompt 内容、结构、函数逻辑都可以改。
唯一的硬性要求：
- 修改后 context.py 必须是合法的 Python，且 build_system_prompt() 和 build_context_message() 函数必须能正常调用返回字符串
- 不要写死具体任务的解法

提示：你可以用 SelfInspect("overview") 查看系统架构和限制，用 SelfInspect("context.py") 查看当前 prompt 的完整代码。

思考：这个 agent 为什么会在某些任务上失败？它的工作流程缺少了什么？什么样的 prompt 能引导出更好的问题解决行为？"""

    state = AgentState()
    system = build_system_prompt()
    config_copy = {**config, "permission_mode": "accept-all"}

    made_changes = False
    for event in agent_run(prompt, state, config_copy, system):
        if isinstance(event, TextChunk):
            console.print(event.text, end="")
        elif isinstance(event, ToolStart):
            console.print(f"\n  [dim]🔧 {event.name}[/dim]")
            if event.name == "Edit":
                made_changes = True
        elif isinstance(event, ToolEnd):
            pass

    console.print()
    return made_changes


def main():
    parser = argparse.ArgumentParser(description="DGM Self-Evolution")
    parser.add_argument("--generations", type=int, default=3, help="进化代数")
    parser.add_argument("--max-rounds", type=int, default=2, help="每个 eval 任务的最大循环轮数")
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()

    config = load_config()
    if args.model:
        config["model"] = args.model
    config["permission_mode"] = "accept-all"

    console.print(Panel(
        f"模型: {config['model']}\n进化代数: {args.generations}\n每任务最大轮数: {args.max_rounds}",
        title="🧬 DGM Self-Evolution",
        border_style="magenta",
    ))

    # 备份原始 context.py
    backup = CONTEXT_FILE.read_text(encoding="utf-8")
    history = []

    best_score = 0.0
    best_prompt = backup

    for gen in range(1, args.generations + 1):
        console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
        console.print(f"[bold magenta]第 {gen}/{args.generations} 代[/bold magenta]")
        console.print(f"[bold magenta]{'='*60}[/bold magenta]")

        # 1. 跑 eval
        console.print("\n[cyan]运行评测...[/cyan]")
        efficiency, pass_rate, results = run_eval(config, args.max_rounds)
        console.print(f"[bold]通过率: {pass_rate:.0f}% | 效率分: {efficiency:.1f}[/bold]")

        history.append({"generation": gen, "efficiency": efficiency, "pass_rate": pass_rate, "phase": "eval"})

        if efficiency > best_score:
            best_score = efficiency
            best_prompt = CONTEXT_FILE.read_text(encoding="utf-8")

        if pass_rate == 100.0 and efficiency >= best_score:
            console.print("[green bold]满分且效率最优！进化完成。[/green bold]")
            break

        # 2. Agent 分析并修改 prompt
        console.print(f"\n[cyan]Agent 分析失败原因并进化 prompt...[/cyan]")
        pre_change = CONTEXT_FILE.read_text(encoding="utf-8")
        changed = analyze_and_evolve(pass_rate, results, gen, config)

        if not changed:
            console.print("[yellow]Agent 没有做出修改，跳过验证[/yellow]")

        # 3. 验证语法 — 坏了就让 agent 修，修不好回滚
        if changed:
            ok, err = verify_context_syntax()
            if not ok:
                fixed = fix_broken_context(err, config)
                if not fixed:
                    console.print("[red]修复失败，回滚到修改前[/red]")
                    CONTEXT_FILE.write_text(pre_change, encoding="utf-8")
                    continue

        if not changed:
            continue

        # 4. 重跑 eval 验证
        console.print(f"\n[cyan]验证进化后的效果...[/cyan]")
        new_eff, new_pct, new_results = run_eval(config, args.max_rounds)
        console.print(f"[bold]新: 通过率 {new_pct:.0f}%, 效率分 {new_eff:.1f} (之前: {pass_rate:.0f}%, {efficiency:.1f})[/bold]")

        history.append({"generation": gen, "efficiency": new_eff, "pass_rate": new_pct, "phase": "evolved"})

        if new_eff > efficiency:
            console.print(f"[green bold]进化成功！效率 {efficiency:.1f} → {new_eff:.1f}[/green bold]")
            if new_eff > best_score:
                best_score = new_eff
                best_prompt = CONTEXT_FILE.read_text(encoding="utf-8")
        elif new_pct < pass_rate:
            console.print(f"[red]通过率下降 {pass_rate:.0f}% → {new_pct:.0f}%，回滚[/red]")
            CONTEXT_FILE.write_text(best_prompt, encoding="utf-8")
        else:
            console.print(f"[yellow]通过率不变，保留修改继续[/yellow]")

    # 汇总
    console.print(f"\n{'='*60}")
    table = Table(title="进化历史")
    table.add_column("代", justify="center")
    table.add_column("阶段")
    table.add_column("通过率", justify="right")
    table.add_column("效率分", justify="right")

    for h in history:
        table.add_row(
            str(h["generation"]), h["phase"],
            f"{h.get('pass_rate', 0):.0f}%",
            f"{h.get('efficiency', 0):.1f}",
        )

    console.print(table)
    console.print(f"\n[bold]最终最佳分数: {best_score:.0f}%[/bold]")

    # 显示 prompt 变化
    current_prompt = CONTEXT_FILE.read_text(encoding="utf-8")
    if current_prompt != backup:
        console.print(f"\n[bold cyan]Prompt 变化:[/bold cyan]")
        import difflib
        diff = difflib.unified_diff(
            backup.splitlines(), current_prompt.splitlines(),
            fromfile="原始", tofile="进化后", lineterm=""
        )
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                console.print(f"[green]{line}[/green]")
            elif line.startswith("-") and not line.startswith("---"):
                console.print(f"[red]{line}[/red]")
            else:
                console.print(f"[dim]{line}[/dim]")
    else:
        console.print("[dim]Prompt 未发生变化[/dim]")

    # 保存进化记录
    evo_file = Path(__file__).parent / f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    evo_file.write_text(json.dumps({
        "model": config["model"],
        "generations": args.generations,
        "best_score": best_score,
        "history": history,
    }, ensure_ascii=False, indent=2))
    console.print(f"\n[dim]进化记录: {evo_file}[/dim]")


if __name__ == "__main__":
    main()
