from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))
    return ordered[idx]


async def one_request(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    query: str,
    tenant: str,
    user: str,
    session_id: str,
    force_retrieval: bool,
    purpose: str,
) -> dict[str, Any]:
    request_id = f"load-{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url}/v1/chat",
            json={
                "query": query,
                "session_id": session_id,
                "purpose": purpose,
                "answer_mode": "enterprise_factual",
                "force_retrieval": force_retrieval,
            },
            headers={
                "X-User-Id": user,
                "X-Tenant-Id": tenant,
                "X-Clearance": "public",
                "X-Request-ID": request_id,
            },
        )
        elapsed = (time.perf_counter() - started) * 1000
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text}
        return {
            "status": response.status_code,
            "elapsed_ms": round(elapsed, 2),
            "outcome": body.get("request_outcome"),
            "error_code": body.get("error_code"),
            "cache_hit": bool(body.get("response_cache_hit")),
            "provider_attempts": body.get("provider_trace", {}).get("attempts", 0),
            "provider_tier": body.get("provider_trace", {}).get("model_tier", "complex"),
            "provider_degraded": bool(
                body.get("provider_trace", {}).get("degraded_to_fast", False)
            ),
            "provider_error": body.get("provider_trace", {}).get("last_error_code"),
            "tool_call_count": body.get("tool_call_count", 0),
            "latency_breakdown": body.get("latency_breakdown", {}),
            "request_id": request_id,
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "status": 0,
            "elapsed_ms": round(elapsed, 2),
            "outcome": "client_error",
            "error_code": exc.__class__.__name__,
            "cache_hit": False,
            "provider_attempts": 0,
            "provider_tier": "none",
            "provider_degraded": False,
            "provider_error": None,
            "tool_call_count": 0,
            "latency_breakdown": {},
            "request_id": request_id,
        }


