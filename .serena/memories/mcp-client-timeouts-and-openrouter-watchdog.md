# MCP client tool timeouts + OpenRouter "time-to-first-activity" watchdog (2026-01-11)

## What the original failure was
- Observed failures looked like: `timed out awaiting tools/call after 60s` / `deadline has elapsed` during `pally/chat` calls via OpenRouter.
- Root cause: the MCP *client* (e.g., Codex CLI default `tool_timeout_sec=60`) can time out before OpenRouter returns a full non-streaming response, making "slow start" indistinguishable from "dead".

## The implemented mitigation (server-side)
- New env var: `OPENROUTER_PROCESSING_TIMEOUT` (default: `15` seconds).
- Semantics: **time-to-first-activity only** for OpenRouter streaming calls.
  - If Pally sees no SSE activity within the window (either an SSE `data:` line or a comment keep-alive like `: OPENROUTER PROCESSING`), it aborts the request so it doesn’t block the per-provider call lock/queue.
  - If activity is observed, the call is treated as alive/processing and is allowed to run to completion (this is *not* an inactivity timeout).

## Why this enables long tool timeouts safely
- With a long MCP tool timeout (e.g. `500s`), you can support long-running workflows.
- The watchdog prevents wasting the full client timeout on dead OpenRouter requests (they fail fast and release the provider lock).

## Client-side configuration guidance (docs-backed)
- **Codex CLI**
  - Config file: `~/.codex/config.toml`.
  - Per-server timeout key: `tool_timeout_sec` (seconds; default is 60).
  - Example:
    - `[mcp_servers.<server-name>]` (server name matches `codex mcp add <server-name> ...`)
    - `tool_timeout_sec = 500.0`
- **Claude Code**
  - Env var: `MCP_TOOL_TIMEOUT` (milliseconds).
  - Example: `MCP_TOOL_TIMEOUT=500000` for 500 seconds.

## Naming gotchas
- Repo name: `pally-mcp-server`, but the installed command is `pal-mcp-server`.
- Server name used across repo scripts/docs is typically `pal` (Codex config table becomes `[mcp_servers.pal]`).

## Codex env forwarding nuance
- Codex MCP supports:
  - `[mcp_servers.<name>.env]` for explicit key/value env pairs.
  - `env_vars = ["OPENROUTER_API_KEY", ...]` as a whitelist to forward env vars that are already present in the Codex process environment.
