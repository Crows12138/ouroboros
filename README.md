# Nano Claude Code Lite — Self-Evolving Local AI Agent

基于 [nano-claude-code](https://github.com/SafeRL-Lab/nano-claude-code) 的轻量 fork，针对本地小模型优化，具备自我进化能力。

```
┌─────────────────────────────────────────────────┐
│  Nano Claude Code Lite                          │
│  Powered by Qwen 3.5 9B · Ollama · Local       │
│                                                 │
│  ❯ /circle "pytest" -- fix all bugs             │
│    ━━━ 第 1 轮 ━━━                              │
│    🔧 Read → Edit → Bash(pytest) → ✅ PASS     │
│    💡 经验已保存: 先读测试再改代码               │
└─────────────────────────────────────────────────┘
```

## 核心特性

### 本地运行，零成本
- 通过 Ollama 运行 Qwen 3.5 9B，完全本地推理
- 创建了 `qwen3.5-16k` 模型（固定 16K 上下文，适配 12GB 显存）
- 静态 System Prompt 启用 KV Cache 复用，响应速度提升 3 倍

### Circle Loop — 自动改进循环
```bash
/circle "pytest tests/" -- 修复所有测试
/circle 10 "flake8 && mypy" -- 最多 10 轮修复代码质量
```
- 持续上下文：模型记住之前尝试了什么，不重复犯错
- 自动验证：verify 命令决定 pass/fail，不靠模型判断
- 经验积累：循环结束自动提炼经验存入 Memory
- 过程日志：每轮记录保存到 `~/.nano_claude/loops/`

### DGM 自我进化
```bash
python eval/evolve.py --generations 5
```
- Agent 分析自己在 eval 任务上的失败原因
- 自由修改 `context.py`（System Prompt、函数结构都可以改）
- 语法检查 + 自修复 + 分数下降回滚，三重安全保护
- 效率评分 = 通过率 / 平均耗时，防止 prompt 膨胀导致变慢

### 自我认知
```
❯ 你有什么能力？
  🔧 SelfInspect(overview)
  → 返回系统架构、工具列表、上下文限制...
```
- Agent 可以查看自己的代码和限制
- 进化时先了解自身再决定怎么改

### 持久记忆
- 用户级 (`~/.nano_claude/memory/`) — 跨项目共享
- 项目级 (`.nano_claude/memory/`) — 项目特定
- 自动注入到上下文，越用越懂你

## 与上游的区别

| | 上游 nano-claude-code | 本 fork |
|--|--|--|
| 定位 | 通用多模型 | 本地小模型优化 |
| System Prompt | ~1.5K tokens | 精简 + 静态化（KV Cache） |
| 工具 | 15+ (含 Task/Agent/Skill/MCP/Plugin) | 13 (8 核心 + 4 Memory + SelfInspect) |
| 默认模型 | Claude Opus | Ollama Qwen 3.5 9B |
| Compact 阈值 | 70% | 85% |
| Circle Loop | 无 | ✅ `/circle` 命令 |
| DGM 进化 | 无 | ✅ `eval/evolve.py` |
| 自我认知 | 无 | ✅ `SelfInspect` 工具 |
| 经验积累 | 无 | ✅ Loop 后自动提炼 |

## 快速开始

### 前置条件
- [Ollama](https://ollama.com/download) 已安装
- Python 3.10+

### 安装
```bash
# 克隆
git clone <your-repo-url>
cd nano-claude-code

# 安装依赖
pip install anthropic openai httpx rich

# 创建 16K 上下文模型
echo 'FROM qwen3.5:9b
PARAMETER num_ctx 16384' > /tmp/Modelfile
ollama create qwen3.5-16k -f /tmp/Modelfile
```

### 使用
```bash
# 普通对话
python nano_claude.py

# 指定模型
python nano_claude.py --model "ollama/qwen3.5-16k"

# Circle Loop
# 进入后输入:
/circle "pytest tests/" -- 修复所有失败的测试

# DGM 自我进化
python eval/evolve.py --generations 5
```

## 项目结构

```
nano-claude-code/
├── nano_claude.py        # 主入口 REPL
├── agent.py              # Agent 循环引擎
├── context.py            # System Prompt（可被进化修改）
├── tools.py              # 13 个工具的定义和实现
├── providers.py          # LLM 接入层（Ollama/OpenAI/Anthropic）
├── compaction.py          # 上下文压缩（85% 阈值）
├── config.py             # 配置管理
├── loop.py               # Circle Loop 循环改进引擎
├── self_inspect.py       # 自我认知工具
├── memory/               # 持久记忆系统
└── eval/
    ├── run_eval.py       # Mini SWE-bench 评测（13 任务 / 142 测试）
    ├── evolve.py         # DGM 自我进化引擎
    └── tasks/            # 评测任务集
```

## 工具清单

| 工具 | 用途 |
|------|------|
| Read | 读文件（带行号） |
| Write | 写文件（创建目录） |
| Edit | 局部编辑（字符串替换） |
| Bash | Shell 命令执行 |
| Glob | 文件模式搜索 |
| Grep | 内容正则搜索 |
| WebFetch | 抓取网页内容 |
| WebSearch | DuckDuckGo 搜索 |
| MemorySave | 保存持久记忆 |
| MemoryDelete | 删除记忆 |
| MemorySearch | 搜索记忆 |
| MemoryList | 列出所有记忆 |
| SelfInspect | 查看自身架构和代码 |

## 设计理念

**适应而非通用。** 这个系统不追求在所有任务上都好，而是通过 DGM 进化针对特定场景深度适配。就像生物进化——北极熊适应寒冷，骆驼适应沙漠。给它不同的 eval 任务集，它会进化出不同的 prompt 策略。

**进度在文件里，不在上下文里。** Circle Loop 借鉴 Ralph Loop 模式，用 git 和文件系统保存进度，模型上下文只用于当前轮的推理。上下文满了由 compact 自动压缩，不影响进度。

**评估在 Agent 改不到的地方。** DGM 的核心安全设计——Agent 可以改自己的 prompt，但 eval 和回滚机制在主进程里，Agent 无法绕过。

## 致谢

- [nano-claude-code](https://github.com/SafeRL-Lab/nano-claude-code) — 上游项目
- [Claude Code](https://claude.com/claude-code) — 架构参考
- [Meta HYPERAGENTS](https://arxiv.org/abs/2504.08066) — DGM 自我进化论文
- [Ralph Loop](https://github.com/disler/infinite-agentic-loop) — 循环改进模式
