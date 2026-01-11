# OpenRouter integration in Pally MCP Server

This note documents how the Pally MCP server routes model calls through OpenRouter (and how that interacts with model selection, allowlists, and MCP tool execution).

## High-level architecture (where OpenRouter fits)

- `server.py`
  - Owns MCP handlers (`handle_list_tools`, `handle_call_tool`, etc.).
  - Performs **early model resolution at the MCP boundary** (before tool code executes).
  - Registers providers based on env var presence (`configure_providers`).

- `providers/`
  - Unified provider abstraction via `providers/base.py:ModelProvider`.
  - OpenRouter support is a **provider implementation** (`providers/openrouter.py:OpenRouterProvider`) built on a shared OpenAI-compatible transport (`providers/openai_compatible.py:OpenAICompatibleProvider`).
  - Provider instantiation, caching, priority routing: `providers/registry.py:ModelProviderRegistry`.

- `tools/`
  - “Simple” tools inherit `tools/simple/base.py:SimpleTool` → `tools/shared/base_tool.py:BaseTool`.
  - Workflow tools mix in `tools/workflow/workflow_mixin.py:BaseWorkflowMixin`.
  - Tools rely on `_model_context` and `_resolved_model_name` injected by `server.py` to avoid re-resolving models.

- `utils/`
  - `utils/model_context.py:ModelContext` lazily resolves the provider+capabilities and computes token budgets.
  - `utils/model_restrictions.py:ModelRestrictionService` enforces `*_ALLOWED_MODELS` allowlists (including OpenRouter).

## Provider registration and priority

### Registration (runtime)
`server.py:configure_providers` checks env vars and registers providers in priority order:

1) Native providers (when their keys/config are present)
- Gemini: `GEMINI_API_KEY`
- OpenAI: `OPENAI_API_KEY`
- Azure OpenAI: `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` (+ `conf/azure_models.json`)
- X.AI: `XAI_API_KEY`
- DIAL: `DIAL_API_KEY`

2) Custom endpoints
- `CUSTOM_API_URL` (+ optional `CUSTOM_API_KEY`)

3) OpenRouter (catch-all)
- `OPENROUTER_API_KEY`

### Priority routing (model → provider)
`providers/registry.py:ModelProviderRegistry.get_provider_for_model` iterates:

`GOOGLE → OPENAI → AZURE → XAI → DIAL → CUSTOM → OPENROUTER`

and returns the first provider for which `provider.validate_model_name(model_name)` succeeds.

Implication: OpenRouter is intentionally last so it only handles models not claimed by “native” providers or a configured custom endpoint.

## MCP boundary: early model resolution and model:option parsing

### Early model resolution
In `server.py` (within `handle_call_tool`):

- Determine requested model:
  - `model_name = arguments.get("model") or DEFAULT_MODEL`
- Parse model option:
  - `model_name, model_option = parse_model_option(model_name)`
- Handle `auto`:
  - If `model_name.lower() == "auto"`: resolve to `ModelProviderRegistry.get_preferred_fallback_model(tool_category)` and overwrite `arguments["model"]`.
- Validate that a provider exists for the requested model:
  - `provider = ModelProviderRegistry.get_provider_for_model(model_name)`
- Construct and inject model context:
  - `model_context = ModelContext(model_name, model_option)`
  - `arguments["_model_context"] = model_context`
  - `arguments["_resolved_model_name"] = model_name`

Tools later use this injected context rather than calling the registry again.

### `parse_model_option` (OpenRouter-specific behavior)
`server.py:parse_model_option` has an OpenRouter special-case:

- If the string contains `/` and has exactly one `:` (e.g. `openai/gpt-4o-mini:free`), then the suffix is inspected.
- If the suffix is one of: `free`, `beta`, `preview`, the function returns `(model_string, None)`.

This preserves OpenRouter’s pricing/tier suffixes as part of the model name.

## OpenRouter provider implementation

