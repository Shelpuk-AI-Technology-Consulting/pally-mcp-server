# Repository Guidelines

See `requirements.txt` and `requirements-dev.txt`

Also read CLAUDE.md and CLAUDE.local.md if available.

## Project Structure & Module Organization
Pally MCP Server centers on `server.py`, which exposes MCP entrypoints and coordinates multi-model workflows. 
Feature-specific tools live in `tools/`, provider integrations in `providers/`, and shared helpers in `utils/`. 
Prompt and system context assets stay in `systemprompts/`, while configuration templates and automation scripts live under `conf/`, `scripts/`, and `docker/`. 
Unit tests sit in `tests/`; simulator-driven scenarios and log utilities are in `simulator_tests/` with the `communication_simulator_test.py` harness. 
Authoritative documentation and samples live in `docs/`, and runtime diagnostics are rotated in `logs/`.

## Implementation Guidelines and Best Practices

When dealing with implementing new feature or fixing a bug, you always follow this approach step by step:
1. Investigate existing application state, execution results and user input. 
2. Write /REQUIREMENTS.md file before you start work on a new task. If it exists, rewrite it.
- First, write the "As Is" section explaining the current state of the system. 
-  Then, write the "To Be" section, describing in detail how the system should behave after the necessary changes. 
-  Then write the "Requirements" section describing functional requirements.
-  Use Kindly Web Search to get up-to-date documentation and information on packages, functions, APIs, and other technologies you plan to use.
-  Then go over the  "Requirements" section once again, and for every functional requirement, you add acceptance criteria.
-  Then you add the "Testing Plan" section. You list there the testing plan for this new feature, following the test-driven development (TDD) best practices.
-  Write the "Implementation Plan" section. Now, this is super important! In the "Implementation Plan", you always describe the smallest possible changes that need to be implemented one after the other to implement the requirements. For every change, you describe how to test it.
3. Ask moonshotai/kimi-k2-thinking and z-ai/glm-4.7 through Pally MCP server tools to review your REQUIREMENTS.md. Explain to them the requirements. Specifically, ask them to spot any issues, bugs, inconsistencies, failure modes, and corner cases. Review their feedback and consider whether it is worth taking into account. Then, if necessary, update REQUIREMENTS.md to incorporate Gemini and Claude feedback.
4. Then proceed to the implementation. You follow the "Implementation Plan" and implement one small change at a time, testing each change with unit tests, integration tests, and smoke tests to ensure they work.
5. Ask moonshotai/kimi-k2-thinking and z-ai/glm-4.7 through the Pally MCP server tools to review your code. Ask them to spot potential bugs, issues, corner cases, failure modes, and potential improvements. 
6. Review kimi-k2-thinking and glm-4.7 feedback. Implement the suggestions that are worthy of consideration.

## LLM Access

- Whenever the user or a documentation refers to "Kimi" it means moonshotai/kimi-k2-thinking accessible with Pally MCP Server.
- Whenever the user or a documentation refers to "GLM" it means z-ai/glm-4.7 accessible with Pally MCP Server.
- You can access these models freely and often to ask for reviews and feedback. Just never share API keys with them. 

## Build, Test, and Development Commands
- `source .pal_venv/bin/activate` – activate the managed Python environment.
- `./run-server.sh` – install dependencies, refresh `.env`, and launch the MCP server locally.
- `./code_quality_checks.sh` – run Ruff autofix, Black, isort, and the default pytest suite.
- `python communication_simulator_test.py --quick` – smoke-test orchestration across tools and providers.
- `./run_integration_tests.sh [--with-simulator]` – exercise provider-dependent flows against remote or Ollama models.

Run code quality checks:
```bash
.pal_venv/bin/activate && ./code_quality_checks.sh
```

For example, this is how we run an individual / all tests:

```bash
.pal_venv/bin/activate && pytest tests/test_auto_mode_model_listing.py -q
.pal_venv/bin/activate && pytest -q
```

## Coding Style & Naming Conventions
Target Python 3.9+ with Black and isort using a 120-character line limit; Ruff enforces pycodestyle, pyflakes, bugbear, comprehension, and pyupgrade rules. Prefer explicit type hints, snake_case modules, and imperative commit-time docstrings. Extend workflows by defining hook or abstract methods instead of checking `hasattr()`/`getattr()`—inheritance-backed contracts keep behavior discoverable and testable.

## Testing Guidelines
Mirror production modules inside `tests/` and name tests `test_<behavior>` or `Test<Feature>` classes. Run `python -m pytest tests/ -v -m "not integration"` before every commit, adding `--cov=. --cov-report=html` for coverage-sensitive changes. Use `python communication_simulator_test.py --verbose` or `--individual <case>` to validate cross-agent flows, and reserve `./run_integration_tests.sh` for provider or transport modifications. Capture relevant excerpts from `logs/mcp_server.log` or `logs/mcp_activity.log` when documenting failures.

## Commit & Pull Request Guidelines
Follow Conventional Commits: `type(scope): summary`, where `type` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, or `chore`. Keep commits focused, referencing issues or simulator cases when helpful. Pull requests should outline intent, list validation commands executed, flag configuration or tool toggles, and attach screenshots or log snippets when user-visible behavior changes.

## GitHub CLI Commands
The GitHub CLI (`gh`) streamlines issue and PR management directly from the terminal.

### Viewing Issues
```bash
# View issue details in current repository
gh issue view <issue-number>

# View issue from specific repository
gh issue view <issue-number> --repo owner/repo-name

# View issue with all comments
gh issue view <issue-number> --comments

# Get issue data as JSON for scripting
gh issue view <issue-number> --json title,body,author,state,labels,comments

# Open issue in web browser
gh issue view <issue-number> --web
```

### Managing Issues
```bash
# List all open issues
gh issue list

# List issues with filters
gh issue list --label bug --state open

# Create a new issue
gh issue create --title "Issue title" --body "Description"

# Close an issue
gh issue close <issue-number>

# Reopen an issue
gh issue reopen <issue-number>
```

### Pull Request Operations
```bash
# View PR details
gh pr view <pr-number>

# List pull requests
gh pr list

# Create a PR from current branch
gh pr create --title "PR title" --body "Description"

# Check out a PR locally
gh pr checkout <pr-number>

# Merge a PR
gh pr merge <pr-number>
```

Install GitHub CLI: `brew install gh` (macOS) or visit https://cli.github.com for other platforms.

## Security & Configuration Tips
Store API keys and provider URLs in `.env` or your MCP client config; never commit secrets or generated log artifacts. Use `run-server.sh` to regenerate environments and verify connectivity after dependency changes. When adding providers or tools, sanitize prompts and responses, document required environment variables in `docs/`, and update `claude_config_example.json` if new capabilities ship by default.
