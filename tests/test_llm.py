import json

import httpx
import pytest

from human_approved_agents.llm import FakeLLM, LLMError, OpenAICompatibleClient

MSGS = [{"role": "user", "content": "hi"}]


def client(handler, **kw):
    return OpenAICompatibleClient(
        base_url="http://llm.test/v1",
        model="m",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        **kw,
    )


def ok(text="hello"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_posts_openai_shape_with_key():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return ok(" hi there ")

    assert client(handler, api_key="test-key").complete(MSGS, temperature=0.1) == "hi there"
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {"model": "m", "messages": MSGS, "temperature": 0.1}


def test_no_key_means_no_auth_header():
    def handler(req):
        assert "authorization" not in req.headers
        return ok()

    assert client(handler).complete(MSGS) == "hello"


def test_retries_rate_limit_and_server_errors():
    responses = iter([httpx.Response(429), httpx.Response(503), ok("third time")])
    assert client(lambda req: next(responses)).complete(MSGS) == "third time"


def test_does_not_retry_client_errors_and_hides_key():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LLMError) as exc:
        client(handler, api_key="secret-value").complete(MSGS)
    assert len(calls) == 1
    assert "secret-value" not in str(exc.value)
    assert "HTTP 401" in str(exc.value)


def test_network_error_after_retries():
    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(LLMError, match="ConnectError"):
        client(handler, max_retries=1).complete(MSGS)


@pytest.mark.parametrize(
    "body", [{"choices": []}, {"nope": 1}, {"choices": [{"message": {"content": ""}}]}]
)
def test_bad_shapes(body):
    with pytest.raises(LLMError):
        client(lambda req: httpx.Response(200, json=body)).complete(MSGS)


def test_fake_llm_script_and_template():
    f = FakeLLM(script=["a"])
    assert f.complete(MSGS) == "a"
    with pytest.raises(LLMError):
        f.complete(MSGS)
    prompt = (
        "FACTS:\n- Fact one.\n- Fact two.\n\nLESSONS:\n- none\n\n"
        "SIGN-OFF: Bo\nTITLE: T\nCONTACT: Al B."
    )
    out = FakeLLM().complete([{"role": "user", "content": prompt}])
    assert out.startswith("Hi Al,")
    assert "Fact one. Fact two." in out
    assert out.endswith("Bo")
    short = FakeLLM().complete(
        [{"role": "user", "content": prompt.replace("none", "Jo shortened it")}]
    )
    assert "Fact two" not in short
