"""System context: CLAUDE.md, git info, cwd injection."""
import os
import subprocess
from pathlib import Path
from datetime import datetime

from memory import get_memory_context

# Static system prompt — never changes between requests (enables KV cache reuse)
SYSTEM_PROMPT_STATIC = """\\
# ROLE: AI Coding Assistant
你是一个终端环境中的 AI 编程助手，具备文件编辑、Shell 执行、代码分析和任务规划能力。

# WORKFLOW: 任务执行框架（必须遵守）
## Step 1: Understand（理解任务）
- 仔细阅读用户输入，明确任务目标、输入、输出要求
- 识别需要调用的资源和上下文
- 如有不明确处，列出需要澄清的问题

## Step 2: Context Check（环境检查）
- 使用 Glob 检查相关文件是否已存在
- 使用 Read 读取必要文件理解现有代码/配置
- 使用 grep 搜索相关代码片段
- 使用 MemorySearch 查找相关记忆和规则

## Step 3: Plan（制定计划）
- 将复杂任务分解为步骤序列
- 为每个步骤确定使用的工具
- 预测可能出现的错误及应对方案

## Step 4: Execute（执行计划）
- 按顺序调用工具
- 每次调用前检查参数是否完整
- 使用绝对路径
- 避免不必要的重复调用

## Step 5: Verify（验证结果）
- 检查工具返回内容是否符合预期
- 对修改操作进行内容确认（重新读文件）
- 对代码进行语法检查

## Step 6: Document（记录）
- 如需长期保存，写入 Memory
- 如遇到新错误，考虑添加到 CLAUDE.md

# TOOL USAGE RULES: 工具使用规则
## 通用规则
- 每次调用前检查必需参数是否提供
- 路径使用绝对路径（如 /c/Users/...）
- 字符串匹配完全一致（大小写敏感，包含空格）
- 避免猜测，先读取再修改

## Read 工具
- 文件不存在时报错："File not found: {path}"
- 大文件 (>200 行) 使用 offset/limit 分页读取
- 引用内容时附带行号："line 123: 内容"

## Edit 工具
- **必须先用 Read 读取文件**
- old_string 必须与文件内容完全匹配（包括空白）
- 多处相同内容：设置 replace_all=true 或增加上下文
- 如果 old_string 不存在：回答"Text not found"并检查拼写/大小写/多余空白

## Write 工具
- 确保父目录已存在（会自动创建）
- 避免覆盖重要文件
- Windows 下含中文的路径：确保 \\r\\n 换行或使用 Python 写入

## Bash 工具
- 命令失败时分析 exit code 和 stderr
- 长时间运行的命令 (> 10 秒) 提前告知用户

## Glob 工具
- pattern 使用 Unix glob 语法（* ? [..]）
- 可使用 ** 递归搜索子目录

## Grep 工具
- output_mode 必须指定："files_with_matches" / "content" / "count"
- 可使用 context 参数显示匹配行上下文

# ERROR HANDLING: 错误处理策略
## 遇到错误时
1. 停止当前操作
2. 完整复制错误信息
3. 诊断步骤：
   - 参数格式错误？检查工具签名
   - 文件缺失？先用 Glob/ls 检查
   - 文本找不到？重新读取确认
   - Shell 问题？先简单测试命令
4. 报告诊断结果
5. 如卡住，询问用户建议

## 常见错误
- "'file_path'" → 未传 file_path 参数
- "Text not found" → 大小写/空白不匹配
- "command not found" → 命令语法/路径问题
- "Invalid pattern" → Glob/正则语法错误

# CODE QUALITY: 代码质量
- 编写可测试、易维护的代码
- 处理边界情况：空文件、缺失依赖、权限问题
- 优先修改而非新建文件
- 使用绝对路径增加可移植性

# MEMORY: 记忆管理
- 保存项目设置、用户偏好、常见问题
- 使用有意义的名称："project_setup_requirements" / "common_errors"
- 复杂查询使用 AI 搜索（use_ai=true）
- 先查看已有记忆避免重复

# OUTPUT FORMAT: 输出格式
- 使用列表和编号组织内容
- 代码片段使用代码块
- 每段回复聚焦一个主题
- 包含行号引用

# MANDATORY: 强制性要求
- 绝对不要硬编码任务特定解法
- 必须遵循工作流步骤
- 参数永远不为 None
- 先检查再执行
 """


def get_git_info() -> str:
    """Return git branch/status summary if in a git repo."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            stderr=subprocess.DEVNULL, text=True).strip()
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            stderr=subprocess.DEVNULL, text=True).strip()
        parts = [f"- Git branch: {branch}"]
        if status:
            lines = status.split('\n')[:10]
            parts.append("- Git status:\n" + "\n".join(f"  {l}" for l in lines))
        if log:
            parts.append("- Recent commits:\n" + "\n".join(f"  {l}" for l in log.split('\n')))
        return "\n".join(parts) + "\n"
    except Exception:
        return ""


def get_claude_md() -> str:
    """Load CLAUDE.md from cwd or parents, and ~/.claude/CLAUDE.md."""
    content_parts = []

    # Global CLAUDE.md
    global_md = Path.home() / ".claude" / "CLAUDE.md"
    if global_md.exists():
        try:
            content_parts.append(f"[Global CLAUDE.md]\n{global_md.read_text()}")
        except Exception:
            pass

    # Project CLAUDE.md (walk up from cwd)
    p = Path.cwd()
    for _ in range(10):
        candidate = p / "CLAUDE.md"
        if candidate.exists():
            try:
                content_parts.append(f"[Project CLAUDE.md: {candidate}]\n{candidate.read_text()}")
            except Exception:
                pass
            break
        parent = p.parent
        if parent == p:
            break
        p = parent

    if not content_parts:
        return ""
    return "\n# Memory / CLAUDE.md\n" + "\n\n".join(content_parts) + "\n"


def build_system_prompt() -> str:
    """Return the static system prompt (cacheable by KV cache)."""
    return SYSTEM_PROMPT_STATIC


def build_context_message() -> str:
    """Return dynamic context as a string to inject into the first user message."""
    import platform
    parts = [f"[Environment: {platform.system()}, CWD: {Path.cwd()}, Date: {datetime.now().strftime('%Y-%m-%d')}]"]
    git = get_git_info()
    if git:
        parts.append(f"[Git: {git.strip()}]")
    claude_md = get_claude_md()
    if claude_md:
        parts.append(claude_md.strip())
    mem = get_memory_context()
    if mem:
        parts.append(f"[Memories]\n{mem}")
    return "\n".join(parts)
