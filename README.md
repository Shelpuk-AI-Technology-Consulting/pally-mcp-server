# PAL MCP: Many Workflows. One Context.

<div align="center">

  <em>Your AI's PAL – a Provider Abstraction Layer</em><br />
  <sub><a href="docs/name-change.md">Formerly known as Zen MCP</a></sub>

  [PAL in action](https://github.com/user-attachments/assets/0d26061e-5f21-4ab1-b7d0-f883ddc2c3da)

👉 **[Watch more examples](#-watch-tools-in-action)**

### Your CLI + Multiple Models = Your AI Dev Team

**Use the 🤖 CLI you love:**  
[Claude Code](https://www.anthropic.com/claude-code) · [Gemini CLI](https://github.com/google-gemini/gemini-cli) · [Codex CLI](https://github.com/openai/codex) · [Qwen Code CLI](https://qwenlm.github.io/qwen-code-docs/) · [Cursor](https://cursor.com) · _and more_

**With multiple models within a single prompt:**  
Gemini · OpenAI · Anthropic · Grok · Azure · Ollama · OpenRouter · DIAL · On-Device Model

</div>

---

## 🆕 Now with CLI-to-CLI Bridge

The new **[`clink`](docs/tools/clink.md)** (CLI + Link) tool connects external AI CLIs directly into your workflow:

- **Connect external CLIs** like [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Codex CLI](https://github.com/openai/codex), and [Claude Code](https://www.anthropic.com/claude-code) directly into your workflow
- **CLI Subagents** - Launch isolated CLI instances from _within_ your current CLI! Claude Code can spawn Codex subagents, Codex can spawn Gemini CLI subagents, etc. Offload heavy tasks (code reviews, bug hunting) to fresh contexts while your main session's context window remains unpolluted. Each subagent returns only final results.
- **Context Isolation** - Run separate investigations without polluting your primary workspace
- **Role Specialization** - Spawn `planner`, `codereviewer`, or custom role agents with specialized system prompts
- **Full CLI Capabilities** - Web search, file inspection, MCP tool access, latest documentation lookups
- **Seamless Continuity** - Sub-CLIs participate as first-class members with full conversation context between tools

```bash
# Codex spawns Codex subagent for isolated code review in fresh context
clink with codex codereviewer to audit auth module for security issues
# Subagent reviews in isolation and returns a final report without cluttering your context.
# Codex reads files and walks the directory structure in the subagent session.

# Consensus from different AI models → Implementation handoff with full context preservation between tools
Use consensus with two models (one deep, one fast) to decide: dark mode or offline support next
clink with gemini to implement the recommended feature
# Gemini receives full debate context and starts coding immediately
```

👉 **[Learn more about clink](docs/tools/clink.md)**

---

## Why PAL MCP?

**Why rely on one AI model when you can orchestrate them all?**

A Model Context Protocol server that supercharges tools like [Claude Code](https://www.anthropic.com/claude-code), [Codex CLI](https://developers.openai.com/codex/cli), and IDE clients such
as [Cursor](https://cursor.com) or the [Claude Dev VS Code extension](https://marketplace.visualstudio.com/items?itemName=Anthropic.claude-vscode). **PAL MCP connects your favorite AI tool
to multiple AI models** for enhanced code analysis, problem-solving, and collaborative development.

### True AI Collaboration with Conversation Continuity

PAL supports **conversation threading** so your CLI can **discuss ideas with multiple AI models, exchange reasoning, get second opinions, and even run collaborative debates between models** to help you reach deeper insights and better solutions.

Your CLI always stays in control but gets perspectives from the best AI for each subtask. Context carries forward seamlessly across tools and models, enabling complex workflows like: code reviews with multiple models → automated planning → implementation → pre-commit validation.

> **You're in control.** Your CLI of choice orchestrates the AI team, but you decide the workflow. Craft powerful prompts that bring in additional models exactly when needed.

<details>
<summary><b>Reasons to Use PAL MCP</b></summary>

A typical workflow with Claude Code as an example:

1. **Multi-Model Orchestration** - Coordinate multiple models (Gemini, OpenAI, OpenRouter, local models) to get the best analysis for each task

2. **Context Revival Magic** - Even after Claude's context resets, continue conversations seamlessly by having other models "remind" Claude of the discussion

3. **Guided Workflows** - Enforces systematic investigation phases that prevent rushed analysis and ensure thorough code examination

4. **Extended Context Windows** - Break your orchestrator's limits by delegating to larger-context models (for example via Gemini or OpenRouter models that support larger context windows)

5. **True Conversation Continuity** - Full context flows across tools and models - one reviewer model can carry forward what another reviewer said 10 steps ago

6. **Model-Specific Strengths** - Use fast models for quick checks, strong reasoning models for deep reviews, and local models for privacy

7. **Professional Code Reviews** - Multi-pass analysis with severity levels, actionable feedback, and consensus from multiple AI experts

8. **Smart Debugging Assistant** - Systematic root cause analysis with hypothesis tracking and confidence levels

9. **Automatic Model Selection** - Claude intelligently picks the right model for each subtask (or you can specify)

10. **Vision Capabilities** - Analyze screenshots, diagrams, and visual content with vision-enabled models

11. **Local Model Support** - Run Llama, Mistral, or other models locally for complete privacy and zero API costs

12. **Large prompt handling** - Works around common MCP client size limits by moving oversized prompts to files (e.g., `prompt.txt`) and using continuation-friendly workflows

**The Killer Feature:** When your agent's context resets, ask it to continue the thread with a second model (e.g., an OpenRouter model) to revive the full discussion without re-ingesting everything manually.

#### Example: Multi-Model Code Review Workflow

1. `Perform a codereview using two models (one deep, one fast) and use planner to generate a detailed plan, implement the fixes and do a final precommit check by continuing from the previous codereview`
2. This triggers a [`codereview`](docs/tools/codereview.md) workflow where Claude walks the code, looking for all kinds of issues
3. After multiple passes, collects relevant code and makes note of issues along the way
4. Maintains a `confidence` level between `exploring`, `low`, `medium`, `high` and `certain` to track how confidently it's been able to find and identify issues
5. Generates a detailed list of critical -> low issues
6. Shares the relevant files, findings, etc. with a second model (for example via OpenRouter: `moonshotai/kimi-k2-thinking`) to perform a deep dive for a second [`codereview`](docs/tools/codereview.md)
7. Comes back with a response and can then repeat with another reviewer model (for example via OpenRouter: `z-ai/glm-4.7`), adding discoveries as needed
8. When done, Claude takes in all the feedback and combines a single list of all critical -> low issues, including good patterns in your code. The final list includes new findings or revisions in case Claude misunderstood or missed something crucial and one of the other models pointed this out
9. It then uses the [`planner`](docs/tools/planner.md) workflow to break the work down into simpler steps if a major refactor is required
10. Claude then performs the actual work of fixing highlighted issues
11. When done, Claude returns to Gemini Pro for a [`precommit`](docs/tools/precommit.md) review

All within a single conversation thread! The final reviewer in step 11 _knows_ what was recommended by the earlier reviewer in step 7! Taking that context
and review into consideration to aid with its final pre-commit review.

**Think of it as super-glue for Claude Code.** This MCP isn't magic. It's just **abstraction**.

> **Remember:** Claude stays in full control — but **YOU** call the shots.
> PAL is designed to have Claude engage other models only when needed — and to follow through with meaningful back-and-forth.
> **You're** the one who crafts the powerful prompt that makes Claude bring in other models — or fly solo.
> You're the guide. The prompter. The puppeteer.
> #### You are the AI - **Actually Intelligent**. The orchestrator in control.
</details>

#### Recommended AI Stack

<details>
<summary>For Claude Code Users</summary>

For best results when using [Claude Code](https://claude.ai/code):  

- **Orchestrator model** (your default Claude model) - All agentic work and orchestration
- **OpenRouter reviewer models** - Use advanced OpenRouter models for second opinions (for example: `moonshotai/kimi-k2-thinking`, `z-ai/glm-4.7`)
</details>

<details>
<summary>For Codex Users</summary>

For best results when using [Codex CLI](https://developers.openai.com/codex/cli):  

- **Orchestrator model** (your default Codex model) - All agentic work and orchestration
- **OpenRouter reviewer models** - Use advanced OpenRouter models for second opinions (for example: `moonshotai/kimi-k2-thinking`, `z-ai/glm-4.7`)
</details>

## Fork notice

This repository (`Shelpuk-AI-Technology-Consulting/pally-mcp-server`) is a fork of `BeehiveInnovations/pal-mcp-server`.

Goal of the fork:
- Keep OpenRouter model routing and metadata current (so AI coding tools can reliably access the latest OpenRouter models).
- Provide first-class installation and onboarding for AI coding tools (Codex, Claude Code, Cursor, etc.) so they can use advanced OpenRouter-hosted models for design and code reviews.

Important naming note:
- Repo name: `pally-mcp-server`
- Installed command / package name: `pal-mcp-server` (this is what you run via `uvx ... pal-mcp-server ...`)

All installation instructions below use this fork as the source (`https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server`).

## Quick Start (5 minutes)

**Prerequisites:** Python 3.10+, Git, [uv installed](https://docs.astral.sh/uv/getting-started/installation/)

**1. Get API Keys** (choose one or more):
- **[OpenRouter](https://openrouter.ai/)** - Access multiple models with one API
- **[Gemini](https://makersuite.google.com/app/apikey)** - Google's latest models
- **[OpenAI](https://platform.openai.com/api-keys)** - OpenAI models (example: GPT-4o)
- **[Azure OpenAI](https://learn.microsoft.com/azure/ai-services/openai/)** - Enterprise deployments of OpenAI models hosted in Azure
- **[X.AI](https://console.x.ai/)** - Grok models
- **[DIAL](https://dialx.ai/)** - Vendor-agnostic model access
- **[Ollama](https://ollama.ai/)** - Local models (free)

**2. Install** (choose one):

**Option A: Clone and Automatic Setup** (recommended)
```bash
git clone https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server.git
cd pally-mcp-server

# Note: repo is pally-mcp-server, command is pal-mcp-server

# Handles everything: setup, config, API keys from system environment. 
# Auto-configures Claude Desktop, Claude Code, Gemini CLI, Codex CLI, Qwen CLI
# Enable / disable additional settings in .env
chmod +x run-server.sh
./run-server.sh  
```

Recommended: set your MCP client's tool timeout to `500` seconds for long-running workflows.
- Codex CLI: `tool_timeout_sec = 500.0` in `~/.codex/config.toml`
- Claude Code: `MCP_TOOL_TIMEOUT=500000` (milliseconds)

**Option B: Instant Setup with [uvx](https://docs.astral.sh/uv/getting-started/installation/)**

Run command used by all MCP clients:
```bash
uvx --from git+https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server.git \
  pal-mcp-server start-mcp-server
```

Notes:
- If your MCP client can run `uvx` directly, prefer that (simpler than `bash -c` wrappers).
- Some clients do not expand `~` / `$HOME` in JSON configuration. The JSON example below attempts to discover `uvx` in common locations; if this fails, hardcode the full path to `uvx` in the command/args.

Codex CLI (no file editing) — add a local stdio MCP server:
```bash
codex mcp add pal \
  --env OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  --env GEMINI_API_KEY="$GEMINI_API_KEY" \
  --env OPENAI_API_KEY="$OPENAI_API_KEY" \
  -- uvx --from git+https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server.git \
  pal-mcp-server start-mcp-server
```

Codex CLI (recommended) — set MCP tool timeout to 500 seconds:
```toml
# ~/.codex/config.toml
[mcp_servers.pal] # server name must match `codex mcp add <server-name> ...`
tool_timeout_sec = 500.0 # seconds
```

Codex CLI (config.toml) — add the server manually with `tool_timeout_sec = 500.0`:
```toml
# ~/.codex/config.toml
[mcp_servers.pal]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server.git",
  "pal-mcp-server",
  "start-mcp-server",
]
env_vars = ["OPENROUTER_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]
tool_timeout_sec = 500.0 # seconds
```

Claude Code (no file editing) — add a local stdio MCP server:
```bash
claude mcp add --transport stdio pal \
  --env OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  --env GEMINI_API_KEY="$GEMINI_API_KEY" \
  --env OPENAI_API_KEY="$OPENAI_API_KEY" \
  -- uvx --from git+https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server.git \
  pal-mcp-server start-mcp-server
```

Claude Code (recommended) — set MCP tool timeout to 500 seconds:
```bash
export MCP_TOOL_TIMEOUT=500000 # milliseconds (500 seconds)
```

```json
// Add to ~/.claude/settings.json or .mcp.json
// Don't forget to add your API keys under env
{
  "mcpServers": {
    "pal": {
      "command": "bash",
      "args": ["-c", "for p in $(which uvx 2>/dev/null) $HOME/.local/bin/uvx /opt/homebrew/bin/uvx /usr/local/bin/uvx uvx; do [ -x \"$p\" ] && exec \"$p\" --from git+https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server.git pal-mcp-server start-mcp-server; done; echo 'uvx not found' >&2; exit 1"],
      "env": {
        "OPENROUTER_API_KEY": "your-key-here",
        "GEMINI_API_KEY": "your-key-here",
        "OPENAI_API_KEY": "your-key-here",
        "DISABLED_TOOLS": "analyze,refactor,testgen,secaudit,docgen,tracer",
        "DEFAULT_MODEL": "auto"
      }
    }
  }
}
```

**3. Start Using!**
```
"Use pal to analyze this code for security issues with gemini pro"
"Debug this error with a deep reasoning model and then get a fast model to suggest optimizations"
"Plan the migration strategy with pal, get consensus from multiple models"
"clink with cli_name=\"gemini\" role=\"planner\" to draft a phased rollout plan"
```

👉 **[Complete Setup Guide](docs/getting-started.md)** with detailed installation, configuration for Gemini / Codex / Qwen, and troubleshooting
👉 **[Cursor & VS Code Setup](docs/getting-started.md#ide-clients)** for IDE integration instructions
📺 **[Watch tools in action](#-watch-tools-in-action)** to see real-world examples

## Provider Configuration

PAL activates any provider that has credentials in your `.env`. See `.env.example` for deeper customization.

## Core Tools

> **Note:** Each tool comes with its own multi-step workflow, parameters, and descriptions that consume valuable context window space even when not in use. To optimize performance, some tools are disabled by default. See [Tool Configuration](#tool-configuration) below to enable them.

**Collaboration & Planning** *(Enabled by default)*
- **[`clink`](docs/tools/clink.md)** - Bridge requests to external AI CLIs (Gemini planner, codereviewer, etc.)
- **[`chat`](docs/tools/chat.md)** - Brainstorm ideas, get second opinions, validate approaches. With capable models, generates complete code / implementation
- **[`thinkdeep`](docs/tools/thinkdeep.md)** - Extended reasoning, edge case analysis, alternative perspectives
- **[`planner`](docs/tools/planner.md)** - Break down complex projects into structured, actionable plans
- **[`consensus`](docs/tools/consensus.md)** - Get expert opinions from multiple AI models with stance steering

**Code Analysis & Quality**
- **[`debug`](docs/tools/debug.md)** - Systematic investigation and root cause analysis
- **[`precommit`](docs/tools/precommit.md)** - Validate changes before committing, prevent regressions
- **[`codereview`](docs/tools/codereview.md)** - Professional reviews with severity levels and actionable feedback
- **[`analyze`](docs/tools/analyze.md)** *(disabled by default - [enable](#tool-configuration))* - Understand architecture, patterns, dependencies across entire codebases

**Development Tools** *(Disabled by default - [enable](#tool-configuration))*
- **[`refactor`](docs/tools/refactor.md)** - Intelligent code refactoring with decomposition focus
- **[`testgen`](docs/tools/testgen.md)** - Comprehensive test generation with edge cases
- **[`secaudit`](docs/tools/secaudit.md)** - Security audits with OWASP Top 10 analysis
- **[`docgen`](docs/tools/docgen.md)** - Generate documentation with complexity analysis

**Utilities**
- **[`apilookup`](docs/tools/apilookup.md)** - Forces current-year API/SDK documentation lookups in a sub-process (saves tokens within the current context window), prevents outdated training data responses
- **[`challenge`](docs/tools/challenge.md)** - Prevent "You're absolutely right!" responses with critical analysis
- **[`tracer`](docs/tools/tracer.md)** *(disabled by default - [enable](#tool-configuration))* - Static analysis prompts for call-flow mapping

<details>
<summary><b id="tool-configuration">👉 Tool Configuration</b></summary>

### Default Configuration

To optimize context window usage, only essential tools are enabled by default:

**Enabled by default:**
- `chat`, `thinkdeep`, `planner`, `consensus` - Core collaboration tools
- `codereview`, `precommit`, `debug` - Essential code quality tools
- `apilookup` - Rapid API/SDK information lookup
- `challenge` - Critical thinking utility

**Disabled by default:**
- `analyze`, `refactor`, `testgen`, `secaudit`, `docgen`, `tracer`

### Enabling Additional Tools

To enable additional tools, remove them from the `DISABLED_TOOLS` list:

**Option 1: Edit your .env file**
```bash
# Default configuration (from .env.example)
DISABLED_TOOLS=analyze,refactor,testgen,secaudit,docgen,tracer

# To enable specific tools, remove them from the list
# Example: Enable analyze tool
DISABLED_TOOLS=refactor,testgen,secaudit,docgen,tracer

# To enable ALL tools
DISABLED_TOOLS=
```

**Option 2: Configure in MCP settings**
```json
// In ~/.claude/settings.json or .mcp.json
{
  "mcpServers": {
    "pal": {
      "env": {
        // Tool configuration
        "DISABLED_TOOLS": "refactor,testgen,secaudit,docgen,tracer",
        "DEFAULT_MODEL": "auto",
        "DEFAULT_THINKING_MODE_THINKDEEP": "high",
        
        // API configuration
        "GEMINI_API_KEY": "your-gemini-key",
        "OPENAI_API_KEY": "your-openai-key",
        "OPENROUTER_API_KEY": "your-openrouter-key",
        
        // Logging and performance
        // OpenRouter streaming watchdog: time-to-first-activity (SSE data or ': OPENROUTER PROCESSING')
        "OPENROUTER_PROCESSING_TIMEOUT": "15",
        "LOG_LEVEL": "INFO",
        "CONVERSATION_TIMEOUT_HOURS": "6",
        "MAX_CONVERSATION_TURNS": "50"
      }
    }
  }
}
```

**Option 3: Enable all tools**
```json
// Remove or empty the DISABLED_TOOLS to enable everything
{
  "mcpServers": {
    "pal": {
      "env": {
        "DISABLED_TOOLS": ""
      }
    }
  }
}
```

**Note:**
- Essential tools (`version`, `listmodels`) cannot be disabled
- After changing tool configuration, restart your Claude session for changes to take effect
- Each tool adds to context window usage, so only enable what you need
- `OPENROUTER_PROCESSING_TIMEOUT` (default `15`) is a time-to-first-activity watchdog for OpenRouter streaming calls: if no SSE `data:` chunks and no `: OPENROUTER PROCESSING` keep-alive is observed within this window, the request is aborted to avoid blocking subsequent OpenRouter calls.
- OpenRouter model capabilities are sourced from `conf/openrouter_models.json`, but if you request an OpenRouter model that isn't listed there (in `provider/model` form), PAL will fetch `context_length` and related metadata from OpenRouter's Models API (`GET https://openrouter.ai/api/v1/models`) to avoid defaulting to ~32k context (cached in-memory with a daily refresh; falls back to generic defaults if the API is unavailable).

</details>

## 📺 Watch Tools In Action

<details>
<summary><b>Chat Tool</b> - Collaborative decision making and multi-turn conversations</summary>

**Picking Redis vs Memcached:**

[Chat Redis or Memcached_web.webm](https://github.com/user-attachments/assets/41076cfe-dd49-4dfc-82f5-d7461b34705d)

**Multi-turn conversation with continuation:**

[Chat With Gemini_web.webm](https://github.com/user-attachments/assets/37bd57ca-e8a6-42f7-b5fb-11de271e95db)

</details>

<details>
<summary><b>Consensus Tool</b> - Multi-model debate and decision making</summary>

**Multi-model consensus debate:**

[PAL Consensus Debate](https://github.com/user-attachments/assets/76a23dd5-887a-4382-9cf0-642f5cf6219e)

</details>

<details>
<summary><b>PreCommit Tool</b> - Comprehensive change validation</summary>

**Pre-commit validation workflow:**

<div align="center">
  <img src="https://github.com/user-attachments/assets/584adfa6-d252-49b4-b5b0-0cd6e97fb2c6" width="950">
</div>

</details>

<details>
<summary><b>API Lookup Tool</b> - Current vs outdated API documentation</summary>

**Without PAL - outdated APIs:**

[API without PAL](https://github.com/user-attachments/assets/01a79dc9-ad16-4264-9ce1-76a56c3580ee)

**With PAL - current APIs:**

[API with PAL](https://github.com/user-attachments/assets/5c847326-4b66-41f7-8f30-f380453dce22)

</details>

<details>
<summary><b>Challenge Tool</b> - Critical thinking vs reflexive agreement</summary>

**Without PAL:**

![without_pal@2x](https://github.com/user-attachments/assets/64f3c9fb-7ca9-4876-b687-25e847edfd87)

**With PAL:**

![with_pal@2x](https://github.com/user-attachments/assets/9d72f444-ba53-4ab1-83e5-250062c6ee70)

</details>

## Key Features

**AI Orchestration**
- **Auto model selection** - Claude picks the right AI for each task
- **Multi-model workflows** - Chain different models in single conversations
- **Conversation continuity** - Context preserved across tools and models
- **[Context revival](docs/context-revival.md)** - Continue conversations even after context resets

**Model Support**
- **Multiple providers** - Gemini, OpenAI, Azure, X.AI, OpenRouter, DIAL, Ollama
- **Latest models** - Models via OpenRouter, Gemini, OpenAI, Grok, and local Llama
- **[Thinking modes](docs/advanced-usage.md#thinking-modes)** - Control reasoning depth vs cost
- **Vision support** - Analyze images, diagrams, screenshots

**Developer Experience**
- **Guided workflows** - Systematic investigation prevents rushed analysis
- **Smart file handling** - Auto-expand directories, manage token limits
- **Web search integration** - Access current documentation and best practices
- **[Large prompt support](docs/advanced-usage.md#working-with-large-prompts)** - Handle large prompts in a client-friendly way

## Example Workflows

**Multi-model Code Review:**
```
"Perform a codereview using two models, then use planner to create a fix strategy"
```
→ Orchestrator reviews code systematically → Consults reviewer model(s) → Creates unified action plan

**Collaborative Debugging:**
```
"Debug this race condition with max thinking mode, then validate the fix with precommit"
```
→ Deep investigation → Expert analysis → Solution implementation → Pre-commit validation

**Architecture Planning:**
```
"Plan our microservices migration, get consensus from two models on the approach"
```
→ Structured planning → Multiple expert opinions → Consensus building → Implementation roadmap

👉 **[Advanced Usage Guide](docs/advanced-usage.md)** for complex workflows, model configuration, and power-user features

## Quick Links

**📖 Documentation**
- [Docs Overview](docs/index.md) - High-level map of major guides
- [Getting Started](docs/getting-started.md) - Complete setup guide
- [Tools Reference](docs/tools/) - All tools with examples
- [Advanced Usage](docs/advanced-usage.md) - Power user features
- [Configuration](docs/configuration.md) - Environment variables, restrictions
- [Adding Providers](docs/adding_providers.md) - Provider-specific setup (OpenAI, Azure, custom gateways)
- [Model Ranking Guide](docs/model_ranking.md) - How intelligence scores drive auto-mode suggestions

**🔧 Setup & Support**
- [WSL Setup](docs/wsl-setup.md) - Windows users
- [Troubleshooting](docs/troubleshooting.md) - Common issues
- [Contributing](docs/contributions.md) - Code standards, PR process

## License

Apache 2.0 License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with the power of **Multi-Model AI** collaboration 🤝
- **A**ctual **I**ntelligence by real Humans
- [MCP (Model Context Protocol)](https://modelcontextprotocol.com)
- [Codex CLI](https://developers.openai.com/codex/cli)
- [Claude Code](https://claude.ai/code)
- [Gemini](https://ai.google.dev/)
- [OpenAI](https://openai.com/)
- [Azure OpenAI](https://learn.microsoft.com/azure/ai-services/openai/)

### Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Shelpuk-AI-Technology-Consulting/pally-mcp-server&type=Date)](https://www.star-history.com/#Shelpuk-AI-Technology-Consulting/pally-mcp-server&Date)