### Provider class
- `providers/openrouter.py:OpenRouterProvider`
  - Inherits `providers/openai_compatible.py:OpenAICompatibleProvider`.
  - Fixed endpoint: `base_url = "https://openrouter.ai/api/v1"`.
  - Adds OpenRouter-required headers (passed to the OpenAI SDK via `default_headers`):
    - `HTTP-Referer`: from `OPENROUTER_REFERER` (defaults to repo URL)
    - `X-Title`: from `OPENROUTER_TITLE` (defaults to `Pally MCP Server`)

### Model registry + aliases
- `providers/registries/openrouter.py:OpenRouterModelRegistry`
  - Backed by `conf/openrouter_models.json`.
  - Can be overridden with `OPENROUTER_MODELS_CONFIG_PATH`.
  - Registry base loader (`providers/registries/base.py:CustomModelRegistryBase`):
    - Tries packaged `conf/…` via `importlib.resources` if available.
    - Falls back to repo `conf/openrouter_models.json`, then `cwd/conf/openrouter_models.json`.
  - Maintains:
    - `model_map`: canonical model name → `ModelCapabilities`
    - `alias_map`: lowercase alias/canonical name → canonical model name

OpenRouterProvider behaviors:

- `_resolve_model_name(model_name)`
  - Resolves case-insensitive aliases via `OpenRouterModelRegistry.resolve` and caches results.

- `list_models(respect_restrictions=True, include_aliases=True, …)`
  - Iterates registry models.
  - Applies model restrictions (`utils.model_restrictions`) **including alias-aware checks**.
  - When restrictions are active, it intentionally **does not return aliases** (only canonical names) to reduce ambiguity.

### Generic fallback for “unlisted” OpenRouter models
`OpenRouterProvider._lookup_capabilities`:

- If the model is not found in the registry but looks like `provider/model` (contains `/`), it returns a **generic** `ModelCapabilities` object (currently hard-coded defaults like a 32K context window).
- If the model is not found and has no `/`, it is rejected (requires explicit configuration in `conf/openrouter_models.json`).

Implications:
- You can call OpenRouter with “full names” not present in `conf/openrouter_models.json` and still pass validation.
- Those models will not show up in `listmodels` output (because listing is registry-driven).

## Transport: how OpenRouter API calls are made

### OpenAI SDK with OpenRouter base URL
`providers/openai_compatible.py:OpenAICompatibleProvider.client`:

- Creates a custom `httpx.Client` and passes it into the OpenAI Python SDK (`OpenAI(**client_kwargs)`).
- Sets `base_url` (OpenRouter provider sets it to `https://openrouter.ai/api/v1`).
- Applies `DEFAULT_HEADERS` (OpenRouter adds `HTTP-Referer` and `X-Title`).
- Suppresses proxy env vars (`HTTP_PROXY`, `HTTPS_PROXY`, etc.) to avoid proxy-related conflicts.

### Timeouts
`providers/openai_compatible.py:_configure_timeouts`:

- Uses extended timeouts by default, especially for non-default endpoints.
- Allows overrides via env vars (applies to all OpenAI-compatible providers, including OpenRouter):
  - `CUSTOM_CONNECT_TIMEOUT`, `CUSTOM_READ_TIMEOUT`, `CUSTOM_WRITE_TIMEOUT`, `CUSTOM_POOL_TIMEOUT`

### Chat Completions endpoint
`providers/openai_compatible.py:generate_content`:

- Builds Chat Completions payload:
  - `model`: resolved model name
  - `messages`: system + user
  - `stream`: always `False` (MCP does not stream; also avoids O3 access issues per code comment)
- Parameter gating:
  - If the model’s `supports_temperature` is false (reasoning models), the provider omits `temperature` and `max_tokens`.
  - Other sampling params are conditionally omitted for reasoning models.
- Retries:
  - Uses `_run_with_retries` with progressive delays `[1, 3, 5, 8]`.

### Responses endpoint (reasoning models)
`providers/openai_compatible.py:_generate_with_responses_endpoint`:

