from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.nvidia.embeddings import NvidiaNIMEmbedding


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canary", default="")
    parser.add_argument(
        "--capture-file",
        type=Path,
        default=Path("artifacts/provider-capture/events.jsonl"),
    )
    args = parser.parse_args()
    canary = args.canary or f"QUERY_EMBED_CANARY_{secrets.token_hex(16).upper()}"

    settings = Settings()
    embedding = NvidiaNIMEmbedding(
        model_name=settings.nvidia_embedding_model,
        api_base=settings.nvidia_base_url,
        api_key=settings.api_key_value(),
        timeout_seconds=settings.nvidia_timeout_seconds,
        max_retries=0,
        embed_batch_size=1,
        max_input_tokens=settings.nvidia_embedding_max_input_tokens,
        token_safety_margin=settings.nvidia_embedding_token_safety_margin,
        truncate=settings.nvidia_embedding_truncate,
    )
    embedding.get_query_embedding(canary)

    hits = []
    if args.capture_file.exists():
        for line in args.capture_file.read_text(encoding="utf-8").splitlines():
            if canary in line:
                hits.append(json.loads(line))
    print(json.dumps({"canary": canary, "captured": bool(hits), "hits": hits}, indent=2))
    raise SystemExit(0 if hits else 1)


if __name__ == "__main__":
    main()
