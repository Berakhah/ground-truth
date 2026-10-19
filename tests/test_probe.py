"""Phase 0 probe: one synthetic call per provider to record reachable, fingerprint, limits and
tokens per call. Offline here -- the transport is injected, so no test touches a network."""

import json

import pytest

from ground_truth.probe import (
    MissingCredentialError,
    ProbeTarget,
    build_request,
    parse_response,
    run_probe,
)

KEY = "sk-test-0123456789"

GROQ = ProbeTarget("A", "groq", "openai/gpt-oss-120b")
CLOUDFLARE = ProbeTarget("C", "cloudflare", "@cf/meta/llama-3.1-8b-instruct-fp8")
GOOGLE = ProbeTarget("F", "google", "some-gemini-model")


def test_an_openai_style_request_is_a_bearer_post_at_temperature_zero():
    req = build_request(GROQ, {"GROQ_API_KEY": KEY})
    assert req.url == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(req.body)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["temperature"] == 0
    assert body["messages"][0]["role"] == "user"


def test_cloudflare_puts_the_account_id_in_the_path():
    env = {"CLOUDFLARE_API_TOKEN": KEY, "CLOUDFLARE_ACCOUNT_ID": "acct123"}
    req = build_request(CLOUDFLARE, env)
    assert "/accounts/acct123/ai/v1/chat/completions" in req.url


def test_cloudflare_without_an_account_id_is_a_missing_credential():
    with pytest.raises(MissingCredentialError, match="CLOUDFLARE_ACCOUNT_ID"):
        build_request(CLOUDFLARE, {"CLOUDFLARE_API_TOKEN": KEY})


def test_google_uses_its_own_header_and_a_model_in_the_path():
    req = build_request(GOOGLE, {"GOOGLE_API_KEY": KEY})
    assert req.url.endswith("/models/some-gemini-model:generateContent")
    assert req.headers["x-goog-api-key"] == KEY
    assert "Authorization" not in req.headers


def test_openai_style_usage_fingerprint_and_ratelimit_headers_are_recorded():
    body = json.dumps(
        {"usage": {"prompt_tokens": 120, "completion_tokens": 30}, "system_fingerprint": "fp_1"}
    )
    headers = {"x-ratelimit-remaining-tokens": "7800", "content-type": "application/json"}
    rec = parse_response(GROQ, 200, headers, body, latency_ms=410)
    assert rec["reachable"] is True
    assert (rec["prompt_tokens"], rec["completion_tokens"]) == (120, 30)
    assert rec["fingerprint"] == "fp_1"
    assert rec["ratelimit_headers"] == {"x-ratelimit-remaining-tokens": "7800"}


def test_a_response_without_a_fingerprint_records_none_rather_than_implying_one():
    body = json.dumps({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    rec = parse_response(GROQ, 200, {}, body, latency_ms=1)
    assert rec["fingerprint"] is None


def test_gemini_usage_and_version_fields_are_read_from_their_own_names():
    body = json.dumps(
        {
            "usageMetadata": {"promptTokenCount": 90, "candidatesTokenCount": 12},
            "modelVersion": "v-1",
            "responseId": "r-1",
        }
    )
    rec = parse_response(GOOGLE, 200, {}, body, latency_ms=300)
    assert (rec["prompt_tokens"], rec["completion_tokens"]) == (90, 12)
    assert rec["fingerprint"] == "v-1"


def test_a_429_is_not_reachable_but_still_keeps_its_ratelimit_headers():
    rec = parse_response(GROQ, 429, {"retry-after": "30"}, '{"error": "slow down"}', latency_ms=5)
    assert rec["reachable"] is False
    assert rec["status"] == 429  # noqa: PLR2004 -- the HTTP status under test
    assert rec["ratelimit_headers"] == {"retry-after": "30"}


def test_a_provider_without_a_key_is_skipped_and_never_called():
    calls = []

    def transport(*args):
        calls.append(args)
        raise AssertionError("must not be called")

    [rec] = run_probe([GROQ], {}, transport)
    assert rec["status"] is None and rec["reachable"] is False
    assert "GROQ_API_KEY" in rec["note"]
    assert calls == []


def test_the_written_record_never_contains_the_key():
    def transport(url, headers, body):
        return 200, {}, json.dumps({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    records = run_probe([GROQ], {"GROQ_API_KEY": KEY}, transport)
    assert KEY not in json.dumps(records)