- Converts messages to the `/responses` format.
- Adds `reasoning: {effort: <default_reasoning_effort|"medium">}`.
- IMPORTANT OpenRouter behavior:
  - Omits `store=True` for OpenRouter because OpenRouter rejects `store:true` on `/responses` (comment references Issue #348).
  - For other providers, `store=True` is included.

## Acl/allowlists and restrictions (OpenRouter)

There are two layers that can restrict OpenRouter models:

1) Global restriction service: `utils/model_restrictions.py:ModelRestrictionService`
- Env var: `OPENROUTER_ALLOWED_MODELS` (comma-separated, lowercased)
- Enforced via `ModelProvider._ensure_model_allowed` during `get_capabilities` and by OpenRouter-specific listing logic.
- Performs alias-aware matching by asking the provider to `_resolve_model_name(allowed_entry)` and caching canonical names.

2) Provider-level allowlist parsing: `providers/openai_compatible.py:_parse_allowed_models`
- Uses `env_var = f"{provider_type.value.upper()}_ALLOWED_MODELS"`.
- For OpenRouter this is also `OPENROUTER_ALLOWED_MODELS`.
- Enforced in `OpenAICompatibleProvider._ensure_model_allowed`.

NOTE: The registry (`providers/registry.py:get_available_models`) explicitly avoids “double filtering” when `respect_restrictions=True` (commented as Fixed Issue #98). OpenRouter’s own `list_models` also contains alias-aware restriction handling.

## Tool metadata: how `provider_used=openrouter` is produced

### Simple tools
- Simple tools ultimately call `BaseTool._generate_content_with_provider_lock`, which invokes `provider.generate_content(...)` and returns a `ModelResponse`.
- `tools/simple/base.py:SimpleTool._parse_response` injects metadata:
  - `model_used`: resolved model name
  - `provider_used`: `provider.get_provider_type().value` (OpenRouter → `openrouter`)

### Workflow tools
- `tools/workflow/workflow_mixin.py:BaseWorkflowMixin._add_workflow_metadata` reads `_model_context` + `_resolved_model_name` from arguments and writes:
  - `model_used`
  - `provider_used` (OpenRouter → `openrouter`)

## Operational / debugging notes

- Provider instance caching:
  - Providers are cached inside `ModelProviderRegistry._initialized_providers`.
- Timeout mitigation:
  - `tools/shared/base_tool.py:BaseTool._generate_content_with_provider_lock` rotates the cached provider instance on timeout via `ModelProviderRegistry.rotate_provider(provider_type)` to avoid stuck locks held by timed-out worker threads.

## Files most relevant to OpenRouter behavior

- `server.py` (model parsing, early resolution, provider registration)
- `providers/openrouter.py` (headers, registry + alias handling, generic capability fallback)
- `providers/openai_compatible.py` (OpenAI SDK + httpx plumbing, request construction, responses endpoint quirks)
- `providers/registry.py` (provider priority, caching, routing)
- `providers/registries/openrouter.py` + `providers/registries/base.py` (OpenRouter model manifest loader + alias maps)
- `conf/openrouter_models.json` (model metadata and aliases exposed via OpenRouter)
- `utils/model_restrictions.py` (OPENROUTER_ALLOWED_MODELS policy)
- `utils/model_context.py` (provider+capabilities lazy resolution, token budget)
- `tools/simple/base.py` and `tools/workflow/workflow_mixin.py` (metadata: provider_used/model_used)

## Potential caveat: `provider` field overrides in OpenRouter registry

`providers/registries/openrouter.py:OpenRouterModelRegistry._finalise_entry` tries to interpret an entry-level `provider` field, but `providers/registries/base.py:CustomModelRegistryBase._convert_entry` overwrites `capability.provider` to the registry default provider (`ProviderType.OPENROUTER`).

In the current codebase, `conf/openrouter_models.json` does not include a `provider` field, so this does not affect OpenRouter in practice. If you ever want to use `openrouter_models.json` as a multi-provider registry (e.g., embed OpenAI-native capabilities), confirm whether this overwrite is intended or adjust the registry behavior accordingly.
