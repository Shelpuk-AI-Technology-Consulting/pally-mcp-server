from __future__ import annotations

import os
from pathlib import Path

import pytest

from providers.shared.model_capabilities import ModelCapabilities
from providers.shared.provider_type import ProviderType
from utils.conversation_memory import ConversationTurn, ThreadContext, build_conversation_history
from utils.file_relevance import FileRankingContext
from utils.file_utils import read_files_with_manifest
from utils.model_context import ModelContext, TokenAllocation, TokenProfile


def _patch_dummy_provider(monkeypatch, *, context_window: int):
    class _Provider:
        def get_capabilities(self, model_name: str):
            return ModelCapabilities(
                provider=ProviderType.OPENAI,
                model_name=model_name,
                friendly_name="dummy",
                context_window=context_window,
                max_output_tokens=context_window,
            )

    from providers.registry import ModelProviderRegistry

    monkeypatch.setattr(
        ModelProviderRegistry,
        "get_provider_for_model",
        classmethod(lambda cls, model_name: _Provider()),
    )


def test_token_profiles_allocate_more_file_budget(monkeypatch):
    _patch_dummy_provider(monkeypatch, context_window=100_000)

    ctx_default = ModelContext("dummy", token_profile=TokenProfile.DEFAULT)
    alloc_default = ctx_default.calculate_token_allocation()

    ctx_review = ModelContext("dummy", token_profile=TokenProfile.CODE_REVIEW)
    ctx_review.estimate_response_tokens(prompt_tokens=100, file_hint_count=2, profile=TokenProfile.CODE_REVIEW)
    alloc_review = ctx_review.calculate_token_allocation()

    assert alloc_review.file_tokens > alloc_default.file_tokens
    assert alloc_review.history_tokens < alloc_default.history_tokens


def test_read_files_with_manifest_ranking_and_dependency_closure(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "b.py").write_text("def b():\n    return 1\n", encoding="utf-8")
    (project / "a.py").write_text("import b\n\ndef a():\n    return b.b()\n", encoding="utf-8")
    (project / "README.md").write_text("# docs\n", encoding="utf-8")

    ranking = FileRankingContext(
        prompt="Please review a.py",
        explicit_paths={str((project / "a.py").resolve())},
        project_root=str(project),
    )

    content, embedded = read_files_with_manifest(
        [str((project / "a.py").resolve())],
        max_tokens=5_000,
        reserve_tokens=0,
        ranking_context=ranking,
        enable_reduction=True,
    )

    # Dependency closure should add b.py.
    assert str((project / "b.py").resolve()) in embedded
    assert "--- BEGIN FILE:" in content


def test_read_files_with_manifest_reduces_large_file(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    big = project / "big.py"
    big.write_text("def x():\n" + ("    a = 1\n" * 2000), encoding="utf-8")

    content, embedded = read_files_with_manifest(
        [str(big.resolve())],
        max_tokens=700,
        reserve_tokens=0,
        enable_reduction=True,
    )

    assert str(big.resolve()) in embedded
    assert "[REDUCED]" in content


def test_build_conversation_history_adds_summary_for_omitted_turns(tmp_path: Path):
    # Craft a conversation where an old turn is too large, but there is still summary budget remaining.
    huge_old = "X" * 10_000
    turns = [
        ConversationTurn(role="assistant", content=huge_old, timestamp="2023-01-01T00:00:00Z"),
        ConversationTurn(role="user", content="ok", timestamp="2023-01-01T00:00:01Z"),
        ConversationTurn(role="assistant", content="ok", timestamp="2023-01-01T00:00:02Z"),
        ConversationTurn(role="user", content="ok", timestamp="2023-01-01T00:00:03Z"),
        ConversationTurn(role="assistant", content="ok", timestamp="2023-01-01T00:00:04Z"),
        ConversationTurn(role="user", content="ok", timestamp="2023-01-01T00:00:05Z"),
    ]

    context = ThreadContext(
        thread_id="12345678-1234-1234-1234-123456789012",
        created_at="2023-01-01T00:00:00Z",
        last_updated_at="2023-01-01T00:00:10Z",
        tool_name="codereview",
        turns=turns,
        initial_context={},
    )

    class _DummyModelContext:
        model_name = "dummy"
        token_profile = TokenProfile.CODE_REVIEW

        def calculate_token_allocation(self):
            return TokenAllocation(
                total_tokens=10_000,
                content_tokens=8_000,
                response_tokens=2_000,
                file_tokens=0,
                history_tokens=900,
            )

        def estimate_tokens(self, text: str) -> int:
            return len(text) // 4

    history, _tokens = build_conversation_history(context, model_context=_DummyModelContext())

    assert "=== SUMMARY OF OLDER TURNS (OMITTED) ===" in history
