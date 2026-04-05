"""DGM Self-Evolution — Agent 通过修改 system prompt 和运行参数来提升 eval 分数

流程:
1. 用当前 prompt + config 跑 eval → 基准分
2. Agent 分析失败任务，可修改:
   - context.py 的 SYSTEM_PROMPT_STATIC（行为策略）
   - config.py 的 DEFAULTS（max_tokens, thinking, tool_output 等运行参数）
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

PROJECT_ROOT = Path(__file__).parent.parent
CONTEXT_FILE = PROJECT_ROOT / "context.py"
CONFIG_FILE  = PROJECT_ROOT / "config.py"
EVOLVABLE_FILES = [CONTEXT_FILE, CONFIG_FILE]
EVAL_SCRIPT = Path(__file__).parent / "run_eval.py"


def _verify_syntax(filepath: Path) -> tuple[bool, str]:
    """验证单个 Python 文件语法是否正确"""
    result = subprocess.run(
        [sys.executable, "-c", f"import ast; ast.parse(open(r'{filepath}').read()); print('OK')"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.strip()


def verify_all_syntax() -> tuple[bool, str]:
    """验证所有可进化文件的语法"""
    for f in EVOLVABLE_FILES:
        ok, err = _verify_syntax(f)
        if not ok:
            return False, f"{f.name}: {err}"
    return True, ""


# 向后兼容
verify_context_syntax = verify_all_syntax


def fix_broken_files(error_msg: str, config: dict) -> bool:
    """让 Agent 修复被写坏的文件"""
    from agent import AgentState, run as agent_run, TextChunk, ToolStart, ToolEnd, TurnDone
    from context import build_system_prompt

    console.print(f"[red]语法错误，让 Agent 修复...[/red]")
    console.print(f"[dim]{error_msg[:300]}[/dim]")

    prompt = f"""进化过程中产生了语法错误，请修复。

错误信息:
```
{error_msg}
```

请用 Read 工具读取出错的文件，找到语法错误并用 Edit 修复。
注意保持文件的功能完整性。"""

    state = AgentState()
    system = build_system_prompt()
    config_copy = {**config, "permission_mode": "accept-all"}

    for event in agent_run(prompt, state, config_copy, system):
        if isinstance(event, TextChunk):
            console.print(event.text, end="")
        elif isinstance(event, ToolStart):
            console.print(f"\n  [dim]🔧 {event.name}[/dim]")

    console.print()

    ok, err = verify_all_syntax()
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
    """让 agent 分析失败原因并修改 system prompt 和运行参数，返回是否做了修改"""
    from agent import AgentState, run as agent_run, TextChunk, ToolStart, ToolEnd, TurnDone
    from context import build_system_prompt

    failed = [r for r in results if not r.get("passed")]
    if not failed:
        console.print("[green]所有任务都通过了，无需进化[/green]")
        return False

    failed_names = ", ".join(r["name"] for r in failed)

    # 读取当前可进化文件内容
    current_context = CONTEXT_FILE.read_text(encoding="utf-8")
    current_config = CONFIG_FILE.read_text(encoding="utf-8")

    prompt = f"""你需要改进一个 AI coding agent，提升它解决编程问题的能力。

# 当前评测结果
得分: {score:.0f}%，失败任务: {failed_names}

# 失败详情
{json.dumps(failed, indent=2, ensure_ascii=False)}

# 你可以修改的文件

## 1. context.py — 行为策略（system prompt）
路径: {CONTEXT_FILE}
```python
{current_context}
```
可改内容:
- SYSTEM_PROMPT_STATIC: agent 的行为指令、工作流程、工具使用规则
- build_context_message(): 注入的动态上下文

## 2. config.py — 运行参数
路径: {CONFIG_FILE}
```python
{current_config}
```
可改的 DEFAULTS 参数:
- max_tokens: 单次回复最大 token（当前 {config.get('max_tokens', 8192)}，增大可让 agent 输出更完整的修复）
- max_tool_output: 工具输出截断阈值（当前 {config.get('max_tool_output', 32000)}，增大可看到更多错误信息）
- thinking / thinking_budget: 扩展思考（如果模型支持）

