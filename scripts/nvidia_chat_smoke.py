"""Direct NVIDIA chat smoke test matching the API pattern from NVIDIA's model page.

Reasoning is hidden by default. Set SHOW_REASONING=true only for private development diagnostics.
"""

from __future__ import annotations

import os

from openai import OpenAI


def main() -> None:
    api_key = os.environ["NVIDIA_API_KEY"]
    show_reasoning = os.getenv("SHOW_REASONING", "false").lower() == "true"
    client = OpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=api_key,
    )
    completion = client.chat.completions.create(
        model=os.getenv("NVIDIA_LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
        messages=[
            {
                "role": "user",
                "content": os.getenv(
                    "SMOKE_PROMPT",
                    "Explain the difference between basic RAG and Agentic RAG in three points.",
                ),
            }
        ],
        temperature=float(os.getenv("NVIDIA_TEMPERATURE", "1")),
        top_p=float(os.getenv("NVIDIA_TOP_P", "0.95")),
        max_tokens=int(os.getenv("NVIDIA_MAX_TOKENS", "16384")),
        extra_body={
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": int(os.getenv("NVIDIA_REASONING_BUDGET", "16384")),
        },
        stream=True,
    )
    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if show_reasoning and reasoning:
            print(reasoning, end="", flush=True)
        if delta.content is not None:
            print(delta.content, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
