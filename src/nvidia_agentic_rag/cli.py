from __future__ import annotations

import argparse
import asyncio
import json

from nvidia_agentic_rag.bootstrap import build_container, build_index_manager_for_ingest
from nvidia_agentic_rag.config import Settings


def _ingest(args: argparse.Namespace) -> None:
    manager = build_index_manager_for_ingest(Settings())
    print(json.dumps(manager.ingest(recreate=args.recreate), indent=2))


async def _chat(args: argparse.Namespace) -> None:
    container = build_container(Settings())
    result = await container.agent_service.chat(args.query, args.session_id)
    print(result.answer)
    print(
        json.dumps(
            {
                "tools": result.tools,
                "tool_call_count": result.tool_call_count,
                "latency_ms": result.latency_ms,
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentic-rag")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Embed and persist both corpora with NVIDIA API")
    ingest.add_argument("--recreate", action="store_true")
    ingest.set_defaults(func=_ingest)

    chat = sub.add_parser("chat", help="Run one agent query")
    chat.add_argument("query")
    chat.add_argument("--session-id", default="cli-session")
    chat.set_defaults(func=lambda args: asyncio.run(_chat(args)))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