# 修改规则
1. 修改后两个文件都必须是合法 Python
2. config.py: load_config() 和 save_config() 必须能正常工作
3. context.py: build_system_prompt() 和 build_context_message() 必须返回字符串
4. 不要写死具体任务的解法
5. 不要改 model 字段（模型由外部指定）
6. 不要改 permission_mode（eval 时强制 accept-all）

# 分析思路
- 失败任务的 verify_output 显示了什么错误？
- agent 是工具使用不当？还是策略有问题？还是输出被截断了？
- max_tokens 太小会不会导致修复代码不完整？
- 是不是需要在 prompt 里加入更好的 debug 策略？

提示：你可以用 SelfInspect("overview") 查看系统架构和限制。"""

    state = AgentState()
    system = build_system_prompt()
    config_copy = {**config, "permission_mode": "accept-all"}

    made_changes = False
    for event in agent_run(prompt, state, config_copy, system):
        if isinstance(event, TextChunk):
            console.print(event.text, end="")
        elif isinstance(event, ToolStart):
            console.print(f"\n  [dim]🔧 {event.name}[/dim]")
            if event.name in ("Edit", "Write"):
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

    # 备份所有可进化文件
    backups = {f: f.read_text(encoding="utf-8") for f in EVOLVABLE_FILES}
    history = []

    best_score = 0.0
    best_state = dict(backups)  # 最佳状态的文件快照

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
            best_state = {f: f.read_text(encoding="utf-8") for f in EVOLVABLE_FILES}

        if pass_rate == 100.0 and efficiency >= best_score:
            console.print("[green bold]满分且效率最优！进化完成。[/green bold]")
            break

        # 2. Agent 分析并修改 prompt + config
        console.print(f"\n[cyan]Agent 分析失败原因并进化...[/cyan]")
        pre_change = {f: f.read_text(encoding="utf-8") for f in EVOLVABLE_FILES}
        changed = analyze_and_evolve(pass_rate, results, gen, config)

        if not changed:
            console.print("[yellow]Agent 没有做出修改，跳过验证[/yellow]")

        # 3. 验证语法 — 坏了就让 agent 修，修不好回滚
        if changed:
            ok, err = verify_all_syntax()
            if not ok:
                fixed = fix_broken_files(err, config)
                if not fixed:
                    console.print("[red]修复失败，回滚到修改前[/red]")
                    for f, content in pre_change.items():
                        f.write_text(content, encoding="utf-8")
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
                best_state = {f: f.read_text(encoding="utf-8") for f in EVOLVABLE_FILES}
        elif new_pct < pass_rate:
            console.print(f"[red]通过率下降 {pass_rate:.0f}% → {new_pct:.0f}%，回滚[/red]")
            for f, content in best_state.items():
                f.write_text(content, encoding="utf-8")
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

    # 显示所有文件变化
    import difflib
    any_changed = False
    for f in EVOLVABLE_FILES:
        current = f.read_text(encoding="utf-8")
        original = backups[f]
        if current != original:
            any_changed = True
            console.print(f"\n[bold cyan]{f.name} 变化:[/bold cyan]")
            diff = difflib.unified_diff(
                original.splitlines(), current.splitlines(),
                fromfile=f"原始 {f.name}", tofile=f"进化后 {f.name}", lineterm=""
            )
            for line in diff:
                if line.startswith("+") and not line.startswith("+++"):
                    console.print(f"[green]{line}[/green]")
                elif line.startswith("-") and not line.startswith("---"):
                    console.print(f"[red]{line}[/red]")
                else:
                    console.print(f"[dim]{line}[/dim]")
    if not any_changed:
        console.print("[dim]文件未发生变化[/dim]")

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
