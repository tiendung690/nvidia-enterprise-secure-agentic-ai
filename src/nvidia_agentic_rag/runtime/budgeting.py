from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

QueryComplexity = Literal["simple", "comparison", "long"]


@dataclass(frozen=True)
class AnswerBudget:
    complexity: QueryComplexity
    max_words: int
    max_sources: int


def classify_query_complexity(query: str) -> QueryComplexity:
    normalized = query.casefold()
    long_signals = (
        "complete lifecycle",
        "end-to-end",
        "step by step",
        "architecture",
        "design system",
        "cover reasoning",
        "evaluation, and security",
        "all components",
    )
    comparison_signals = (
        "compare",
        "versus",
        " vs ",
        "difference",
        "trade-off",
        "tradeoff",
        "across",
    )
    if len(query) > 900 or any(signal in normalized for signal in long_signals):
        return "long"
    if len(query) > 420 or any(signal in normalized for signal in comparison_signals):
        return "comparison"
    return "simple"


def resolve_answer_budget(
    query: str,
    *,
    simple_words: int,
    comparison_words: int,
    long_words: int,
    simple_sources: int,
    comparison_sources: int,
    long_sources: int,
) -> AnswerBudget:
    complexity = classify_query_complexity(query)
    if complexity == "simple":
        return AnswerBudget(complexity, simple_words, simple_sources)
    if complexity == "comparison":
        return AnswerBudget(complexity, comparison_words, comparison_sources)
    return AnswerBudget(complexity, long_words, long_sources)


def build_response_contract(budget: AnswerBudget) -> str:
    return (
        "\n\nInternal response contract (application-enforced):\n"
        f"- Query complexity: {budget.complexity}.\n"
        f"- Keep the final answer within approximately {budget.max_words} words unless the user "
        "explicitly requests a longer artifact.\n"
        "- Put citations directly at the end of every factual sentence or Markdown table row.\n"
        "- Do not add a repetitive uncited summary.\n"
        "- Distinguish source-derived facts from repository runtime observations.\n"
        "- Treat ReAct and Plan-and-Execute as alternative reasoning strategies, not one merged "
        "execution flow.\n"
        "- Do not expand acronyms unless current-turn evidence explicitly defines the expansion."
    )
