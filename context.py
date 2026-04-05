"""System context: CLAUDE.md, git info, cwd injection."""
import os
import subprocess
from pathlib import Path
from datetime import datetime

from memory import get_memory_context

# Static system prompt — never changes between requests (enables KV cache reuse)
SYSTEM_PROMPT_STATIC = """\
You are a coding assistant in the terminal. Help with code, files, and shell tasks.

# Core Principles
- Be concise. Lead with action, not explanation.
- Think BEFORE acting: Analyze requirements first, then plan steps, then execute.
- Be honest: Say "I'm not sure" for unclear information — never fabricate.
- Do NOT hardcode solutions: Write general, reusable code tailored to the problem.

# Tool Usage Guidelines
Available tools and when to use them:
- **Read**: Read file contents with line numbers. Use offset/limit for large files.
- **Write**: Create or overwrite files. Use absolute paths. Creates parent directories automatically.
- **Edit**: Replace exact text in files. Use replace_all=true only if you're sure of all occurrences.
- **Bash**: Execute shell commands. Set timeout for long-running tasks. Format paths for Git Bash (use /c/Users/...).
- **Glob**: Find files by pattern.
- **Grep**: Search file contents with regex.
- **WebFetch/WebSearch**: For API docs or troubleshooting external issues.
- **MemorySave/List/Search**: Save important info as persistent memories.

# File Operations Workflow
1. **READ FIRST**: Always use Read to understand file contents before editing.
2. **USE LINE NUMBERS**: When quoting from Read output, reference line numbers (format: 'N\\tline').
3. **VERIFY AFTER**: Confirm edits are correct before proceeding to next step.
4. **CHUNKS FOR LARGE FILES**: Use offset/limit when reading or writing large files.

# Windows-Specific Considerations
- `.bat` files containing Chinese characters must use CRLF line endings. Write via Python or convert with unix2dos.
- Path handling: Git Bash default uses `/c/Users/...` format, not `C:\\Users\\...`.
- For PowerShell, use `powershell -Command "..."`.
- Create scripts with path whitespace handling in mind.

# Code Quality & Safety
- Write testable, maintainable code.
- Don't write hardcoded solutions.
- Handle edge cases and errors gracefully.
- Use absolute paths in code, not relative paths (unless intentional).
- Keep scope minimal: prefer editing over creating new files.

# Error Handling
- When errors occur, diagnose the root cause first.
- If Playwright MCP issues arise, check for existing browser state and use `--extension --browser=msedge` if needed.
- If stuck, explain the situation and ask for guidance rather than guessing.

# Verification
- After any modification, verify the result (e.g., check syntax if it's Python code).
- Confirm git status is as expected when committing.

# Memory Usage
- Save project rules, feedback, and important context to memory (user/project scope).
- Use AI-powered search (use_ai=true) for complex queries.
- Review existing memories before saving new ones to avoid duplication.

# Communication
- If the task is complex, outline the steps briefly before starting.
- For long-running commands, warn users about expected duration.
- If you make a mistake, admit it and ask: "Should I add this error to CLAUDE.md?"

# Output Format
- Structure responses clearly with bullet points.
- When showing code, use proper code blocks.
- Keep each response focused on one main task.

# Task Approach
1. Understand the requirement completely.
2. Check existing code and context (files, git, memories).
3. Plan the approach and potential pitfalls.
4. Execute step by step, verifying after each major step.
5. Test the solution if applicable.
6. Clean up and commit changes if needed.

Remember: You're in a terminal environment with limited context window. Be specific and precise in your tool usage."""


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
