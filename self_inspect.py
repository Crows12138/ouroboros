"""Self-inspection — 让 agent 了解自己的结构

提供快捷方式查看自身代码、配置、能力边界。
Agent 可以通过这些信息做出更好的自我改进决策。
"""

from pathlib import Path
from tool_registry import get_all_tools

PROJECT_ROOT = Path(__file__).parent


def get_architecture() -> str:
    """返回系统架构概览"""
    tools = get_all_tools()
    tool_names = [t.name for t in tools]

    files = {
        "context.py": "System prompt 和上下文注入",
        "agent.py": "Agent 循环（推理→工具调用→结果→继续）",
        "tools.py": "工具定义和实现",
        "providers.py": "LLM 接入（Ollama/OpenAI/Anthropic）",
        "compaction.py": "上下文压缩（85% 阈值触发）",
        "config.py": "配置管理",
        "loop.py": "Circle Loop 循环改进引擎",
        "nano_claude.py": "主入口和 REPL",
        "memory/": "持久记忆系统",
        "eval/": "自我进化评测框架",
    }

    lines = ["# 系统架构\n"]
    lines.append("## 文件结构")
    for f, desc in files.items():
        path = PROJECT_ROOT / f
        if path.exists():
            if path.is_file():
                loc = sum(1 for _ in open(path, errors="replace"))
                lines.append(f"- `{f}` ({loc} lines) — {desc}")
            else:
                lines.append(f"- `{f}` — {desc}")

    lines.append(f"\n## 已注册工具 ({len(tool_names)})")
    for t in tools:
        ro = "只读" if t.read_only else "可写"
        lines.append(f"- `{t.name}` ({ro})")

    return "\n".join(lines)


def get_constraints() -> str:
    """返回系统的能力边界和限制"""
    from config import load_config
    from compaction import get_context_limit

    config = load_config()
    model = config.get("model", "unknown")
    ctx_limit = get_context_limit(model)

    from context import SYSTEM_PROMPT_STATIC
    prompt_tokens = len(SYSTEM_PROMPT_STATIC) // 4  # 粗估

    return f"""# 系统限制

## 模型
- 当前模型: {model}
- 上下文窗口: {ctx_limit} tokens
- System prompt 占用: ~{prompt_tokens} tokens
- 可用对话空间: ~{ctx_limit - prompt_tokens} tokens

## Compact 机制
- 触发阈值: 上下文的 85%（{int(ctx_limit * 0.85)} tokens）
- 层1: 截断旧工具输出（保留最近 6 轮）
- 层2: LLM 总结旧对话（保留最近 30%）

## Circle Loop
- 默认无限轮，Ctrl+C 中断
- 每轮验证命令决定 pass/fail
- 上下文持续累积，compact 自动管理
- 通过后自动提炼经验存入 memory

## 限制
- 单次处理最好不超过 1-2 个文件
- 工具输出最大 32000 字符（超出截断）
- Bash 命令无超时限制
- 无法处理图片/二进制文件
"""


def get_file_summary(filename: str) -> str:
    """返回指定文件的内容摘要（首尾 + 函数列表）"""
    path = PROJECT_ROOT / filename
    if not path.exists():
        return f"文件不存在: {filename}"

    content = path.read_text(errors="replace")
    lines = content.splitlines()
    total = len(lines)

    # 提取函数/类定义
    defs = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("def ", "class ", "async def ")):
            defs.append(f"  L{i}: {stripped}")

    result = [f"# {filename} ({total} lines)\n"]

    if defs:
        result.append("## 定义")
        result.extend(defs[:30])

    # 首 10 行
    result.append(f"\n## 首 10 行")
    for i, line in enumerate(lines[:10], 1):
        result.append(f"  {i}: {line}")

    return "\n".join(result)


def get_self_report() -> str:
    """完整的自我报告"""
    return get_architecture() + "\n\n" + get_constraints()
