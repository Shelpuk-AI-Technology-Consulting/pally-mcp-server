"""Base class for OpenAI-compatible API providers."""

import asyncio
import copy
import ipaddress
import json
import logging
import time
from typing import Optional
from urllib.parse import urlparse

from openai import OpenAI

from utils.env import get_env, suppress_env_vars
from utils.image_utils import validate_image

from .base import ModelProvider
from .shared import (
    ModelCapabilities,
    ModelResponse,
    ProviderType,
)


class OpenAICompatibleProvider(ModelProvider):
    """Shared implementation for OpenAI API lookalikes.

    The class owns HTTP client configuration (timeouts, proxy hardening,
    custom headers) and normalises the OpenAI SDK responses into
    :class:`~providers.shared.ModelResponse`.  Concrete subclasses only need to
    provide capability metadata and any provider-specific request tweaks.
    """

    DEFAULT_HEADERS = {}
    FRIENDLY_NAME = "OpenAI Compatible"
    _OPENROUTER_PROCESSING_TIMEOUT_DEFAULT_SEC = 15.0

    def __init__(self, api_key: str, base_url: str = None, **kwargs):
        """Initialize the provider with API key and optional base URL.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API endpoint
            **kwargs: Additional configuration options including timeout
        """
        self._allowed_alias_cache: dict[str, str] = {}
        super().__init__(api_key, **kwargs)
        self._client = None
        self.base_url = base_url
        self.organization = kwargs.get("organization")
        self.allowed_models = self._parse_allowed_models()

        # Configure timeouts - especially important for custom/local endpoints
        self.timeout_config = self._configure_timeouts(**kwargs)

        # Validate base URL for security
        if self.base_url:
            self._validate_base_url()

        # Warn if using external URL without authentication
        if self.base_url and not self._is_localhost_url() and not api_key:
            logging.warning(
                f"Using external URL '{self.base_url}' without API key. "
                "This may be insecure. Consider setting an API key for authentication."
            )

    def _get_openrouter_processing_timeout_sec(self) -> float:
        """Return the OpenRouter first-activity timeout in seconds (time-to-first-activity only)."""

        raw = (get_env("OPENROUTER_PROCESSING_TIMEOUT", "") or "").strip()
        if not raw:
            return self._OPENROUTER_PROCESSING_TIMEOUT_DEFAULT_SEC
        try:
            value = float(raw)
        except (TypeError, ValueError):
            logging.warning(
                "Invalid OPENROUTER_PROCESSING_TIMEOUT value '%s'; using default of %ss",
                raw,
                self._OPENROUTER_PROCESSING_TIMEOUT_DEFAULT_SEC,
            )
            return self._OPENROUTER_PROCESSING_TIMEOUT_DEFAULT_SEC
        if value <= 0:
            logging.warning(
                "Non-positive OPENROUTER_PROCESSING_TIMEOUT value '%s'; using default of %ss",
                raw,
                self._OPENROUTER_PROCESSING_TIMEOUT_DEFAULT_SEC,
            )
            return self._OPENROUTER_PROCESSING_TIMEOUT_DEFAULT_SEC
        return value

    def _extract_usage_dict(self, usage: object) -> Optional[dict[str, int]]:
        """Extract token usage from OpenRouter/OpenAI-style dict usage blocks."""

        if not isinstance(usage, dict):
            return None

        # OpenAI chat-completions-style usage
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        # OpenAI responses-style usage
        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            prompt_tokens = usage.get("input_tokens")
            completion_tokens = usage.get("output_tokens")
            total_tokens = usage.get("total_tokens")

        def _to_int(value: object) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        input_tokens = _to_int(prompt_tokens)
        output_tokens = _to_int(completion_tokens)
        if total_tokens is None:
            total_tokens_value = input_tokens + output_tokens
        else:
            total_tokens_value = _to_int(total_tokens)

        if input_tokens == 0 and output_tokens == 0 and total_tokens_value == 0:
            return None

        return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens_value}

    def _openrouter_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.DEFAULT_HEADERS:
            headers.update(self.DEFAULT_HEADERS)
        return headers

    def _openrouter_url(self, path: str) -> str:
        if not self.base_url:
            raise ValueError("OpenRouter streaming requires base_url to be configured.")
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    async def _wait_for_openrouter_first_activity_line(self, line_iter, *, timeout_sec: float) -> str:
        """Wait up to ``timeout_sec`` for the first OpenRouter SSE activity line."""

        deadline = time.monotonic() + timeout_sec

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"OpenRouter streaming timed out awaiting first activity after {timeout_sec}s "
                    f"(OPENROUTER_PROCESSING_TIMEOUT={timeout_sec})."
                )

            try:
                line = await asyncio.wait_for(line_iter.__anext__(), timeout=remaining)
            except StopAsyncIteration as exc:
                raise TimeoutError(
                    f"OpenRouter streaming ended before first activity after {timeout_sec}s "
                    f"(OPENROUTER_PROCESSING_TIMEOUT={timeout_sec})."
                ) from exc
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"OpenRouter streaming timed out awaiting first activity after {timeout_sec}s "
                    f"(OPENROUTER_PROCESSING_TIMEOUT={timeout_sec})."
                ) from exc

            if not line:
                continue

            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("data:"):
                return line

            # OpenRouter keep-alive comment (as documented by OpenRouter).
            if stripped.startswith(":") and "OPENROUTER" in stripped.upper() and "PROCESSING" in stripped.upper():
                return line

    async def _iter_with_first(self, first: str, line_iter):
        yield first
        async for line in line_iter:
            yield line

    def _run_async(self, coro):
        """Run a coroutine from sync provider code (provider calls run in worker threads)."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("Cannot run OpenRouter streaming from an active event loop thread.")

    def _extract_output_text_from_responses_payload(self, response_payload: dict) -> str:
        output = response_payload.get("output")
        if not isinstance(output, list):
            return ""

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                if content_item.get("type") == "output_text":
                    text = content_item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "".join(parts)

    def _generate_openrouter_chat_completions_streaming(
        self,
        *,
        completion_params: dict,
        model_name: str,
    ) -> ModelResponse:
        """Execute an OpenRouter chat completion via SSE and aggregate the final content."""

        import httpx

        timeout_sec = self._get_openrouter_processing_timeout_sec()
        url = self._openrouter_url("/chat/completions")
        headers = self._openrouter_headers()

        async def _call() -> ModelResponse:
            proxy_env_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
            transport = getattr(self, "_test_transport", None)

            with suppress_env_vars(*proxy_env_vars):
                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=self.timeout_config,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    async with client.stream("POST", url, json=completion_params) as response:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", errors="replace")
                            raise RuntimeError(
                                f"OpenRouter streaming request failed (status={response.status_code}): {body[:2000]}"
                            )

                        line_iter = response.aiter_lines()
                        first_line = await self._wait_for_openrouter_first_activity_line(line_iter, timeout_sec=timeout_sec)

                        content_parts: list[str] = []
                        usage: Optional[dict[str, int]] = None
                        metadata: dict[str, object] = {"endpoint": "chat_completions", "streaming": True}

                        async for line in self._iter_with_first(first_line, line_iter):
                            if not line:
                                continue

                            stripped = line.strip()
                            if not stripped:
                                continue

                            # Ignore OpenRouter keep-alive comments.
                            if stripped.startswith(":"):
                                continue

                            if not stripped.startswith("data:"):
                                continue

                            data = stripped[len("data:") :].lstrip()
                            if data == "[DONE]":
                                break

                            try:
                                payload = json.loads(data)
                            except json.JSONDecodeError as exc:
                                raise RuntimeError(f"OpenRouter streaming sent invalid JSON chunk: {data[:2000]}") from exc

                            if isinstance(payload, dict) and payload.get("error"):
                                raise RuntimeError(f"OpenRouter streaming error: {payload.get('error')}")

                            if isinstance(payload, dict):
                                if payload.get("id"):
                                    metadata["id"] = payload.get("id")
                                if payload.get("created") is not None:
                                    metadata["created"] = payload.get("created")
                                if payload.get("model"):
                                    metadata["model"] = payload.get("model")

                                extracted = self._extract_usage_dict(payload.get("usage"))
                                if extracted is not None:
                                    usage = extracted

                                choices = payload.get("choices")
                                if isinstance(choices, list):
                                    for choice in choices:
                                        if not isinstance(choice, dict):
                                            continue
                                        finish_reason = choice.get("finish_reason")
                                        if finish_reason is not None:
                                            metadata["finish_reason"] = finish_reason
                                        delta = choice.get("delta")
                                        if isinstance(delta, dict):
                                            token = delta.get("content")
                                            if isinstance(token, str) and token:
                                                content_parts.append(token)

                        return ModelResponse(
                            content="".join(content_parts),
                            usage=usage,
                            model_name=model_name,
                            friendly_name=self.FRIENDLY_NAME,
                            provider=self.get_provider_type(),
                            metadata=metadata,
                        )

        try:
            return self._run_async(_call())
        except TimeoutError as exc:
            logging.warning(
                "OpenRouter streaming timed out waiting for first activity (timeout=%ss model=%s endpoint=chat_completions): %s",
                timeout_sec,
                model_name,
                exc,
            )
            raise

    def _generate_openrouter_responses_streaming(
        self,
        *,
        completion_params: dict,
        model_name: str,
    ) -> ModelResponse:
        """Execute an OpenRouter responses call via SSE and extract final output text."""

        import httpx

        timeout_sec = self._get_openrouter_processing_timeout_sec()
        url = self._openrouter_url("/responses")
        headers = self._openrouter_headers()

        async def _call() -> ModelResponse:
            proxy_env_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
            transport = getattr(self, "_test_transport", None)

            with suppress_env_vars(*proxy_env_vars):
                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=self.timeout_config,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    async with client.stream("POST", url, json=completion_params) as response:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", errors="replace")
                            raise RuntimeError(
                                f"OpenRouter streaming request failed (status={response.status_code}): {body[:2000]}"
                            )

                        line_iter = response.aiter_lines()
                        first_line = await self._wait_for_openrouter_first_activity_line(line_iter, timeout_sec=timeout_sec)

                        completed_response: Optional[dict] = None
                        output_parts: list[str] = []
                        usage: Optional[dict[str, int]] = None
                        metadata: dict[str, object] = {"endpoint": "responses", "streaming": True}

                        async for line in self._iter_with_first(first_line, line_iter):
                            if not line:
                                continue

                            stripped = line.strip()
                            if not stripped:
                                continue

                            if stripped.startswith(":"):
                                continue

                            if not stripped.startswith("data:"):
                                continue

                            data = stripped[len("data:") :].lstrip()
                            if data == "[DONE]":
                                break

                            try:
                                event = json.loads(data)
                            except json.JSONDecodeError as exc:
                                raise RuntimeError(
                                    f"OpenRouter responses stream sent invalid JSON event: {data[:2000]}"
                                ) from exc

                            if isinstance(event, dict) and event.get("error"):
                                raise RuntimeError(f"OpenRouter responses stream error: {event.get('error')}")

                            if not isinstance(event, dict):
                                continue

                            event_type = event.get("type")
                            if isinstance(event_type, str):
                                metadata["last_event_type"] = event_type

                            response_obj = event.get("response")
                            if isinstance(response_obj, dict):
                                if response_obj.get("id"):
                                    metadata["id"] = response_obj.get("id")
                                if response_obj.get("created_at") is not None:
                                    metadata["created"] = response_obj.get("created_at")
                                if response_obj.get("model"):
                                    metadata["model"] = response_obj.get("model")
                                extracted = self._extract_usage_dict(response_obj.get("usage"))
                                if extracted is not None:
                                    usage = extracted

                            # Capture deltas as a fallback if response.completed is not delivered.
                            if event_type == "response.output_text.delta":
                                delta = event.get("delta")
                                if isinstance(delta, str) and delta:
                                    output_parts.append(delta)

                            if event_type == "response.completed" and isinstance(response_obj, dict):
                                completed_response = response_obj
                                break

                            if event_type in {"response.failed", "response.error"}:
                                raise RuntimeError(f"OpenRouter responses stream failed ({event_type}): {event}")

                        content = ""
                        if completed_response is not None:
                            content = self._extract_output_text_from_responses_payload(completed_response)
                        if not content:
                            content = "".join(output_parts)

                        return ModelResponse(
                            content=content,
                            usage=usage,
                            model_name=model_name,
                            friendly_name=self.FRIENDLY_NAME,
                            provider=self.get_provider_type(),
                            metadata=metadata,
                        )

        try:
            return self._run_async(_call())
        except TimeoutError as exc:
            logging.warning(
                "OpenRouter responses streaming timed out waiting for first activity (timeout=%ss model=%s): %s",
                timeout_sec,
                model_name,
                exc,
            )
            raise

    def _ensure_model_allowed(
        self,
        capabilities: ModelCapabilities,
        canonical_name: str,
        requested_name: str,
    ) -> None:
        """Respect provider-specific allowlists before default restriction checks."""

        super()._ensure_model_allowed(capabilities, canonical_name, requested_name)

        if self.allowed_models is not None:
            requested = requested_name.lower()
            canonical = canonical_name.lower()

            if requested not in self.allowed_models and canonical not in self.allowed_models:
                allowed = False
                for allowed_entry in list(self.allowed_models):
                    normalized_resolved = self._allowed_alias_cache.get(allowed_entry)
                    if normalized_resolved is None:
                        try:
                            resolved_name = self._resolve_model_name(allowed_entry)
                        except Exception:
                            continue

                        if not resolved_name:
                            continue

                        normalized_resolved = resolved_name.lower()
                        self._allowed_alias_cache[allowed_entry] = normalized_resolved

                    if normalized_resolved == canonical:
                        # Canonical match discovered via alias resolution – mark as allowed and
                        # memoise the canonical entry for future lookups.
                        allowed = True
                        self._allowed_alias_cache[canonical] = canonical
                        self.allowed_models.add(canonical)
                        break

                if not allowed:
                    raise ValueError(
                        f"Model '{requested_name}' is not allowed by restriction policy. Allowed models: {sorted(self.allowed_models)}"
                    )

    def _parse_allowed_models(self) -> Optional[set[str]]:
        """Parse allowed models from environment variable.

        Returns:
            Set of allowed model names (lowercase) or None if not configured
        """
        # Get provider-specific allowed models
        provider_type = self.get_provider_type().value.upper()
        env_var = f"{provider_type}_ALLOWED_MODELS"
        models_str = get_env(env_var, "") or ""

        if models_str:
            # Parse and normalize to lowercase for case-insensitive comparison
            models = {m.strip().lower() for m in models_str.split(",") if m.strip()}
            if models:
                logging.info(f"Configured allowed models for {self.FRIENDLY_NAME}: {sorted(models)}")
                self._allowed_alias_cache = {}
                return models

        # Log info if no allow-list configured for proxy providers
        if self.get_provider_type() not in [ProviderType.GOOGLE, ProviderType.OPENAI]:
            logging.info(
                f"Model allow-list not configured for {self.FRIENDLY_NAME} - all models permitted. "
                f"To restrict access, set {env_var} with comma-separated model names."
            )

        return None

    def _configure_timeouts(self, **kwargs):
        """Configure timeout settings based on provider type and custom settings.

        Custom URLs and local models often need longer timeouts due to:
        - Network latency on local networks
        - Extended thinking models taking longer to respond
        - Local inference being slower than cloud APIs

        Returns:
            httpx.Timeout object with appropriate timeout settings
        """
        import httpx

        # Default timeouts - more generous for custom/local endpoints
        default_connect = 30.0  # 30 seconds for connection (vs OpenAI's 5s)
        default_read = 600.0  # 10 minutes for reading (same as OpenAI default)
        default_write = 600.0  # 10 minutes for writing
        default_pool = 600.0  # 10 minutes for pool

        # For custom/local URLs, use even longer timeouts
        if self.base_url and self._is_localhost_url():
            default_connect = 60.0  # 1 minute for local connections
            default_read = 1800.0  # 30 minutes for local models (extended thinking)
            default_write = 1800.0  # 30 minutes for local models
            default_pool = 1800.0  # 30 minutes for local models
            logging.info(f"Using extended timeouts for local endpoint: {self.base_url}")
        elif self.base_url:
            default_connect = 45.0  # 45 seconds for custom remote endpoints
            default_read = 900.0  # 15 minutes for custom remote endpoints
            default_write = 900.0  # 15 minutes for custom remote endpoints
            default_pool = 900.0  # 15 minutes for custom remote endpoints
            logging.info(f"Using extended timeouts for custom endpoint: {self.base_url}")

        # Allow override via kwargs or environment variables in future, for now...
        connect_timeout = kwargs.get("connect_timeout")
        if connect_timeout is None:
            connect_timeout_raw = get_env("CUSTOM_CONNECT_TIMEOUT")
            connect_timeout = float(connect_timeout_raw) if connect_timeout_raw is not None else float(default_connect)

        read_timeout = kwargs.get("read_timeout")
        if read_timeout is None:
            read_timeout_raw = get_env("CUSTOM_READ_TIMEOUT")
            read_timeout = float(read_timeout_raw) if read_timeout_raw is not None else float(default_read)

        write_timeout = kwargs.get("write_timeout")
        if write_timeout is None:
            write_timeout_raw = get_env("CUSTOM_WRITE_TIMEOUT")
            write_timeout = float(write_timeout_raw) if write_timeout_raw is not None else float(default_write)

        pool_timeout = kwargs.get("pool_timeout")
        if pool_timeout is None:
            pool_timeout_raw = get_env("CUSTOM_POOL_TIMEOUT")
            pool_timeout = float(pool_timeout_raw) if pool_timeout_raw is not None else float(default_pool)

        timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=write_timeout, pool=pool_timeout)

        logging.debug(
            f"Configured timeouts - Connect: {connect_timeout}s, Read: {read_timeout}s, "
            f"Write: {write_timeout}s, Pool: {pool_timeout}s"
        )

        return timeout

    def _is_localhost_url(self) -> bool:
        """Check if the base URL points to localhost or local network.

        Returns:
            True if URL is localhost or local network, False otherwise
        """
        if not self.base_url:
            return False

        try:
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname

            # Check for common localhost patterns
            if hostname in ["localhost", "127.0.0.1", "::1"]:
                return True

            # Check for private network ranges (local network)
            if hostname:
                try:
                    ip = ipaddress.ip_address(hostname)
                    return ip.is_private or ip.is_loopback
                except ValueError:
                    # Not an IP address, might be a hostname
                    pass

            return False
        except Exception:
            return False

    def _validate_base_url(self) -> None:
        """Validate base URL for security (SSRF protection).

        Raises:
            ValueError: If URL is invalid or potentially unsafe
        """
        if not self.base_url:
            return

        try:
            parsed = urlparse(self.base_url)

            # Check URL scheme - only allow http/https
            if parsed.scheme not in ("http", "https"):
                raise ValueError(f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.")

            # Check hostname exists
            if not parsed.hostname:
                raise ValueError("URL must include a hostname")

            # Check port is valid (if specified)
            port = parsed.port
            if port is not None and (port < 1 or port > 65535):
                raise ValueError(f"Invalid port number: {port}. Must be between 1 and 65535.")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Invalid base URL '{self.base_url}': {str(e)}")

    @property
    def client(self):
        """Lazy initialization of OpenAI client with security checks and timeout configuration."""
        if self._client is None:
            import httpx

            proxy_env_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]

            with suppress_env_vars(*proxy_env_vars):
                try:
                    # Create a custom httpx client that explicitly avoids proxy parameters
                    timeout_config = (
                        self.timeout_config
                        if hasattr(self, "timeout_config") and self.timeout_config
                        else httpx.Timeout(30.0)
                    )

                    # Create httpx client with minimal config to avoid proxy conflicts
                    # Note: proxies parameter was removed in httpx 0.28.0
                    # Check for test transport injection
                    if hasattr(self, "_test_transport"):
                        # Use custom transport for testing (HTTP recording/replay)
                        http_client = httpx.Client(
                            transport=self._test_transport,
                            timeout=timeout_config,
                            follow_redirects=True,
                        )
                    else:
                        # Normal production client
                        http_client = httpx.Client(
                            timeout=timeout_config,
                            follow_redirects=True,
                        )

                    # Keep client initialization minimal to avoid proxy parameter conflicts
                    client_kwargs = {
                        "api_key": self.api_key,
                        "http_client": http_client,
                    }

                    if self.base_url:
                        client_kwargs["base_url"] = self.base_url

                    if self.organization:
                        client_kwargs["organization"] = self.organization

                    # Add default headers if any
                    if self.DEFAULT_HEADERS:
                        client_kwargs["default_headers"] = self.DEFAULT_HEADERS.copy()

                    logging.debug(
                        "OpenAI client initialized with custom httpx client and timeout: %s",
                        timeout_config,
                    )

                    # Create OpenAI client with custom httpx client
                    self._client = OpenAI(**client_kwargs)

                except Exception as e:
                    # If all else fails, try absolute minimal client without custom httpx
                    logging.warning(
                        "Failed to create client with custom httpx, falling back to minimal config: %s",
                        e,
                    )
                    try:
                        minimal_kwargs = {"api_key": self.api_key}
                        if self.base_url:
                            minimal_kwargs["base_url"] = self.base_url
                        self._client = OpenAI(**minimal_kwargs)
                    except Exception as fallback_error:
                        logging.error("Even minimal OpenAI client creation failed: %s", fallback_error)
                        raise

        return self._client

    def _sanitize_for_logging(self, params: dict) -> dict:
        """Sanitize sensitive data from parameters before logging.

        Args:
            params: Dictionary of API parameters

        Returns:
            dict: Sanitized copy of parameters safe for logging
        """
        sanitized = copy.deepcopy(params)

        # Sanitize messages content
        if "input" in sanitized:
            for msg in sanitized.get("input", []):
                if isinstance(msg, dict) and "content" in msg:
                    for content_item in msg.get("content", []):
                        if isinstance(content_item, dict) and "text" in content_item:
                            # Truncate long text and add ellipsis
                            text = content_item["text"]
                            if len(text) > 100:
                                content_item["text"] = text[:100] + "... [truncated]"

        # Remove any API keys that might be in headers/auth
        sanitized.pop("api_key", None)
        sanitized.pop("authorization", None)

        return sanitized

    def _safe_extract_output_text(self, response) -> str:
        """Safely extract output_text from o3-pro response with validation.

        Args:
            response: Response object from OpenAI SDK

        Returns:
            str: The output text content

        Raises:
            ValueError: If output_text is missing, None, or not a string
        """
        logging.debug(f"Response object type: {type(response)}")
        logging.debug(f"Response attributes: {dir(response)}")

        if not hasattr(response, "output_text"):
            raise ValueError(f"o3-pro response missing output_text field. Response type: {type(response).__name__}")

        content = response.output_text
        logging.debug(f"Extracted output_text: '{content}' (type: {type(content)})")

        if content is None:
            raise ValueError("o3-pro returned None for output_text")

        if not isinstance(content, str):
            raise ValueError(f"o3-pro output_text is not a string. Got type: {type(content).__name__}")

        return content

    def _generate_with_responses_endpoint(
        self,
        model_name: str,
        messages: list,
        temperature: float,
        max_output_tokens: Optional[int] = None,
        capabilities: Optional[ModelCapabilities] = None,
        **kwargs,
    ) -> ModelResponse:
        """Generate content using the /v1/responses endpoint for reasoning models."""
        # Convert messages to the correct format for responses endpoint
        input_messages = []

        for message in messages:
            role = message.get("role", "")
            content = message.get("content", "")

            if role == "system":
                # For o3-pro, system messages should be handled carefully to avoid policy violations
                # Instead of prefixing with "System:", we'll include the system content naturally
                input_messages.append({"role": "user", "content": [{"type": "input_text", "text": content}]})
            elif role == "user":
                input_messages.append({"role": "user", "content": [{"type": "input_text", "text": content}]})
            elif role == "assistant":
                input_messages.append({"role": "assistant", "content": [{"type": "output_text", "text": content}]})

        # Prepare completion parameters for responses endpoint
        # Based on OpenAI documentation, use nested reasoning object for responses endpoint
        effort = "medium"
        if capabilities and capabilities.default_reasoning_effort:
            effort = capabilities.default_reasoning_effort

        completion_params = {
            "model": model_name,
            "input": input_messages,
            "reasoning": {"effort": effort},
        }

        # Only include store parameter for providers that support it.
        # OpenRouter's /responses endpoint rejects store:true via Zod validation (Issue #348).
        # This is an endpoint-level limitation, not model-specific, so we omit for all
        # OpenRouter /responses calls. If OpenRouter later supports store, revisit this logic.
        if self.get_provider_type() != ProviderType.OPENROUTER:
            completion_params["store"] = True
        else:
            logging.debug(f"Omitting 'store' parameter for OpenRouter provider (model: {model_name})")

        # Add max tokens if specified (using max_completion_tokens for responses endpoint)
        if max_output_tokens:
            completion_params["max_completion_tokens"] = max_output_tokens

        # For responses endpoint, we only add parameters that are explicitly supported
        # Remove unsupported chat completion parameters that may cause API errors

        # Retry logic with progressive delays
        max_retries = 4
        retry_delays = [1, 3, 5, 8]
        attempt_counter = {"value": 0}

        def _attempt() -> ModelResponse:
            attempt_counter["value"] += 1
            import json

            sanitized_params = self._sanitize_for_logging(completion_params)
            logging.info(
                f"o3-pro API request (sanitized): {json.dumps(sanitized_params, indent=2, ensure_ascii=False)}"
            )

            if self.get_provider_type() == ProviderType.OPENROUTER and self.base_url:
                completion_params["stream"] = True
                return self._generate_openrouter_responses_streaming(
                    completion_params=completion_params,
                    model_name=model_name,
                )

            response = self.client.responses.create(**completion_params)

            content = self._safe_extract_output_text(response)

            usage = None
            if hasattr(response, "usage"):
                usage = self._extract_usage(response)
            elif hasattr(response, "input_tokens") and hasattr(response, "output_tokens"):
                input_tokens = getattr(response, "input_tokens", 0) or 0
                output_tokens = getattr(response, "output_tokens", 0) or 0
                usage = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }

            return ModelResponse(
                content=content,
                usage=usage,
                model_name=model_name,
                friendly_name=self.FRIENDLY_NAME,
                provider=self.get_provider_type(),
                metadata={
                    "model": getattr(response, "model", model_name),
                    "id": getattr(response, "id", ""),
                    "created": getattr(response, "created_at", 0),
                    "endpoint": "responses",
                },
            )

        try:
            return self._run_with_retries(
                operation=_attempt,
                max_attempts=max_retries,
                delays=retry_delays,
                log_prefix="responses endpoint",
            )
        except Exception as exc:
            attempts = max(attempt_counter["value"], 1)
            error_msg = f"responses endpoint error after {attempts} attempt{'s' if attempts > 1 else ''}: {exc}"
            logging.error(error_msg)
            raise RuntimeError(error_msg) from exc

    def generate_content(
        self,
        prompt: str,
        model_name: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_output_tokens: Optional[int] = None,
        images: Optional[list[str]] = None,
        **kwargs,
    ) -> ModelResponse:
        """Generate content using the OpenAI-compatible API.

        Args:
            prompt: User prompt to send to the model
            model_name: Canonical model name or its alias
            system_prompt: Optional system prompt for model behavior
            temperature: Sampling temperature
            max_output_tokens: Maximum tokens to generate
            images: Optional list of image paths or data URLs to include with the prompt (for vision models)
            **kwargs: Additional provider-specific parameters

        Returns:
            ModelResponse with generated content and metadata
        """
        # Validate model name against allow-list
        if not self.validate_model_name(model_name):
            raise ValueError(f"Model '{model_name}' not in allowed models list. Allowed models: {self.allowed_models}")

        capabilities: Optional[ModelCapabilities]
        try:
            capabilities = self.get_capabilities(model_name)
        except Exception as exc:
            logging.debug(f"Falling back to generic capabilities for {model_name}: {exc}")
            capabilities = None

        # Get effective temperature for this model from capabilities when available
        if capabilities:
            effective_temperature = capabilities.get_effective_temperature(temperature)
            if effective_temperature is not None and effective_temperature != temperature:
                logging.debug(
                    f"Adjusting temperature from {temperature} to {effective_temperature} for model {model_name}"
                )
        else:
            effective_temperature = temperature

        # Only validate if temperature is not None (meaning the model supports it)
        if effective_temperature is not None:
            # Validate parameters with the effective temperature
            self.validate_parameters(model_name, effective_temperature)

        # Resolve to canonical model name
        resolved_model = self._resolve_model_name(model_name)

        # Prepare messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Prepare user message with text and potentially images
        user_content = []
        user_content.append({"type": "text", "text": prompt})

        # Add images if provided and model supports vision
        if images and capabilities and capabilities.supports_images:
            for image_path in images:
                try:
                    image_content = self._process_image(image_path)
                    if image_content:
                        user_content.append(image_content)
                except Exception as e:
                    logging.warning(f"Failed to process image {image_path}: {e}")
                    # Continue with other images and text
                    continue
        elif images and (not capabilities or not capabilities.supports_images):
            logging.warning(f"Model {resolved_model} does not support images, ignoring {len(images)} image(s)")

        # Add user message
        if len(user_content) == 1:
            # Only text content, use simple string format for compatibility
            messages.append({"role": "user", "content": prompt})
        else:
            # Text + images, use content array format
            messages.append({"role": "user", "content": user_content})

        # Prepare completion parameters
        completion_params = {
            "model": resolved_model,
            "messages": messages,
        }

        # Use the effective temperature we calculated earlier
        supports_sampling = effective_temperature is not None

        if supports_sampling:
            completion_params["temperature"] = effective_temperature

        # Add max tokens if specified and model supports it
        # O3/O4 models that don't support temperature also don't support max_tokens
        if max_output_tokens and supports_sampling:
            completion_params["max_tokens"] = max_output_tokens

        # Add any additional OpenAI-specific parameters
        # Use capabilities to filter parameters for reasoning models
        for key, value in kwargs.items():
            if key in ["top_p", "frequency_penalty", "presence_penalty", "seed", "stop", "stream"]:
                # Reasoning models (those that don't support temperature) also don't support these parameters
                if not supports_sampling and key in ["top_p", "frequency_penalty", "presence_penalty", "stream"]:
                    continue  # Skip unsupported parameters for reasoning models
                completion_params[key] = value

        # Check if this model needs the Responses API endpoint
        # Prefer capability metadata; fall back to static map when capabilities unavailable
        use_responses_api = False
        if capabilities is not None:
            use_responses_api = getattr(capabilities, "use_openai_response_api", False)
        else:
            static_capabilities = self.get_all_model_capabilities().get(resolved_model)
            if static_capabilities is not None:
                use_responses_api = getattr(static_capabilities, "use_openai_response_api", False)

        if use_responses_api:
            # These models require the /v1/responses endpoint for stateful context
            # If it fails, we should not fall back to chat/completions
            return self._generate_with_responses_endpoint(
                model_name=resolved_model,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                capabilities=capabilities,
                **kwargs,
            )

        # Retry logic with progressive delays
        max_retries = 4  # Total of 4 attempts
        retry_delays = [1, 3, 5, 8]  # Progressive delays: 1s, 3s, 5s, 8s
        attempt_counter = {"value": 0}

        def _attempt() -> ModelResponse:
            attempt_counter["value"] += 1

            if self.get_provider_type() == ProviderType.OPENROUTER and self.base_url:
                completion_params["stream"] = True
                return self._generate_openrouter_chat_completions_streaming(
                    completion_params=completion_params,
                    model_name=resolved_model,
                )

            response = self.client.chat.completions.create(**completion_params)

            content = response.choices[0].message.content
            usage = self._extract_usage(response)

            return ModelResponse(
                content=content,
                usage=usage,
                model_name=resolved_model,
                friendly_name=self.FRIENDLY_NAME,
                provider=self.get_provider_type(),
                metadata={
                    "finish_reason": response.choices[0].finish_reason,
                    "model": response.model,
                    "id": response.id,
                    "created": response.created,
                },
            )

        try:
            return self._run_with_retries(
                operation=_attempt,
                max_attempts=max_retries,
                delays=retry_delays,
                log_prefix=f"{self.FRIENDLY_NAME} API ({resolved_model})",
            )
        except Exception as exc:
            attempts = max(attempt_counter["value"], 1)
            error_msg = (
                f"{self.FRIENDLY_NAME} API error for model {resolved_model} after {attempts} attempt"
                f"{'s' if attempts > 1 else ''}: {exc}"
            )
            logging.error(error_msg)
            raise RuntimeError(error_msg) from exc

    def validate_parameters(self, model_name: str, temperature: float, **kwargs) -> None:
        """Validate model parameters.

        For proxy providers, this may use generic capabilities.

        Args:
            model_name: Canonical model name or its alias
            temperature: Temperature to validate
            **kwargs: Additional parameters to validate
        """
        try:
            capabilities = self.get_capabilities(model_name)

            # Check if we're using generic capabilities
            if hasattr(capabilities, "_is_generic"):
                logging.debug(
                    f"Using generic parameter validation for {model_name}. Actual model constraints may differ."
                )

            # Validate temperature using parent class method
            super().validate_parameters(model_name, temperature, **kwargs)

        except Exception as e:
            # For proxy providers, we might not have accurate capabilities
            # Log warning but don't fail
            logging.warning(f"Parameter validation limited for {model_name}: {e}")

    def _extract_usage(self, response) -> dict[str, int]:
        """Extract token usage from OpenAI response.

        Args:
            response: OpenAI API response object

        Returns:
            Dictionary with usage statistics
        """
        usage = {}

        if hasattr(response, "usage") and response.usage:
            # Safely extract token counts with None handling
            usage["input_tokens"] = getattr(response.usage, "prompt_tokens", 0) or 0
            usage["output_tokens"] = getattr(response.usage, "completion_tokens", 0) or 0
            usage["total_tokens"] = getattr(response.usage, "total_tokens", 0) or 0

        return usage

    def count_tokens(self, text: str, model_name: str) -> int:
        """Count tokens using OpenAI-compatible tokenizer tables when available."""

        resolved_model = self._resolve_model_name(model_name)

        try:
            import tiktoken

            try:
                encoding = tiktoken.encoding_for_model(resolved_model)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")

            return len(encoding.encode(text))

        except (ImportError, Exception) as exc:
            logging.debug("tiktoken unavailable for %s: %s", resolved_model, exc)

        return super().count_tokens(text, model_name)

    def _is_error_retryable(self, error: Exception) -> bool:
        """Determine if an error should be retried based on structured error codes.

        Uses OpenAI API error structure instead of text pattern matching for reliability.

        Args:
            error: Exception from OpenAI API call

        Returns:
            True if error should be retried, False otherwise
        """
        error_str = str(error).lower()

        # Check for 429 errors first - these need special handling
        if "429" in error_str:
            # Try to extract structured error information
            error_type = None
            error_code = None

            # Parse structured error from OpenAI API response
            # Format: "Error code: 429 - {'error': {'type': 'tokens', 'code': 'rate_limit_exceeded', ...}}"
            try:
                import ast
                import json
                import re

                # Extract JSON part from error string using regex
                # Look for pattern: {...} (from first { to last })
                json_match = re.search(r"\{.*\}", str(error))
                if json_match:
                    json_like_str = json_match.group(0)

                    # First try: parse as Python literal (handles single quotes safely)
                    try:
                        error_data = ast.literal_eval(json_like_str)
                    except (ValueError, SyntaxError):
                        # Fallback: try JSON parsing with simple quote replacement
                        # (for cases where it's already valid JSON or simple replacements work)
                        json_str = json_like_str.replace("'", '"')
                        error_data = json.loads(json_str)

                    if "error" in error_data:
                        error_info = error_data["error"]
                        error_type = error_info.get("type")
                        error_code = error_info.get("code")

            except (json.JSONDecodeError, ValueError, SyntaxError, AttributeError):
                # Fall back to checking hasattr for OpenAI SDK exception objects
                if hasattr(error, "response") and hasattr(error.response, "json"):
                    try:
                        response_data = error.response.json()
                        if "error" in response_data:
                            error_info = response_data["error"]
                            error_type = error_info.get("type")
                            error_code = error_info.get("code")
                    except Exception:
                        pass

            # Determine if 429 is retryable based on structured error codes
            if error_type == "tokens":
                # Token-related 429s are typically non-retryable (request too large)
                logging.debug(f"Non-retryable 429: token-related error (type={error_type}, code={error_code})")
                return False
            elif error_code in ["invalid_request_error", "context_length_exceeded"]:
                # These are permanent failures
                logging.debug(f"Non-retryable 429: permanent failure (type={error_type}, code={error_code})")
                return False
            else:
                # Other 429s (like requests per minute) are retryable
                logging.debug(f"Retryable 429: rate limiting (type={error_type}, code={error_code})")
                return True

        # For non-429 errors, check if they're retryable
        retryable_indicators = [
            "timeout",
            "connection",
            "network",
            "temporary",
            "unavailable",
            "retry",
            "408",  # Request timeout
            "500",  # Internal server error
            "502",  # Bad gateway
            "503",  # Service unavailable
            "504",  # Gateway timeout
            "ssl",  # SSL errors
            "handshake",  # Handshake failures
        ]

        return any(indicator in error_str for indicator in retryable_indicators)

    def _process_image(self, image_path: str) -> Optional[dict]:
        """Process an image for OpenAI-compatible API."""
        try:
            if image_path.startswith("data:"):
                # Validate the data URL
                validate_image(image_path)
                # Handle data URL: data:image/png;base64,iVBORw0...
                return {"type": "image_url", "image_url": {"url": image_path}}
            else:
                # Use base class validation
                image_bytes, mime_type = validate_image(image_path)

                # Read and encode the image
                import base64

                image_data = base64.b64encode(image_bytes).decode()
                logging.debug(f"Processing image '{image_path}' as MIME type '{mime_type}'")

                # Create data URL for OpenAI API
                data_url = f"data:{mime_type};base64,{image_data}"

                return {"type": "image_url", "image_url": {"url": data_url}}

        except ValueError as e:
            logging.warning(str(e))
            return None
        except Exception as e:
            logging.error(f"Error processing image {image_path}: {e}")
            return None
