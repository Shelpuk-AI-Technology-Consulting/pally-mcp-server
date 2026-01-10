# Updates Log

This file tracks notable behavior, reliability, and observability changes introduced to PAL MCP Server.

## 2026-01-10 — OpenRouter timeout RCA + mitigations

### Root-cause findings (summary)
- Provider calls to OpenRouter-backed models were executed synchronously inside async tool execution paths, which could block the asyncio event loop and contribute to MCP client timeouts under load.
- Directory/file embedding work could be expensive (especially when a directory is provided and expanded into many files), and redundant directory expansion increased wall time before the provider call.
- OpenRouter calls are executed non-streaming (`stream=False`), so long completions can “feel fast” in the OpenRouter UI while still taking long enough to time out in a non-streaming MCP tool call.

### Mitigations implemented
- Run sync provider calls off the event loop using a thread wrapper:
  - Added `BaseTool._generate_content_with_provider_lock(...)` to execute `provider.generate_content(...)` via `asyncio.to_thread`.
  - Optional wall-time cap via `PAL_MODEL_CALL_TIMEOUT_SEC` (best-effort; does not forcibly terminate the underlying thread/HTTP request).
- Serialize provider calls per provider instance:
  - Added per-provider call lock in `providers/base.py` (`ModelProvider.get_call_lock()`).
- Eliminate redundant directory traversal and report what was actually embedded:
  - Added `utils/file_utils.read_files_with_manifest(...) -> (content, embedded_files)` so expansion + reading happens once and callers can track the exact embedded file list.
  - Updated tool file embedding paths to use the manifest result instead of expanding directories separately.
  - Updated workflow expert-analysis embedding to use `read_files_with_manifest` to avoid an extra `expand_paths(...)` pass.
- Add timing observability to outputs:
  - Tools now attach `metadata.timings` with `file_prep_s`, `model_call_s`, `total_s` to distinguish “slow file prep” from “slow upstream call”.
- Add default output cap knob:
  - Added `PAL_DEFAULT_MAX_OUTPUT_TOKENS` to set a default `max_output_tokens` when a tool doesn’t explicitly specify one (helps reduce long non-streaming waits).

### Tests
- Added `tests/test_file_utils_manifest.py` for manifest + timeout enforcement coverage.
- Updated workflow and directory-expansion tests to reflect “embedded files manifest” semantics and workflow embedding behavior.

### Files touched (high-level)
- `providers/base.py`
- `utils/file_utils.py`
- `tools/shared/base_tool.py`
- `tools/simple/base.py`
- `tools/workflow/workflow_mixin.py`
- `tools/consensus.py`
- `tests/test_file_utils_manifest.py`
- `tests/test_directory_expansion_tracking.py`
- `tests/test_workflow_file_embedding.py`

## 2026-01-10 — `uvx` install + client CLI onboarding

### CLI entrypoint
- Added a stable `start-mcp-server` subcommand to the `pal-mcp-server` console script.
- Preserved backward compatibility: `pal-mcp-server` (no args) still starts the stdio MCP server.
- Added `pal-mcp-server --version` for debugging `uvx` installs.

### Documentation
- Updated `README.md` with:
  - a canonical `uvx --from git+... pal-mcp-server start-mcp-server` command
  - copy/paste onboarding commands for Codex CLI (`codex mcp add ...`) and Claude Code (`claude mcp add ...`)

### Tests
- Added `tests/test_cli_entrypoint.py` to cover `--version` and `start-mcp-server` parsing.

## 2026-01-10 — Fork source of truth for installation

### Documentation
- Updated `README.md` to declare this repo as a fork of `BeehiveInnovations/pal-mcp-server` and state the fork’s focus (OpenRouter routing + AI coding tool onboarding).
- Updated all `uvx --from git+...` and clone instructions to use `Shelpuk-AI-Technology-Consulting/pally-mcp-server` as the install source.
