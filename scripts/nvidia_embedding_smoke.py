from __future__ import annotations

import os

from openai import OpenAI


def main() -> None:
    client = OpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=os.environ["NVIDIA_API_KEY"],
    )
    response = client.embeddings.create(
        model=os.getenv("NVIDIA_EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5"),
        input=["Agentic RAG uses planning, tools, observation, and iterative retrieval."],
        extra_body={"input_type": "passage"},
    )
    vector = response.data[0].embedding
    print({"dimension": len(vector), "first_values": vector[:5]})


if __name__ == "__main__":
    main()
