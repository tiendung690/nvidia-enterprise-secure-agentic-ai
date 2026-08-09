from __future__ import annotations

import os

import pytest


@pytest.mark.live
def test_nvidia_embedding() -> None:
    if os.getenv("RUN_LIVE_TESTS") != "1" or not os.getenv("NVIDIA_API_KEY"):
        pytest.skip("Set RUN_LIVE_TESTS=1 and NVIDIA_API_KEY")
    OpenAI = pytest.importorskip("openai").OpenAI
    client = OpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=os.environ["NVIDIA_API_KEY"],
    )
    result = client.embeddings.create(
        model=os.getenv("NVIDIA_EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5"),
        input=["Agentic RAG"],
        extra_body={"input_type": "query", "truncate": "END"},
    )
    assert len(result.data[0].embedding) > 0
