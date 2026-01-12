"""
Model context management for dynamic token allocation.

This module provides a clean abstraction for model-specific token management,
ensuring that token limits are properly calculated based on the current model
being used, not global constants.

CONVERSATION MEMORY INTEGRATION:
This module works closely with the conversation memory system to provide
optimal token allocation for multi-turn conversations:

1. DUAL PRIORITIZATION STRATEGY SUPPORT:
   - Provides separate token budgets for conversation history vs. files
   - Enables the conversation memory system to apply newest-first prioritization
   - Ensures optimal balance between context preservation and new content

2. MODEL-SPECIFIC ALLOCATION:
   - Dynamic allocation based on model capabilities (context window size)
   - Conservative allocation for smaller models (O3: 200K context)
   - Generous allocation for larger models (Gemini: 1M+ context)
   - Adapts token distribution ratios based on model capacity

3. CROSS-TOOL CONSISTENCY:
   - Provides consistent token budgets across different tools
   - Enables seamless conversation continuation between tools
   - Supports conversation reconstruction with proper budget management
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from config import DEFAULT_MODEL
from providers import ModelCapabilities, ModelProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class TokenAllocation:
    """Token allocation strategy for a model."""

    total_tokens: int
    content_tokens: int
    response_tokens: int
    file_tokens: int
    history_tokens: int

    @property
    def available_for_prompt(self) -> int:
        """Tokens available for the actual prompt after allocations."""
        return self.content_tokens - self.file_tokens - self.history_tokens


class TokenProfile(str, Enum):
    DEFAULT = "default"
    CODE_REVIEW = "code_review"
    SYSTEM_DESIGN_REVIEW = "system_design_review"


@dataclass(frozen=True)
class TokenProfileShares:
    """Token allocation shares across the total context window."""

    files: float
    history: float
    response: float
    prompt: float

    def validate(self) -> None:
        total = self.files + self.history + self.response + self.prompt
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"TokenProfileShares must sum to 1.0, got {total}")
        non_response = self.files + self.history + self.prompt
        if non_response <= 0:
            raise ValueError("TokenProfileShares must reserve some non-response tokens for content/history/prompt")


class ModelContext:
    """
    Encapsulates model-specific information and token calculations.

    This class provides a single source of truth for all model-related
    token calculations, ensuring consistency across the system.
    """

    def __init__(
        self,
        model_name: str,
        model_option: Optional[str] = None,
        *,
        token_profile: TokenProfile | str = TokenProfile.DEFAULT,
    ):
        self.model_name = model_name
        self.model_option = model_option  # Store optional model option (e.g., "for", "against", etc.)
        try:
            self.token_profile = TokenProfile(token_profile)
        except Exception:
            self.token_profile = TokenProfile.DEFAULT
        self._provider = None
        self._capabilities = None
        self._token_allocation = None
        self._token_allocation_key: tuple[str, int | None] | None = None
        self._preferred_response_tokens: int | None = None

    @property
    def provider(self):
        """Get the model provider lazily."""
        if self._provider is None:
            self._provider = ModelProviderRegistry.get_provider_for_model(self.model_name)
            if not self._provider:
                available_models = ModelProviderRegistry.get_available_model_names()
                if available_models:
                    available_text = ", ".join(available_models)
                else:
                    available_text = (
                        "No models detected. Configure provider credentials or set DEFAULT_MODEL to a valid option."
                    )

                raise ValueError(
                    f"Model '{self.model_name}' is not available with current API keys. Available models: {available_text}."
                )
        return self._provider

    @property
    def capabilities(self) -> ModelCapabilities:
        """Get model capabilities lazily."""
        if self._capabilities is None:
            self._capabilities = self.provider.get_capabilities(self.model_name)
        return self._capabilities

    def calculate_token_allocation(
        self,
        reserved_for_response: Optional[int] = None,
        *,
        profile: TokenProfile | str | None = None,
    ) -> TokenAllocation:
        """
        Calculate token allocation based on model capacity and conversation requirements.

        This method implements the core token budget calculation that supports the
        dual prioritization strategy used in conversation memory and file processing:

        TOKEN ALLOCATION STRATEGY:
        1. CONTENT vs RESPONSE SPLIT:
           - Smaller models (< 300K): 60% content, 40% response (conservative)
           - Larger models (≥ 300K): 80% content, 20% response (generous)

        2. CONTENT SUB-ALLOCATION:
           - File tokens: 30-40% of content budget for newest file versions
           - History tokens: 40-50% of content budget for conversation context
           - Remaining: Available for tool-specific prompt content

        3. CONVERSATION MEMORY INTEGRATION:
           - History allocation enables conversation reconstruction in reconstruct_thread_context()
           - File allocation supports newest-first file prioritization in tools
           - Remaining budget passed to tools via _remaining_tokens parameter

        Args:
            reserved_for_response: Override response token reservation (best-effort; capped to profile max)
            profile: Allocation profile (defaults to the ModelContext's token_profile)

        Returns:
            TokenAllocation with calculated budgets for dual prioritization strategy
        """
        resolved_profile = TokenProfile(profile) if profile is not None else self.token_profile
        effective_reserved = self._preferred_response_tokens if reserved_for_response is None else reserved_for_response
        cache_key = (resolved_profile.value, effective_reserved)
        if self._token_allocation is not None and self._token_allocation_key == cache_key:
            return self._token_allocation

        total_tokens = self.capabilities.context_window

        def _profile_shares(*, is_large: bool) -> TokenProfileShares:
            # Default profile retains legacy behavior via shares approximating the prior ratios.
            # Shares are defined as proportions of the total context window.
            if resolved_profile == TokenProfile.CODE_REVIEW:
                if is_large:
                    shares = TokenProfileShares(files=0.50, history=0.15, response=0.20, prompt=0.15)
                else:
                    shares = TokenProfileShares(files=0.45, history=0.12, response=0.23, prompt=0.20)
            elif resolved_profile == TokenProfile.SYSTEM_DESIGN_REVIEW:
                if is_large:
                    shares = TokenProfileShares(files=0.60, history=0.10, response=0.20, prompt=0.10)
                else:
                    shares = TokenProfileShares(files=0.55, history=0.10, response=0.22, prompt=0.13)
            else:
                # Legacy ratios:
                # - small: content 60 / response 40; within content: files 30%, history 50%, prompt 20%
                #   => files 18%, history 30%, prompt 12%, response 40%
                # - large: content 80 / response 20; within content: files 40%, history 40%, prompt 20%
                #   => files 32%, history 32%, prompt 16%, response 20%
                if is_large:
                    shares = TokenProfileShares(files=0.32, history=0.32, response=0.20, prompt=0.16)
                else:
                    shares = TokenProfileShares(files=0.18, history=0.30, response=0.40, prompt=0.12)
            shares.validate()
            return shares

        is_large = total_tokens >= 300_000
        shares = _profile_shares(is_large=is_large)

        max_response_tokens = int(total_tokens * shares.response)
        response_tokens = max_response_tokens if effective_reserved is None else min(effective_reserved, max_response_tokens)
        response_tokens = max(1, response_tokens)

        content_tokens = total_tokens - response_tokens
        non_response_share_total = shares.files + shares.history + shares.prompt
        if non_response_share_total <= 0:
            # Defensive fallback to avoid division by zero on misconfiguration.
            non_response_share_total = 1.0 - shares.response

        file_tokens = int(content_tokens * (shares.files / non_response_share_total))
        history_tokens = int(content_tokens * (shares.history / non_response_share_total))

        # Ensure invariants: file/history budgets cannot exceed content budget.
        file_tokens = min(file_tokens, max(0, content_tokens))
        history_tokens = min(history_tokens, max(0, content_tokens - file_tokens))

        allocation = TokenAllocation(
            total_tokens=total_tokens,
            content_tokens=content_tokens,
            response_tokens=response_tokens,
            file_tokens=file_tokens,
            history_tokens=history_tokens,
        )

        logger.debug(f"Token allocation for {self.model_name} ({resolved_profile.value}):")
        logger.debug(f"  Total: {allocation.total_tokens:,}")
        logger.debug(f"  Content: {allocation.content_tokens:,} ({allocation.content_tokens / total_tokens:.0%})")
        logger.debug(f"  Response: {allocation.response_tokens:,} (cap={max_response_tokens:,})")
        logger.debug(f"  Files: {allocation.file_tokens:,}")
        logger.debug(f"  History: {allocation.history_tokens:,}")
        logger.debug(f"  Prompt: {allocation.available_for_prompt:,}")

        self._token_allocation = allocation
        self._token_allocation_key = cache_key
        return allocation

    def estimate_response_tokens(
        self,
        *,
        prompt_tokens: int,
        file_hint_count: int,
        profile: TokenProfile | str | None = None,
    ) -> int:
        """
        Estimate a sensible response-token reservation for this request.

        This is used to avoid reserving an overly-large portion of the context window for outputs
        when the tool is doing code review / design review and the output is typically much smaller.

        The estimate is capped by the profile's response share.
        """
        resolved_profile = TokenProfile(profile) if profile is not None else self.token_profile
        total_tokens = self.capabilities.context_window
        is_large = total_tokens >= 300_000

        # Mirror the profile response share caps from calculate_token_allocation.
        if resolved_profile == TokenProfile.CODE_REVIEW:
            response_share = 0.20 if is_large else 0.23
            base = 2_500
            per_file = 140
        elif resolved_profile == TokenProfile.SYSTEM_DESIGN_REVIEW:
            response_share = 0.20 if is_large else 0.22
            base = 3_500
            per_file = 180
        else:
            response_share = 0.20 if is_large else 0.40
            base = 3_000
            per_file = 120

        response_cap = int(total_tokens * response_share)
        if response_cap <= 0:
            return 1

        prompt_component = min(int(prompt_tokens * 0.30), 2_000)
        expected = base + (per_file * min(max(file_hint_count, 0), 50)) + prompt_component

        # Keep a reasonable minimum reservation, but never exceed the cap.
        minimum = min(2_048, response_cap)
        reserved = max(minimum, min(expected, response_cap))
        # Store for subsequent calculate_token_allocation calls in this request's lifecycle.
        self._preferred_response_tokens = reserved
        return reserved

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text using model-specific tokenizer.

        For now, uses simple estimation. Can be enhanced with model-specific
        tokenizers (tiktoken for OpenAI, etc.) in the future.
        """
        # TODO: Integrate model-specific tokenizers
        # For now, use conservative estimation
        return len(text) // 3  # Conservative estimate

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any]) -> "ModelContext":
        """Create ModelContext from tool arguments."""
        model_name = arguments.get("model") or DEFAULT_MODEL
        return cls(model_name)
