from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request

CAPTURE_PATH = Path(os.getenv("CAPTURE_PATH", "/capture/events.jsonl"))
CAPTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Synthetic OpenAI-compatible provider capture")


def record(path: str, body: dict[str, Any]) -> None:
    event = {
        "timestamp": time.time(),
        "path": path,
        "body": body,
    }
    with CAPTURE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def vector_for(text: str, dims: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for i in range(dims):
        raw = digest[i % len(digest)]
        values.append((raw + 1) / 256.0)
    return values


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> dict[str, Any]:
    body = await request.json()
    record("/v1/embeddings", body)
    raw_input = body.get("input", [])
    inputs = [raw_input] if isinstance(raw_input, str) else list(raw_input)
    return {
        "object": "list",
        "model": body.get("model", "capture-embedding"),
        "data": [
            {"object": "embedding", "index": i, "embedding": vector_for(str(text))}
            for i, text in enumerate(inputs)
        ],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict[str, Any]:
    body = await request.json()
    record("/v1/chat/completions", body)
    return {
        "id": f"capture-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "capture-chat"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Synthetic provider-capture response.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CAPTURE_PORT", "18081")))
