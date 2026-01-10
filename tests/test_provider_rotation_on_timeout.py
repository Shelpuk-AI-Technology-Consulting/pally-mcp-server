import time

import pytest

from providers.base import ModelProvider
from providers.registry import ModelProviderRegistry
from providers.shared import ModelResponse, ProviderType
from tools.chat import ChatTool


@pytest.mark.asyncio
async def test_timeout_rotates_cached_provider_instance(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")
    monkeypatch.setenv("PALLY_MODEL_CALL_TIMEOUT_SEC", "0.01")

    registry = ModelProviderRegistry()
    previous_provider_class = registry._providers.get(ProviderType.OPENROUTER)  # noqa: SLF001
    previous_initialized = registry._initialized_providers.get(ProviderType.OPENROUTER)  # noqa: SLF001

    class CountingProvider(ModelProvider):
        instance_count = 0

        def __init__(self, api_key: str, **kwargs):
            super().__init__(api_key, **kwargs)
            CountingProvider.instance_count += 1
            self.instance_id = CountingProvider.instance_count

        def get_provider_type(self) -> ProviderType:
            return ProviderType.OPENROUTER

        def generate_content(
            self,
            prompt: str,
            model_name: str,
            system_prompt=None,
            temperature: float = 0.3,
            max_output_tokens=None,
            **kwargs,
        ) -> ModelResponse:
            time.sleep(0.05)
            return ModelResponse(
                content=f"ok-{self.instance_id}",
                usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                model_name=model_name,
                friendly_name="CountingProvider",
                provider=self.get_provider_type(),
                metadata={},
            )

    try:
        ModelProviderRegistry.register_provider(ProviderType.OPENROUTER, CountingProvider)
        provider = ModelProviderRegistry.get_provider(ProviderType.OPENROUTER, force_new=True)
        assert provider is not None
        assert CountingProvider.instance_count == 1

        tool = ChatTool()
        with pytest.raises(TimeoutError):
            await tool._generate_content_with_provider_lock(
                provider,
                prompt="hi",
                model_name="z-ai/glm-4.7",
                system_prompt="",
                temperature=0.1,
            )

        rotated = ModelProviderRegistry.get_provider(ProviderType.OPENROUTER)
        assert rotated is not None
        assert rotated is not provider
        assert CountingProvider.instance_count >= 2
    finally:
        # Restore registry state for other tests.
        if previous_provider_class is not None:
            registry._providers[ProviderType.OPENROUTER] = previous_provider_class  # noqa: SLF001
        else:
            registry._providers.pop(ProviderType.OPENROUTER, None)  # noqa: SLF001

        if previous_initialized is not None:
            registry._initialized_providers[ProviderType.OPENROUTER] = previous_initialized  # noqa: SLF001
        else:
            registry._initialized_providers.pop(ProviderType.OPENROUTER, None)  # noqa: SLF001
