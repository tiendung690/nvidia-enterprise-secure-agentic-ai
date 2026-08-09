"""Minimal hosted NVIDIA probes to distinguish provider capacity from agent issues."""
from __future__ import annotations

import os
import sys
from openai import OpenAI


def run_probe(
    name: str,
    *,
    thinking: bool,
    max_tokens: int,
    reasoning_budget: int | None = None,
) -> bool:
    client = OpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=os.environ["NVIDIA_API_KEY"],
        max_retries=0,
        timeout=60.0,
    )
    extra_body = {"chat_template_kwargs": {"enable_thinking": thinking}}
    if reasoning_budget is not None:
        extra_body["reasoning_budget"] = reasoning_budget
    try:
        response = client.chat.completions.create(
            model=os.getenv("NVIDIA_LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            temperature=1.0,
            top_p=0.95,
            max_tokens=max_tokens,
            extra_body=extra_body,
            stream=False,
        )
        content = response.choices[0].message.content
        print(f"PASS {name}: {content!r}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    basic = run_probe("minimal-no-thinking", thinking=False, max_tokens=64)
    reasoning = run_probe(
        "small-reasoning",
        thinking=True,
        max_tokens=512,
        reasoning_budget=256,
    )
    if basic and reasoning:
        print(
            "Provider is reachable. Investigate agent/tool orchestration "
            "if /v1/chat still fails."
        )
        return 0
    print(
        "At least one direct probe failed. This points to hosted endpoint "
        "capacity or account limits."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
