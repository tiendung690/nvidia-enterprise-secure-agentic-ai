from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evaluation/performance_cases.jsonl"


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(value * len(ordered)) - 1))
    return ordered[index]


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def post_case(
    client: httpx.AsyncClient,
    base_url: str,
    case: dict[str, Any],
    *,
    session_id: str,
    force_retrieval: bool,
) -> dict[str, Any]:
    payload = {
        "query": case["query"],
        "session_id": session_id,
        "purpose": case.get("purpose", "research"),
        "answer_mode": case.get("answer_mode", "enterprise_factual"),
        "force_retrieval": force_retrieval,
    }
    started = time.perf_counter()
    response = await client.post(
        f"{base_url}/v1/chat",
        json=payload,
        headers={
            "X-User-Id": "performance-evaluator",
            "X-Tenant-Id": "public",
            "X-Clearance": "public",
            "X-Request-ID": f"perf-{case['id']}-{uuid.uuid4().hex[:8]}",
        },
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    expected_tools = set(case.get("expected_tools", []))
    actual_tools = set(body.get("tools", []))
    citation = body.get("citation_audit", {})
    applicable = citation.get("applicable", True)
    citation_pass = (not applicable) or citation.get("valid") is True
    expected_outcome = case.get("expected_outcome")
    return {
        "case_id": case["id"],
        "session_id": session_id,
        "status": response.status_code,
        "elapsed_ms": elapsed_ms,
        "request_outcome": body.get("request_outcome"),
        "error_code": body.get("error_code"),
        "tools": sorted(actual_tools),
        "tool_call_count": body.get("tool_call_count", 0),
        "cache_hit": bool(body.get("response_cache_hit")),
        "citation_valid": citation_pass,
        "citation_coverage": citation.get("coverage"),
        "source_count": len(body.get("sources", [])),
        "provider_attempts": body.get("provider_trace", {}).get("attempts", 0),
        "provider_retries": body.get("provider_trace", {}).get("retry_count", 0),
        "provider_tier": body.get("provider_trace", {}).get("model_tier", "complex"),
        "provider_degraded": bool(
            body.get("provider_trace", {}).get("degraded_to_fast", False)
        ),
        "provider_error": body.get("provider_trace", {}).get("last_error_code"),
        "latency_breakdown": body.get("latency_breakdown", {}),
        "pass": (
            response.status_code == case.get("expected_status", 200)
            and expected_tools.issubset(actual_tools)
            and (expected_outcome is None or body.get("request_outcome") == expected_outcome)
            and citation_pass
            and elapsed_ms <= case.get("max_latency_ms", 120_000)
        ),
    }


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    cases = {item["id"]: item for item in load_cases(args.cases)}
    timeout = httpx.Timeout(args.http_timeout_seconds)
    limits = httpx.Limits(max_connections=max(20, args.concurrency * 2))
    rows: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        for case_id in ("P01", "P04", "P06", "P07"):
            case = cases[case_id]
            session = f"{case_id.lower()}-{uuid.uuid4().hex[:8]}"
            row = await post_case(
                client,
                args.base_url,
                case,
                session_id=session,
                force_retrieval=True,
            )
            rows.append(row)
            if case_id == "P01" and row["status"] == 200:
                cached = await post_case(
                    client,
                    args.base_url,
                    case,
                    session_id=session,
                    force_retrieval=False,
                )
                cached["case_id"] = "P02"
                cached["pass"] = (
                    cached["status"] == 200
                    and cached["cache_hit"]
                    and cached["tool_call_count"] == 0
                    and cached["elapsed_ms"] < args.cache_p95_gate_ms
                )
                rows.append(cached)

        concurrent_case = cases["P09"]
        concurrent_rows = await asyncio.gather(
            *[
                post_case(
                    client,
                    args.base_url,
                    concurrent_case,
                    session_id=f"p09-{index}-{uuid.uuid4().hex[:6]}",
                    force_retrieval=True,
                )
                for index in range(args.concurrency)
            ]
        )
        rows.extend(concurrent_rows)

    fresh = [row["elapsed_ms"] for row in rows if not row["cache_hit"]]
    cached = [row["elapsed_ms"] for row in rows if row["cache_hit"]]
    p09 = [row for row in rows if row["case_id"] == "P09"]
    summary = {
        "row_count": len(rows),
        "pass_rate": round(statistics.mean(float(row["pass"]) for row in rows), 4),
        "fresh_p50_ms": round(statistics.median(fresh), 2) if fresh else 0,
        "fresh_p95_ms": round(percentile(fresh, 0.95), 2),
        "cache_p95_ms": round(percentile(cached, 0.95), 2),
        "concurrency": args.concurrency,
        "concurrency_success_rate": round(
            statistics.mean(float(row["status"] == 200) for row in p09), 4
        )
        if p09
        else 0,
        "citation_valid_rate": round(
            statistics.mean(float(row["citation_valid"]) for row in rows), 4
        ),
    }
    gates = {
        "all_cases_pass": all(row["pass"] for row in rows),
        "cache_p95_gate": summary["cache_p95_ms"] < args.cache_p95_gate_ms,
        "concurrency_success_100pct": summary["concurrency_success_rate"] == 1.0,
        "citation_valid_100pct": summary["citation_valid_rate"] == 1.0,
    }
    return {"summary": summary, "gates": gates, "passed": all(gates.values()), "rows": rows}


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Production Performance Suite",
        "",
        f"Overall: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- Pass rate: {summary['pass_rate']:.1%}",
        f"- Fresh p50: {summary['fresh_p50_ms']:.0f} ms",
        f"- Fresh p95: {summary['fresh_p95_ms']:.0f} ms",
        f"- Cache p95: {summary['cache_p95_ms']:.0f} ms",
        f"- Concurrency success: {summary['concurrency_success_rate']:.1%}",
        f"- Citation-valid rate: {summary['citation_valid_rate']:.1%}",
        "",
        "| Case | Status | Outcome/Error | ms | Tier | Tools | Cache | Citation | Pass |",
        "|---|---:|---|---:|---|---|---:|---:|---:|",
    ]
    for row in report["rows"]:
        outcome = row.get("request_outcome") or row.get("error_code") or "-"
        lines.append(
            f"| {row['case_id']} | {row['status']} | {outcome} | {row['elapsed_ms']:.0f} | "
            f"{row.get('provider_tier', '-')} | {', '.join(row['tools']) or '-'} | "
            f"{row['cache_hit']} | "
            f"{row['citation_valid']} | {row['pass']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--http-timeout-seconds", type=float, default=180)
    parser.add_argument("--cache-p95-gate-ms", type=float, default=500)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/performance")
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")

    report = asyncio.run(evaluate(args))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "performance-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (args.output_dir / "performance-report.md").write_text(
        markdown(report), encoding="utf-8"
    )
    print(json.dumps(report["summary"], indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
