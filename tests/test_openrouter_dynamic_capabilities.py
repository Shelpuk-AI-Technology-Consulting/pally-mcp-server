from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from providers.openrouter import OpenRouterProvider
from providers.registries.openrouter import OpenRouterModelRegistry


def _reset_openrouter_models_api_cache() -> None:
    OpenRouterProvider._models_api_cache = None
    OpenRouterProvider._models_api_last_fetch = None
    OpenRouterProvider._models_api_last_failure = None


@pytest.fixture(autouse=True)
def reset_openrouter_models_api_cache_fixture():
    _reset_openrouter_models_api_cache()
    yield
    _reset_openrouter_models_api_cache()


def test_openrouter_registry_defaults_allow_code_generation_true(tmp_path):
    config_path = tmp_path / "openrouter_models.json"
    config_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model_name": "acme/known-model",
                        "context_window": 100,
                        "max_output_tokens": 50,
                    },
                    {
                        "model_name": "acme/no-codegen",
                        "context_window": 100,
                        "max_output_tokens": 50,
                        "allow_code_generation": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    registry = OpenRouterModelRegistry(config_path=str(config_path))

    defaulted = registry.get_capabilities("acme/known-model")
    assert defaulted.allow_code_generation is True

    explicit = registry.get_capabilities("acme/no-codegen")
    assert explicit.allow_code_generation is False


def test_unknown_openrouter_model_populates_capabilities_from_models_api():
    provider = OpenRouterProvider(api_key="test-key")

    fetch_mock = Mock(
        return_value=[
            {
                "id": "acme/unknown-model",
                "name": "Acme: Unknown Model",
                "description": "A test model",
                "context_length": 100_000,
                "architecture": {"input_modalities": ["text"]},
                "supported_parameters": ["tools", "response_format", "temperature"],
                "top_provider": {"max_completion_tokens": 8192},
            }
        ]
    )
    provider._fetch_models_api = fetch_mock  # type: ignore[method-assign]

    capabilities = provider.get_capabilities("acme/unknown-model")
    assert capabilities.context_window == 100_000
    assert capabilities.max_output_tokens == 8192
    assert capabilities.supports_function_calling is True
    assert capabilities.supports_json_mode is True
    assert capabilities.supports_temperature is True
    assert capabilities.allow_code_generation is True

    # Cache should prevent another fetch.
    capabilities_2 = provider.get_capabilities("acme/unknown-model")
    assert capabilities_2.context_window == 100_000
    assert fetch_mock.call_count == 1


def test_unknown_openrouter_model_api_failure_falls_back_to_generic():
    provider = OpenRouterProvider(api_key="test-key")

    fetch_mock = Mock(side_effect=RuntimeError("boom"))
    provider._fetch_models_api = fetch_mock  # type: ignore[method-assign]

    capabilities = provider.get_capabilities("acme/unknown-model")
    assert capabilities.context_window == 32_768
    assert capabilities.max_output_tokens == 32_768
    assert capabilities.allow_code_generation is True

