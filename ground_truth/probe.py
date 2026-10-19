"""python -m ground_truth.probe [--model SLOT=REF ...] [--dry-run]

Phase 0 of docs/run-schedule.md: one synthetic call per configured slot, recording what only a
live account can tell us -- reachable, any fingerprint the response exposes, rate-limit headers,
and tokens per call. Writes data/probe/probe-<date>.json. It is not a measurement of any model:
the prompt is a made-up invoice snippet, never a golden item.

Standard library only and independent of bok_core (not installed here), so these calls are NOT in
the ledger (00 R7); that is acceptable for a probe that produces no result. Endpoints and auth
shapes are from each provider's own docs (retrieved 2026-10-19, URLs in ENDPOINTS). Keys come
from the environment or .env and are never written anywhere. Providers without a key are
skipped and reported as such, never filled in.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "probe"

# provider -> (url template, key env var, docs url). `{account}` and `{model}` are filled in.
ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "groq": (
        "https://api.groq.com/openai/v1/chat/completions",
        "GROQ_API_KEY",
        "https://console.groq.com/docs/openai",
    ),
    "cerebras": (
        "https://api.cerebras.ai/v1/chat/completions",
        "CEREBRAS_API_KEY",
        "https://inference-docs.cerebras.ai/quickstart",
    ),
    "mistral": (
        "https://api.mistral.ai/v1/chat/completions",
        "MISTRAL_API_KEY",
        "https://docs.mistral.ai/api/endpoint/chat",
    ),
    "cloudflare": (
        "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions",
        "CLOUDFLARE_API_TOKEN",
        "https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/",
    ),
    "google": (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "GOOGLE_API_KEY",
        "https://ai.google.dev/gemini-api/docs",
    ),
}
_ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"

# slot -> (provider, model_ref or None). Refs recorded in docs/providers.md are filled in; the
# rest (DeepSeek V4 Pro, the Gemini model id, the Cerebras judges) must be passed with --model
# rather than guessed. SambaNova is omitted: its endpoint has not been looked up.
SLOTS: dict[str, tuple[str, str | None]] = {
    "A": ("groq", "openai/gpt-oss-120b"),
    "B": ("groq", "qwen/qwen3.8-27b"),
    "C": ("cloudflare", "@cf/meta/llama-3.1-8b-instruct-fp8"),
    "D": ("cloudflare", None),
    "E": ("mistral", "mistral-small-2603"),
    "F": ("google", None),
    "J1": ("cerebras", None),
    "J2": ("cerebras", None),
    "J3": ("cerebras", None),
    "J4": ("cerebras", None),
}

PROBE_PROMPT = (
    "Extract these fields and return one JSON object with string values: invoice_no, total.\n\n"
    "---\nINVOICE NO. PROBE-0001   TOTAL DUE  $1,250.00\n"
    "(synthetic probe text, not a golden item)\n"
)
MAX_TOKENS = 256
_ERROR_SNIPPET = 200
_RATELIMIT_PREFIXES = ("x-ratelimit", "ratelimit", "retry-after")


class MissingCredentialError(Exception):
    """A required environment variable is not set."""


@dataclass(frozen=True)
class ProbeTarget:
    slot: str
    provider: str
    model_ref: str


@dataclass(frozen=True)
class ProbeRequest:
    url: str
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, str], str]]


def _need(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise MissingCredentialError(f"{name} is not set")
    return value


def build_request(target: ProbeTarget, env: Mapping[str, str]) -> ProbeRequest:
    template, key_env, _ = ENDPOINTS[target.provider]
    key = _need(env, key_env)
    if target.provider == "google":
        url = template.format(model=target.model_ref)
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        payload: dict[str, object] = {
            "contents": [{"parts": [{"text": PROBE_PROMPT}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": MAX_TOKENS},
        }
    else:
        url = (
            template.format(account=_need(env, _ACCOUNT_ENV))
            if "{account}" in template
            else template
        )
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": target.model_ref,
            "messages": [{"role": "user", "content": PROBE_PROMPT}],
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
        }
    return ProbeRequest(url, headers, json.dumps(payload).encode("utf-8"))


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def parse_response(
    target: ProbeTarget,
    status: int,
    headers: Mapping[str, str],
    body: str,
    *,
    latency_ms: int,
) -> dict[str, object]:
    reachable = 200 <= status < 300  # noqa: PLR2004 -- the 2xx range
    record: dict[str, object] = {
        "slot": target.slot,
        "provider": target.provider,
        "model_ref": target.model_ref,
        "status": status,
        "reachable": reachable,
        "latency_ms": latency_ms,
        "prompt_tokens": None,
        "completion_tokens": None,
        "fingerprint": None,
        "ratelimit_headers": {
            k.lower(): v for k, v in headers.items() if k.lower().startswith(_RATELIMIT_PREFIXES)
        },
        "note": "",
    }
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not reachable or not isinstance(data, dict):
        record["note"] = body[:_ERROR_SNIPPET]
        return record
    if target.provider == "google":
        usage = data.get("usageMetadata") or {}
        record["prompt_tokens"] = _int(usage.get("promptTokenCount"))
        record["completion_tokens"] = _int(usage.get("candidatesTokenCount"))
        record["fingerprint"] = data.get("modelVersion")
    else:
        usage = data.get("usage") or {}
        record["prompt_tokens"] = _int(usage.get("prompt_tokens"))
        record["completion_tokens"] = _int(usage.get("completion_tokens"))
        record["fingerprint"] = data.get("system_fingerprint")
    return record


def _urllib_transport(
    url: str, headers: dict[str, str], body: bytes
) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310
            return resp.status, dict(resp.headers.items()), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()), err.read().decode("utf-8", "replace")


def run_probe(
    targets: list[ProbeTarget], env: Mapping[str, str], transport: Transport
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for target in targets:
        observed_at = datetime.now(UTC).isoformat()
        try:
            req = build_request(target, env)
        except MissingCredentialError as err:
            records.append(
                {
                    "slot": target.slot,
                    "provider": target.provider,
                    "model_ref": target.model_ref,
                    "status": None,
                    "reachable": False,
                    "note": f"skipped: {err}",
                    "observed_at": observed_at,
                }
            )
            continue
        started = time.monotonic()
        status, headers, body = transport(req.url, req.headers, req.body)
        latency_ms = round((time.monotonic() - started) * 1000)
        record = parse_response(target, status, headers, body, latency_ms=latency_ms)
        record["observed_at"] = observed_at
        records.append(record)
    return records


def _load_env(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                env.setdefault(name.strip(), value.strip().strip("\"'"))
    return env


def targets_from(overrides: Mapping[str, str]) -> tuple[list[ProbeTarget], list[str]]:
    """Slots with a known or supplied model ref; the rest are returned as unresolved notices."""
    targets: list[ProbeTarget] = []
    unresolved: list[str] = []
    for slot, (provider, default_ref) in SLOTS.items():
        ref = overrides.get(slot, default_ref)
        if ref is None:
            unresolved.append(f"{slot} ({provider}): no model ref -- pass --model {slot}=<ref>")
        else:
            targets.append(ProbeTarget(slot, provider, ref))
    return targets, unresolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 0 provider probe.")
    parser.add_argument("--model", action="append", default=[], metavar="SLOT=REF")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan; call nothing.")
    args = parser.parse_args()
    overrides = dict(item.split("=", 1) for item in args.model)

    targets, unresolved = targets_from(overrides)
    for notice in unresolved:
        print(f"not probed: {notice}")
    env = _load_env(REPO / ".env")
    if args.dry_run:
        for t in targets:
            key_env = ENDPOINTS[t.provider][1]
            state = "set" if env.get(key_env) else "MISSING"
            print(f"would probe {t.slot} {t.provider} {t.model_ref} (key {key_env}: {state})")
        return

    records = run_probe(targets, env, _urllib_transport)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"probe-{datetime.now(UTC).date().isoformat()}.json"
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    for rec in records:
        note = str(rec.get("note", ""))[:60]
        print(
            f"{rec['slot']:>3} {rec['provider']:<10} status={rec['status']} "
            f"reachable={rec['reachable']} {note}"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
