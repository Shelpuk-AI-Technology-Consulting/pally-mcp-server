"""OpenRouter provider implementation."""

import logging
import threading
import time
from typing import Any

from utils.env import get_env

import httpx

from .openai_compatible import OpenAICompatibleProvider
from .registries.openrouter import OpenRouterModelRegistry
from .shared import (
    ModelCapabilities,
    ProviderType,
    RangeTemperatureConstraint,
)


class OpenRouterProvider(OpenAICompatibleProvider):
    """Client for OpenRouter's multi-model aggregation service.

    Role
        Surface OpenRouter’s dynamic catalogue through the same interface as
        native providers so tools can reference OpenRouter models and aliases
        without special cases.

    Characteristics
        * Pulls live model definitions from :class:`OpenRouterModelRegistry`
          (aliases, provider-specific metadata, capability hints)
        * Applies alias-aware restriction checks before exposing models to the
          registry or tooling
        * Reuses :class:`OpenAICompatibleProvider` infrastructure for request
          execution so OpenRouter endpoints behave like standard OpenAI-style
          APIs.
    """

    FRIENDLY_NAME = "OpenRouter"

    # Custom headers required by OpenRouter
    DEFAULT_HEADERS = {
        "HTTP-Referer": get_env(
            "OPENROUTER_REFERER", "https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server"
        )
        or "https://github.com/Shelpuk-AI-Technology-Consulting/pally-mcp-server",
        "X-Title": get_env("OPENROUTER_TITLE", "PAL MCP Server") or "PAL MCP Server",
    }

    # Model registry for managing configurations and aliases
    _registry: OpenRouterModelRegistry | None = None
    _models_api_lock = threading.Lock()
    _models_api_cache: dict[str, dict[str, Any]] | None = None
    _models_api_last_fetch: float | None = None
    _models_api_last_failure: float | None = None

    _MODELS_API_URL = "https://openrouter.ai/api/v1/models"
    _MODELS_API_TTL_SEC = 60 * 60 * 24  # daily refresh
    _MODELS_API_TIMEOUT_SEC = 5.0
    _MODELS_API_FAILURE_COOLDOWN_SEC = 60.0

    def __init__(self, api_key: str, **kwargs):
        """Initialize OpenRouter provider.

        Args:
            api_key: OpenRouter API key
            **kwargs: Additional configuration
        """
        base_url = "https://openrouter.ai/api/v1"
        self._alias_cache: dict[str, str] = {}
        super().__init__(api_key, base_url=base_url, **kwargs)

        # Initialize model registry
        if OpenRouterProvider._registry is None:
            OpenRouterProvider._registry = OpenRouterModelRegistry()
            # Log loaded models and aliases only on first load
            models = self._registry.list_models()
            aliases = self._registry.list_aliases()
            logging.info(f"OpenRouter loaded {len(models)} models with {len(aliases)} aliases")

    def _fetch_models_api(self) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}", **self.DEFAULT_HEADERS}
        with httpx.Client(timeout=self._MODELS_API_TIMEOUT_SEC) as client:
            response = client.get(self._MODELS_API_URL, headers=headers)
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", [])
        return data if isinstance(data, list) else []

    def _get_models_api_cache(self) -> dict[str, dict[str, Any]]:
        now = time.time()

        with self._models_api_lock:
            cache = self._models_api_cache
            last_fetch = self._models_api_last_fetch

            if cache is not None and last_fetch is not None and (now - last_fetch) < self._MODELS_API_TTL_SEC:
                return cache

            last_failure = self._models_api_last_failure
            if last_failure is not None and (now - last_failure) < self._MODELS_API_FAILURE_COOLDOWN_SEC:
                raise RuntimeError("OpenRouter models API recently failed; cooldown active")

            try:
                models = self._fetch_models_api()
                index: dict[str, dict[str, Any]] = {}
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    model_id = model.get("id")
                    if isinstance(model_id, str) and model_id:
                        index[model_id] = model

                    canonical_slug = model.get("canonical_slug")
                    if isinstance(canonical_slug, str) and canonical_slug and canonical_slug not in index:
                        index[canonical_slug] = model

                self._models_api_cache = index
                self._models_api_last_fetch = now
                self._models_api_last_failure = None
                return index
            except Exception as exc:
                self._models_api_last_failure = now
                raise RuntimeError(f"Failed to fetch OpenRouter models API: {exc}") from exc

    def _lookup_dynamic_model_info(self, model_name: str) -> dict[str, Any] | None:
        try:
            index = self._get_models_api_cache()
        except Exception as exc:
            logging.debug("OpenRouter models API unavailable: %s", exc)
            return None

        hit = index.get(model_name)
        if hit is not None:
            return hit

        if ":" in model_name:
            base = model_name.rsplit(":", 1)[0]
            return index.get(base)

        return None

    def _build_capabilities_from_models_api(self, model_name: str, model_info: dict[str, Any]) -> ModelCapabilities:
        context_window = int(model_info.get("context_length") or 0) or 32_768

        top_provider = model_info.get("top_provider") or {}
        max_completion_tokens = None
        if isinstance(top_provider, dict):
            max_completion_tokens = top_provider.get("max_completion_tokens")
        if isinstance(max_completion_tokens, int):
            max_output_tokens = max_completion_tokens
        else:
            max_output_tokens = min(context_window, 32_768)

        architecture = model_info.get("architecture") or {}
        input_modalities: list[str] = []
        if isinstance(architecture, dict):
            raw_modalities = architecture.get("input_modalities") or []
            if isinstance(raw_modalities, list):
                input_modalities = [m for m in raw_modalities if isinstance(m, str)]

        supported_parameters: list[str] = []
        raw_supported = model_info.get("supported_parameters") or []
        if isinstance(raw_supported, list):
            supported_parameters = [p for p in raw_supported if isinstance(p, str)]

        supports_images = "image" in input_modalities
        supports_function_calling = "tools" in supported_parameters
        supports_json_mode = "response_format" in supported_parameters or "structured_outputs" in supported_parameters
        supports_temperature = "temperature" in supported_parameters

        description = model_info.get("description") or model_info.get("name") or ""
        if not isinstance(description, str):
            description = ""

        capabilities = ModelCapabilities(
            provider=ProviderType.OPENROUTER,
            model_name=model_name,
            friendly_name=f"{self.FRIENDLY_NAME} ({model_name})",
            intelligence_score=9,
            description=description,
            aliases=[],
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            supports_extended_thinking=False,
            supports_system_prompts=True,
            supports_streaming=True,
            supports_function_calling=supports_function_calling,
            supports_images=supports_images,
            supports_json_mode=supports_json_mode,
            supports_temperature=supports_temperature,
            max_image_size_mb=0.0,
            temperature_constraint=RangeTemperatureConstraint(0.0, 2.0, 0.3),
            allow_code_generation=True,
        )
        return capabilities

    # ------------------------------------------------------------------
    # Capability surface
    # ------------------------------------------------------------------

    def _lookup_capabilities(
        self,
        canonical_name: str,
        requested_name: str | None = None,
    ) -> ModelCapabilities | None:
        """Fetch OpenRouter capabilities from the registry or build a generic fallback."""

        capabilities = self._registry.get_capabilities(canonical_name)
        if capabilities:
            return capabilities

        base_identifier = canonical_name.rsplit(":", 1)[0]
        if "/" in base_identifier:
            model_info = self._lookup_dynamic_model_info(canonical_name)
            if model_info is not None:
                logging.debug("Loaded OpenRouter capabilities for %s from Models API", canonical_name)
                return self._build_capabilities_from_models_api(canonical_name, model_info)

            logging.debug(
                "Using generic OpenRouter capabilities for %s (provider/model format detected)", canonical_name
            )
            generic = ModelCapabilities(
                provider=ProviderType.OPENROUTER,
                model_name=canonical_name,
                friendly_name=self.FRIENDLY_NAME,
                intelligence_score=9,
                context_window=32_768,
                max_output_tokens=32_768,
                supports_extended_thinking=False,
                supports_system_prompts=True,
                supports_streaming=True,
                supports_function_calling=False,
                allow_code_generation=True,
                temperature_constraint=RangeTemperatureConstraint(0.0, 2.0, 1.0),
            )
            generic._is_generic = True
            return generic

        logging.debug(
            "Rejecting unknown OpenRouter model '%s' (no provider prefix); requires explicit configuration",
            canonical_name,
        )
        return None

    # ------------------------------------------------------------------
    # Provider identity
    # ------------------------------------------------------------------

    def get_provider_type(self) -> ProviderType:
        """Identify this provider for restrictions and logging."""
        return ProviderType.OPENROUTER

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def list_models(
        self,
        *,
        respect_restrictions: bool = True,
        include_aliases: bool = True,
        lowercase: bool = False,
        unique: bool = False,
    ) -> list[str]:
        """Return formatted OpenRouter model names, respecting alias-aware restrictions."""

        if not self._registry:
            return []

        from utils.model_restrictions import get_restriction_service

        restriction_service = get_restriction_service() if respect_restrictions else None
        allowed_configs: dict[str, ModelCapabilities] = {}

        for model_name in self._registry.list_models():
            config = self._registry.resolve(model_name)
            if not config:
                continue

            # Custom models belong to CustomProvider; skip them here so the two
            # providers don't race over the same registrations (important for tests
            # that stub the registry with minimal objects lacking attrs).
            if config.provider == ProviderType.CUSTOM:
                continue

            if restriction_service:
                allowed = restriction_service.is_allowed(self.get_provider_type(), model_name)

                if not allowed and config.aliases:
                    for alias in config.aliases:
                        if restriction_service.is_allowed(self.get_provider_type(), alias):
                            allowed = True
                            break

                if not allowed:
                    continue

            allowed_configs[model_name] = config

        if not allowed_configs:
            return []

        # When restrictions are in place, don't include aliases to avoid confusion
        # Only return the canonical model names that are actually allowed
        actual_include_aliases = include_aliases and not respect_restrictions

        return ModelCapabilities.collect_model_names(
            allowed_configs,
            include_aliases=actual_include_aliases,
            lowercase=lowercase,
            unique=unique,
        )

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def _resolve_model_name(self, model_name: str) -> str:
        """Resolve aliases defined in the OpenRouter registry."""

        cache_key = model_name.lower()
        if cache_key in self._alias_cache:
            return self._alias_cache[cache_key]

        config = self._registry.resolve(model_name)
        if config:
            if config.model_name != model_name:
                logging.debug("Resolved model alias '%s' to '%s'", model_name, config.model_name)
            resolved = config.model_name
            self._alias_cache[cache_key] = resolved
            self._alias_cache.setdefault(resolved.lower(), resolved)
            return resolved

        logging.debug(f"Model '{model_name}' not found in registry, using as-is")
        self._alias_cache[cache_key] = model_name
        return model_name

    def get_all_model_capabilities(self) -> dict[str, ModelCapabilities]:
        """Expose registry-backed OpenRouter capabilities."""

        if not self._registry:
            return {}

        capabilities: dict[str, ModelCapabilities] = {}
        for model_name in self._registry.list_models():
            config = self._registry.resolve(model_name)
            if not config:
                continue

            # See note in list_models: respect the CustomProvider boundary.
            if config.provider == ProviderType.CUSTOM:
                continue

            capabilities[model_name] = config
        return capabilities
