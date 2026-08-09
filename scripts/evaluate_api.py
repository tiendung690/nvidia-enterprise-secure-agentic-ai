from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation/golden_cases.jsonl"


def post_json(url: str, payload: dict[str, Any], user_id: str) -> tuple[int, dict[str, Any], float]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-User-Id": user_id},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            status = response.status
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        data = json.loads(exc.read().decode("utf-8"))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return status, data, elapsed_ms


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile_value * len(ordered)) - 1))
    return ordered[index]


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate(base_url: str, dataset: Path) -> dict[str, Any]:
    cases = load_cases(dataset)
    rows: list[dict[str, Any]] = []
    fresh_latencies: list[float] = []
    cache_latencies: list[float] = []

    for case in cases:
        session_id = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
        payload = {
            "query": case["query"],
            "session_id": session_id,
            "force_retrieval": True,
        }
        status, response, elapsed_ms = post_json(
            f"{base_url}/v1/chat", payload, "quality-evaluator"
        )
        fresh_latencies.append(elapsed_ms)
        tools = response.get("tools", [])
        answer = response.get("answer", "")
        required_terms = case.get("required_terms", [])
        term_hits = [term for term in required_terms if term.casefold() in answer.casefold()]
        expected_tool = case["expected_tool"]
        source_count = len(response.get("sources", []))
        citation_valid = response.get("citation_audit", {}).get("valid", True)

        repeat_payload = {"query": case["query"], "session_id": session_id}
        repeat_status, repeat_response, repeat_elapsed_ms = post_json(
            f"{base_url}/v1/chat", repeat_payload, "quality-evaluator"
        )
        cache_latencies.append(repeat_elapsed_ms)

        rows.append(
            {
                "id": case["id"],
                "status": status,
                "tool_pass": expected_tool in tools,
                "tools": tools,
                "term_coverage": len(term_hits) / max(1, len(required_terms)),
                "source_count": source_count,
                "citation_valid": citation_valid,
                "fresh_latency_ms": round(elapsed_ms, 2),
                "cache_status": repeat_status,
                "cache_hit": bool(repeat_response.get("response_cache_hit")),
                "cache_latency_ms": round(repeat_elapsed_ms, 2),
            }
        )

    routing_accuracy = statistics.mean(float(row["tool_pass"]) for row in rows)
    term_coverage = statistics.mean(row["term_coverage"] for row in rows)
    citation_rate = statistics.mean(float(row["citation_valid"]) for row in rows)
    cache_hit_rate = statistics.mean(float(row["cache_hit"]) for row in rows)
    report = {
        "summary": {
            "case_count": len(rows),
            "routing_accuracy": round(routing_accuracy, 4),
            "required_term_coverage": round(term_coverage, 4),
            "citation_valid_rate": round(citation_rate, 4),
            "cache_hit_rate": round(cache_hit_rate, 4),
            "fresh_latency_p50_ms": round(statistics.median(fresh_latencies), 2),
            "fresh_latency_p95_ms": round(percentile(fresh_latencies, 0.95), 2),
            "cache_latency_p95_ms": round(percentile(cache_latencies, 0.95), 2),
        },
        "cases": rows,
    }
    report["gates"] = {
        "routing_accuracy_100pct": routing_accuracy == 1.0,
        "required_term_coverage_gte_90pct": term_coverage >= 0.90,
        "citation_valid_rate_100pct": citation_rate == 1.0,
        "cache_hit_rate_100pct": cache_hit_rate == 1.0,
        "cache_latency_p95_lt_500ms": report["summary"]["cache_latency_p95_ms"] < 500,
        "fresh_latency_p95_lt_60000ms": report["summary"]["fresh_latency_p95_ms"] < 60_000,
    }
    report["passed"] = all(report["gates"].values())
    return report


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Live API Quality Evaluation",
        "",
        f"Overall gate: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "## Summary",
        "",
        f"- Routing accuracy: {summary['routing_accuracy']:.1%}",
        f"- Required-term coverage: {summary['required_term_coverage']:.1%}",
        f"- Citation-valid rate: {summary['citation_valid_rate']:.1%}",
        f"- Cache-hit rate: {summary['cache_hit_rate']:.1%}",
        f"- Fresh latency p95: {summary['fresh_latency_p95_ms']:.0f} ms",
        f"- Cache latency p95: {summary['cache_latency_p95_ms']:.0f} ms",
        "",
        "## Cases",
        "",
        "| Case | Tool | Terms | Sources | Citation | Fresh ms | Cache ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["cases"]:
        lines.append(
            f"| {row['id']} | {'PASS' if row['tool_pass'] else 'FAIL'} | "
            f"{row['term_coverage']:.0%} | {row['source_count']} | "
            f"{'PASS' if row['citation_valid'] else 'FAIL'} | "
            f"{row['fresh_latency_ms']:.0f} | {row['cache_latency_ms']:.0f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/evaluation")
    args = parser.parse_args()

    report = evaluate(args.base_url.rstrip("/"), args.dataset)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "live-quality-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (args.output_dir / "live-quality-report.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
