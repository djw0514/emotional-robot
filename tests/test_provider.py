import asyncio
import json

import httpx
import pytest
from emotional_robot.config import Settings
from emotional_robot.providers import CompatibleProvider, ProviderError


def provider(handler):
    return CompatibleProvider(
        Settings(provider="compatible", model_api_key="test-secret-not-real"),
        transport=httpx.MockTransport(handler),
    )


def test_deepseek_request_and_stream():
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret-not-real"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash" and body["stream"] is True
        assert body["thinking"] == {"type": "disabled"}
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][-1] == {"role": "user", "content": "你好"}
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"你好🌱"}}]}\n\ndata: [DONE]\n\n'
        )

    async def consume():
        return [
            text
            async for text in provider(handler).stream([{"role": "user", "content": "你好"}], [])
        ]

    assert asyncio.run(consume()) == ["你好🌱"]


@pytest.mark.parametrize(
    "status,body",
    [
        (429, "sensitive upstream error"),
        (200, 'data: {"choices":[]}\n\n'),
        (200, "data: [DONE]\n\n"),
    ],
)
def test_upstream_error_and_truncation(status, body):
    async def consume():
        return [
            text
            async for text in provider(lambda _: httpx.Response(status, text=body)).stream(
                [{"role": "user", "content": "hi"}], []
            )
        ]

    with pytest.raises(ProviderError) as error:
        asyncio.run(consume())
    assert "sensitive" not in str(error.value) and "test-secret" not in str(error.value)


def test_extraction_requires_verbatim_evidence():
    def handler(_):
        facts = [
            {
                "content": "用户喜欢猫",
                "predicate": "pet",
                "kind": "preference",
                "evidence": "没有说过的句子",
            }
        ]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"facts": facts})}}]}
        )

    assert provider(handler).extract("我喜欢画画") == []


def test_bad_extraction_schema_fails():
    bad = {"choices": [{"message": {"content": '{"facts":[{"oops":1}]}'}}]}
    with pytest.raises(ProviderError):
        provider(lambda _: httpx.Response(200, json=bad)).extract("我喜欢画画")


def test_missing_key_does_not_silently_fall_back():
    with pytest.raises(ValueError):
        CompatibleProvider(Settings(provider="compatible", model_api_key=""))
