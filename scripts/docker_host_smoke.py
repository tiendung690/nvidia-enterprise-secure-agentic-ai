from __future__ import annotations

import json
import os
import urllib.request


BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")


def get(path: str) -> tuple[int, str]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=15) as response:
        return response.status, response.read().decode()


def post(path: str, payload: dict[str, object]) -> tuple[int, str]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-User-Id": "local-smoke"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return response.status, response.read().decode()


def main() -> None:
    print("live:", get("/health/live"))
    print("ready:", get("/health/ready"))
    status, body = post(
        "/v1/chat",
        {
            "query": (
                "According to the indexed documents, explain the key difference "
                "between basic RAG and Agentic RAG."
            ),
            "session_id": "docker-host-smoke",
        },
    )
    print("chat status:", status)
    print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
