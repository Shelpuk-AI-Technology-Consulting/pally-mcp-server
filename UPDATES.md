# Updates Log

This file tracks notable behavior, reliability, and observability changes introduced to PAL MCP Server.

## 2026-01-10 — OpenRouter timeout RCA + mitigations

### Root-cause findings (summary)
- Provider calls to OpenRouter-backed models were executed synchronously inside async tool execution paths, which could block the asyncio event loop and contribute to MCP client timeouts under load.
- Directory/file embedding work could be expensive (especially when a directory is provided and expanded into many files), and redundant directory expansion increased wall time before the provider call.
- OpenRouter calls are executed non-streaming (`stream=False`), so long completions can “feel fast” in the OpenRouter UI while still taking long enough to time out in a non-streaming MCP tool call.

### Mitigations implemented
- Run sync provider calls off the event loop using a thread wrapper:
  - Added `BaseTool._generate_content_with_provider_lock(...)` to execute `provider.generate_content(...)` via `loop.run_in_executor(...)` using a short-lived `ThreadPoolExecutor` per call (avoids cross-event-loop hangs in pytest and keeps tool execution non-blocking).
  - Optional wall-time cap via `PAL_MODEL_CALL_TIMEOUT_SEC` (best-effort; does not forcibly terminate the underlying thread/HTTP request).
- Serialize provider calls per provider instance:
  - Added per-provider call lock in `providers/base.py` (`ModelProvider.get_call_lock()`).
- Eliminate redundant directory traversal and report what was actually embedded:
  - Added `utils/file_utils.read_files_with_manifest(...) -> (content, embedded_files)` so expansion + reading happens once and callers can track the exact embedded file list.
  - Updated tool file embedding paths to use the manifest result instead of expanding directories separately.
  - Updated workflow expert-analysis embedding to use `read_files_with_manifest` to avoid an extra `expand_paths(...)` pass.
- Add timing observability to outputs:
  - Tools now attach `metadata.timings` with `file_prep_s`, `model_lock_wait_s`, `model_call_s`, `total_s` to distinguish “slow file prep” vs “lock contention” vs “slow upstream call”.
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

### Repo-wide metadata + onboarding scripts
- Updated additional install/config references across the repo to point to the fork:
  - `docs/getting-started.md` / `docs/docker-deployment.md`
  - `run-server.sh` / `run-server.ps1` / `code_quality_checks.ps1` / `run_integration_tests.ps1`
  - `Dockerfile` OCI labels
  - `SECURITY.md` advisory link
  - `conf/*.json` documentation URLs
  - `tools/version.py` remote version check URL
  - `providers/openrouter.py` default `OPENROUTER_REFERER` fallback

## 2026-01-11 — Intelligent OpenRouter health monitoring (safe long tool timeouts)

- Added “time-to-first-activity” OpenRouter health monitoring via `OPENROUTER_PROCESSING_TIMEOUT`:
  - If no SSE `data:` chunk and no `: OPENROUTER PROCESSING` keep-alive is observed within the timeout window (default: `15s`), the request is aborted.
  - If activity is observed, the request is treated as alive and allowed to continue (this is *not* an inactivity timeout).
- This makes it safe to set a high MCP client tool timeout (e.g. `500s`) for long-running workflows:
  - Dead/stalled OpenRouter calls fail fast and don’t occupy the per-provider call lock/queue for the full client timeout.
  - Healthy-but-slow calls are allowed to run to completion without triggering provider rotation / fail-fast heuristics.

## 2026-01-11 — Dynamic OpenRouter capability discovery (fix unknown context windows)

- Improved OpenRouter model capability handling for models not listed in `conf/openrouter_models.json`:
  - For unknown `provider/model` names, Pally queries `GET https://openrouter.ai/api/v1/models` (cached in-memory with daily refresh) to pull real `context_length` and `top_provider.max_completion_tokens`.
  - Derived flags (best-effort) from API metadata: `architecture.input_modalities` (vision) and `supported_parameters` (e.g., tools / json format / temperature).
  - If the API is unavailable or the model can’t be found, Pally falls back to the previous generic OpenRouter defaults (~32k) instead of failing.
- OpenRouter models now default `allow_code_generation=true` unless explicitly set otherwise in config.

## 2026-01-11 — Review-optimized token budgeting & context selection

- Added tool-aware token allocation profiles (files/history/response/prompt) for review workloads:
  - `codereview` defaults to `code_review`
  - `analyze` defaults to `code_review`, and switches to `system_design_review` for `analysis_type=architecture`
- Added adaptive response reservation for review tools to avoid wasting large portions of the context window on unused output tokens.
- Implemented deterministic file relevance ranking (explicit mentions + type weighting + recency) and best-effort Python local import dependency closure (depth=1) for review contexts.
- Added structure-preserving large file reduction (`[REDUCED]`) instead of skipping files when a full file doesn’t fit in the remaining budget.
- Added deterministic conversation history compression with a summary section for omitted turns; configurable via `PALLY_CONVERSATION_VERBATIM_TURNS` (default `6`).
