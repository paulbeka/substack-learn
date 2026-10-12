import json
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI

from french_bot.config import Settings
from french_bot.generate import GenerationError, OpenAIGenerator
from french_bot.schema import Lesson


def test_responses_structured_output_contract(lesson):
    generator = OpenAIGenerator(Settings(api_key="test-key"))
    generator.client = Mock()
    generator.client.responses.parse.return_value = Mock(status="completed", output_parsed=lesson)
    assert generator.generate("food", [], []) == lesson
    kwargs = generator.client.responses.parse.call_args.kwargs
    assert kwargs["text_format"] is Lesson
    assert kwargs["store"] is False
    assert kwargs["model"] == "gpt-4.1-mini"
    assert "2026-" not in json.dumps(kwargs["input"])


@pytest.mark.parametrize("status,parsed", [("incomplete", None), ("completed", None)])
def test_refusal_or_incomplete_is_safe(status, parsed):
    generator = OpenAIGenerator(Settings(api_key="test-key"))
    generator.client = Mock()
    generator.client.responses.parse.return_value = Mock(status=status, output_parsed=parsed)
    with pytest.raises(GenerationError, match="refused or returned incomplete"):
        generator.generate("food", [], [])


def test_sdk_http_error_is_redacted_and_not_retried_for_auth():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "secret-test-key", "type": "auth"}})

    generator = OpenAIGenerator(Settings(api_key="secret-test-key"))
    generator.client = OpenAI(
        api_key="secret-test-key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GenerationError) as exc:
        generator.generate("food", [], [])
    assert "HTTP 401" in str(exc.value)
    assert "secret-test-key" not in str(exc.value)
    assert len(calls) == 1


def test_sdk_transient_error_has_bounded_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            503, headers={"retry-after-ms": "1"}, json={"error": {"message": "unavailable"}}
        )

    generator = OpenAIGenerator(Settings(api_key="test-key"))
    generator.client = OpenAI(
        api_key="test-key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GenerationError):
        generator.generate("food", [], [])
    assert len(calls) == 3