async def run_phase(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    *,
    name: str,
    concurrency: int,
    requests: int,
    same_session: bool,
    force_retrieval: bool,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    common_session = f"{name}-shared-{uuid.uuid4().hex[:8]}"

    async def wrapped(i: int) -> dict[str, Any]:
        async with semaphore:
            session_id = common_session if same_session else f"{name}-{i}-{uuid.uuid4().hex[:6]}"
            request_user = (
                args.user
                if same_session
                else f"{args.user}-{i % max(1, concurrency)}"
            )
            return await one_request(
                client,
                base_url=args.base_url,
                query=args.query,
                tenant=args.tenant,
                user=request_user,
                session_id=session_id,
                force_retrieval=force_retrieval,
                purpose=args.purpose,
            )

    started = time.perf_counter()
    rows = await asyncio.gather(*(wrapped(i) for i in range(requests)))
    wall_seconds = max(0.001, time.perf_counter() - started)
    latencies = [float(row["elapsed_ms"]) for row in rows]
    status_counts = Counter(str(row["status"]) for row in rows)
    error_counts = Counter(str(row.get("error_code") or "none") for row in rows)
    success = sum(1 for row in rows if row["status"] == 200)
    controlled_overload = sum(1 for row in rows if row["status"] in {409, 429, 503, 504})
    provider_latencies = [
        float(row.get("latency_breakdown", {}).get("provider_ms", 0) or 0)
        for row in rows
        if row.get("latency_breakdown", {}).get("provider_ms") is not None
    ]
    provider_tier_counts = Counter(str(row.get("provider_tier") or "none") for row in rows)
    provider_attempt_counts = Counter(str(row.get("provider_attempts", 0)) for row in rows)
    return {
        "name": name,
        "concurrency": concurrency,
        "requests": requests,
        "same_session": same_session,
        "force_retrieval": force_retrieval,
        "success_rate": round(success / max(1, requests), 4),
        "controlled_overload_rate": round(controlled_overload / max(1, requests), 4),
        "acceptable_rate": round(
            (success + controlled_overload) / max(1, requests), 4
        ),
        "throughput_rps": round(requests / wall_seconds, 3),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "p99_ms": round(percentile(latencies, 0.99), 2),
        "max_ms": round(max(latencies), 2),
        "status_counts": dict(status_counts),
        "error_counts": dict(error_counts),
        "provider_tier_counts": dict(provider_tier_counts),
        "provider_attempt_counts": dict(provider_attempt_counts),
        "provider_p50_ms": round(statistics.median(provider_latencies), 2)
        if provider_latencies
        else 0,
        "provider_p95_ms": round(percentile(provider_latencies, 0.95), 2),
        "rows": rows,
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=max(20, args.max_concurrency * 2))
    phases: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        phases.append(
            await run_phase(
                client,
                args,
                name="fresh-c1",
                concurrency=1,
                requests=args.requests,
                same_session=False,
                force_retrieval=True,
            )
        )
        for concurrency in args.concurrency:
            phases.append(
                await run_phase(
                    client,
                    args,
                    name=f"fresh-c{concurrency}",
                    concurrency=concurrency,
                    requests=args.requests,
                    same_session=False,
                    force_retrieval=True,
                )
            )
        phases.append(
            await run_phase(
                client,
                args,
                name="same-session-serialization",
                concurrency=min(args.max_concurrency, 4),
                requests=min(args.requests, 8),
                same_session=True,
                force_retrieval=True,
            )
        )

        # Warm one deterministic session, then measure cache-only latency.
        cache_session = f"cache-{uuid.uuid4().hex[:8]}"
        await one_request(
            client,
            base_url=args.base_url,
            query=args.query,
            tenant=args.tenant,
            user=args.user,
            session_id=cache_session,
            force_retrieval=True,
            purpose=args.purpose,
        )
        cache_rows = []
        for _ in range(args.cache_requests):
            cache_rows.append(
                await one_request(
                    client,
                    base_url=args.base_url,
                    query=args.query,
                    tenant=args.tenant,
                    user=args.user,
                    session_id=cache_session,
                    force_retrieval=False,
                    purpose=args.purpose,
                )
            )
        cache_latencies = [float(row["elapsed_ms"]) for row in cache_rows]
        phases.append(
            {
                "name": "cache-hot",
                "concurrency": 1,
                "requests": len(cache_rows),
                "same_session": True,
                "force_retrieval": False,
                "success_rate": round(
                    sum(1 for row in cache_rows if row["status"] == 200) / max(1, len(cache_rows)),
                    4,
                ),
                "cache_hit_rate": round(
                    sum(1 for row in cache_rows if row["cache_hit"]) / max(1, len(cache_rows)),
                    4,
                ),
                "p50_ms": round(statistics.median(cache_latencies), 2),
                "p95_ms": round(percentile(cache_latencies, 0.95), 2),
                "p99_ms": round(percentile(cache_latencies, 0.99), 2),
                "max_ms": round(max(cache_latencies), 2),
                "rows": cache_rows,
            }
        )

    return {
        "base_url": args.base_url,
        "query": args.query,
        "phases": phases,
        "recommended_interpretation": {
            "steady_state": (
                "Use c1/c2 as the primary production baseline because the repo default "
                "AGENT_MAX_CONCURRENT_REQUESTS is 2."
            ),
            "saturation": (
                "At c4/c8, controlled 409/429/503 is preferable to crashes or "
                "unbounded latency."
            ),
            "cache": (
                "Hot-cache p95 should be far below fresh-generation p95 and "
                "cache_hit_rate should be 1.0."
            ),
            "same_session": (
                "The production default rejects overlapping work for one session. A 409 "
                "SESSION_BUSY is a controlled outcome and avoids minute-long serialized queues."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrency/load sweep for the v6 API")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--query",
        default=(
            "Using only the indexed Agentic RAG course, explain the difference between "
            "Basic RAG and Agentic RAG. Cite every factual sentence."
        ),
    )
    parser.add_argument("--purpose", default="research")
    parser.add_argument("--tenant", default="public")
    parser.add_argument("--user", default="load-evaluator")
    parser.add_argument("--requests", type=int, default=6)
    parser.add_argument("--cache-requests", type=int, default=5)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[2, 4, 8])
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/performance/load-sweep.json"),
    )
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    args.max_concurrency = max(args.concurrency or [1])
    report = asyncio.run(main_async(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for phase in report["phases"]:
        print(
            f"{phase['name']}: success={phase.get('success_rate', 0):.1%} "
            f"controlled={phase.get('controlled_overload_rate', 0):.1%} "
            f"acceptable={phase.get('acceptable_rate', phase.get('success_rate', 0)):.1%} "
            f"p50={phase.get('p50_ms', 0):.0f}ms p95={phase.get('p95_ms', 0):.0f}ms "
            f"provider_p95={phase.get('provider_p95_ms', 0):.0f}ms "
            f"tiers={phase.get('provider_tier_counts', {})}"
        )
    print(f"report: {args.output}")


if __name__ == "__main__":
    main()
