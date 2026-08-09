from __future__ import annotations

import os

import pytest


@pytest.mark.live
def test_nvidia_chat_completion() -> None:
    if os.getenv("RUN_LIVE_TESTS") != "1" or not os.getenv("NVIDIA_API_KEY"):
        pytest.skip("Set RUN_LIVE_TESTS=1 and NVIDIA_API_KEY")
    OpenAI = pytest.importorskip("openai").OpenAI
    client = OpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=os.environ["NVIDIA_API_KEY"],
    )
    result = client.chat.completions.create(
        model=os.getenv("NVIDIA_LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
        messages=[{"role": "user", "content": "Reply with exactly: NVIDIA_OK"}],
        temperature=0,
        max_tokens=64,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    assert "NVIDIA_OK" in (result.choices[0].message.content or "")
