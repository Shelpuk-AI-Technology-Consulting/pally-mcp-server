import asyncio
import json

import httpx
import pytest

from providers.openrouter import OpenRouterProvider


class DelayedSSEStream(httpx.AsyncByteStream):
    def __init__(self, parts: list[tuple[float, bytes]]):
        self._parts = parts
        self.closed = False

    async def __aiter__(self):
        for delay_s, payload in self._parts:
            if delay_s:
                await asyncio.sleep(delay_s)
            yield payload

    async def aclose(self) -> None:
        self.closed = True


def test_openrouter_processing_timeout_keepalive_allows_completion(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PROCESSING_TIMEOUT", "0.2")

    stream = DelayedSSEStream(
        [
        (0.0, b": OPENROUTER PROCESSING\n\n"),
        (
            0.05,
            b'data: {"id":"gen-1","created":1,"model":"z-ai/glm-4.7","choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n',
        ),
        (
            0.0,
            b'data: {"id":"gen-1","created":1,"model":"z-ai/glm-4.7","choices":[{"index":0,"delta":{"content":" there"}}]}\n\n',
        ),
        (0.0, b"data: [DONE]\n\n"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode("utf-8"))
        assert body["stream"] is True
        assert "Authorization" in request.headers
        assert request.headers.get("HTTP-Referer")
        assert request.headers.get("X-Title")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    provider = OpenRouterProvider(api_key="dummy")
    provider._test_transport = httpx.MockTransport(handler)  # noqa: SLF001

    result = provider.generate_content(
        prompt="hello",
        model_name="z-ai/glm-4.7",
        system_prompt="",
        temperature=0.1,
    )
    assert result.content == "hi there"
    assert stream.closed is True


def test_openrouter_processing_timeout_no_activity_aborts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PROCESSING_TIMEOUT", "0.05")

    # First bytes arrive after the processing timeout.
    stream = DelayedSSEStream(
        [
        (0.2, b": OPENROUTER PROCESSING\n\n"),
        (0.0, b"data: [DONE]\n\n"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode("utf-8"))
        assert body["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    provider = OpenRouterProvider(api_key="dummy")
    provider._test_transport = httpx.MockTransport(handler)  # noqa: SLF001
    provider._is_error_retryable = lambda exc: False  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as excinfo:
        provider.generate_content(
            prompt="hello",
            model_name="z-ai/glm-4.7",
            system_prompt="",
            temperature=0.1,
        )
    assert "OPENROUTER_PROCESSING_TIMEOUT" in str(excinfo.value)
    assert stream.closed is True


def test_openrouter_processing_timeout_responses_completed_extracts_output_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PROCESSING_TIMEOUT", "0.2")

    response_completed = (
        b'data: {"type":"response.completed","response":{"id":"resp_1","created_at":123,"model":"o3-pro",'
        b'"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"hello"}]}]}}\n\n'
    )
    stream = DelayedSSEStream([(0.0, b": OPENROUTER PROCESSING\n\n"), (0.0, response_completed)])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        body = json.loads(request.content.decode("utf-8"))
        assert body["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    provider = OpenRouterProvider(api_key="dummy")
    provider._test_transport = httpx.MockTransport(handler)  # noqa: SLF001

    completion_params = {"model": "o3-pro", "input": [], "reasoning": {"effort": "medium"}, "stream": True}
    result = provider._generate_openrouter_responses_streaming(  # noqa: SLF001
        completion_params=completion_params,
        model_name="o3-pro",
    )
    assert result.content == "hello"
    assert stream.closed is True
