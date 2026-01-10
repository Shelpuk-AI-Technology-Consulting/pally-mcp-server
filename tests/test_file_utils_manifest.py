import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.chat import ChatTool
from utils.file_utils import read_files_with_manifest


def test_read_files_with_manifest_returns_embedded_files(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("print('a')\n", encoding="utf-8")
    nested = project / "nested"
    nested.mkdir()
    (nested / "b.py").write_text("print('b')\n", encoding="utf-8")
    (nested / "c.py").write_text("print('c')\n", encoding="utf-8")

    content, manifest = read_files_with_manifest([str(project)], max_tokens=200_000, reserve_tokens=1_000)

    assert len(manifest) == 3
    assert all(os.path.isabs(p) for p in manifest)
    assert all(Path(p).is_file() for p in manifest)

    for embedded_file in manifest:
        assert f"--- BEGIN FILE: {embedded_file} " in content
        assert f"--- END FILE: {embedded_file} ---" in content


def test_prepare_file_content_for_prompt_expands_only_once(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("print('a')\n", encoding="utf-8")
    (project / "b.py").write_text("print('b')\n", encoding="utf-8")

    tool = ChatTool()

    class _TokenAllocation:
        file_tokens = 200_000

    class _ModelContext:
        model_name = "gemini-2.5-flash"

        def calculate_token_allocation(self):
            return _TokenAllocation()

    model_context = _ModelContext()

    import utils.file_utils as file_utils

    with patch("utils.file_utils.expand_paths", wraps=file_utils.expand_paths) as mock_expand:
        _content, embedded = tool._prepare_file_content_for_prompt(
            [str(project)],
            continuation_id=None,
            model_context=model_context,
        )

    assert mock_expand.call_count == 1
    assert len(embedded) == 2


@pytest.mark.asyncio
async def test_pal_model_call_timeout_sec_enforced(monkeypatch):
    monkeypatch.setenv("PAL_MODEL_CALL_TIMEOUT_SEC", "0.01")

    from providers.base import ModelProvider
    from providers.shared import ModelResponse, ProviderType

    class SlowProvider(ModelProvider):
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
            import time

            time.sleep(0.05)
            return ModelResponse(
                content="ok",
                usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                model_name=model_name,
                friendly_name="SlowProvider",
                provider=self.get_provider_type(),
                metadata={},
            )

    tool = ChatTool()
    provider = SlowProvider(api_key="dummy")

    with pytest.raises(TimeoutError):
        await tool._generate_content_with_provider_lock(
            provider,
            prompt="hi",
            model_name="z-ai/glm-4.7",
            system_prompt="",
            temperature=0.1,
        )
