from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable

from nvidia_agentic_rag.schemas import ProvenanceAudit, ProvenanceDerivation, SourceReference

_Q2 = Decimal("0.01")


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise InvalidOperation
    return Decimal(str(value))


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_Q2, rounding=ROUND_HALF_UP)


def _safe_ratio(numerator: object, denominator: object) -> Decimal | None:
    den = _decimal(denominator or 0)
    if den == 0:
        return None
    return _round2(_decimal(numerator or 0) / den)


def _customer_aov(inputs: dict[str, object]) -> Decimal | None:
    return _safe_ratio(inputs.get("total_amount"), inputs.get("total_orders"))


def _revenue_per_unit(inputs: dict[str, object]) -> Decimal | None:
    return _safe_ratio(inputs.get("total_revenue"), inputs.get("total_quantity"))


def _average_units(inputs: dict[str, object]) -> Decimal | None:
    return _safe_ratio(inputs.get("total_quantity"), inputs.get("total_orders"))


def _absolute_difference(inputs: dict[str, object]) -> Decimal:
    return _round2(
        abs(
            _decimal(inputs.get("top_book_revenue") or 0)
            - _decimal(inputs.get("customer_total_spending") or 0)
        )
    )


def _percentage_difference(inputs: dict[str, object]) -> Decimal | None:
    denominator = _decimal(inputs.get("customer_total_spending") or 0)
    if denominator == 0:
        return None
    return _round2(_decimal(inputs.get("absolute_difference") or 0) / denominator * 100)


def _amount_revenue_difference(inputs: dict[str, object]) -> Decimal:
    return _round2(
        _decimal(inputs.get("customer_total_amount") or 0)
        - _decimal(inputs.get("book_total_revenue") or 0)
    )


def _quantity_difference(inputs: dict[str, object]) -> Decimal:
    return _decimal(inputs.get("customer_total_quantity") or 0) - _decimal(
        inputs.get("book_total_quantity") or 0
    )


FormulaFn = Callable[[dict[str, object]], Decimal | None]

_FORMULAS: dict[str, tuple[str, FormulaFn]] = {
    "customer.average_spending_per_order.v1": (
        "total_amount / total_orders",
        _customer_aov,
    ),
    "customer.average_units_per_order.v1": (
        "total_quantity / total_orders",
        _average_units,
    ),
    "book.revenue_per_unit.v1": (
        "total_revenue / total_quantity",
        _revenue_per_unit,
    ),
    "book.average_units_per_order.v1": (
        "total_quantity / total_orders",
        _average_units,
    ),
    "comparison.absolute_difference.v1": (
        "abs(top_book_revenue - customer_total_spending)",
        _absolute_difference,
    ),
    "comparison.percentage_difference.v1": (
        "absolute_difference / customer_total_spending * 100",
        _percentage_difference,
    ),
    "reconciliation.amount_revenue.v1": (
        "SUM(customer.total_amount) - SUM(book.total_revenue)",
        _amount_revenue_difference,
    ),
    "reconciliation.quantity.v1": (
        "SUM(customer.total_quantity) - SUM(book.total_quantity)",
        _quantity_difference,
    ),
}


def validate_provenance(
    derivations: list[ProvenanceDerivation],
    sources: list[SourceReference],
) -> ProvenanceAudit:
    """Recompute allowlisted derived metrics and validate their source lineage.

    This is intentionally not an expression evaluator. Formula IDs and implementations are
    application-owned, so an LLM cannot smuggle arbitrary arithmetic or SQL into validation.
    """

    if not derivations:
        return ProvenanceAudit(applicable=False, valid=True)

    available = {source.citation_id for source in sources}
    unknown: set[str] = set()
    invalid_formula_ids: list[str] = []
    mismatched_outputs: list[str] = []
    errors: list[str] = []
    validated = 0

    for derivation in derivations:
        unknown.update(set(derivation.source_citation_ids) - available)
        formula_entry = _FORMULAS.get(derivation.formula_id)
        if formula_entry is None:
            invalid_formula_ids.append(derivation.formula_id)
            continue
        expected_formula, function = formula_entry
        if derivation.formula.strip() != expected_formula:
            invalid_formula_ids.append(derivation.formula_id)
            continue
        if not derivation.source_citation_ids:
            errors.append(f"Derivation '{derivation.output_name}' has no source citations.")
            continue
        try:
            expected = function(derivation.inputs)
            actual = None if derivation.value is None else _round2(_decimal(derivation.value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            errors.append(f"Derivation '{derivation.output_name}' could not be recomputed: {exc}")
            continue
        if expected != actual:
            mismatched_outputs.append(derivation.output_name)
            continue
        validated += 1

    if unknown:
        errors.append(f"Derived metrics reference unknown citation IDs: {sorted(unknown)}")
    if invalid_formula_ids:
        errors.append(f"Unrecognized or altered formula IDs: {sorted(set(invalid_formula_ids))}")
    if mismatched_outputs:
        errors.append(f"Derived values failed recomputation: {sorted(set(mismatched_outputs))}")
    if validated != len(derivations):
        errors.append(
            f"Only {validated} of {len(derivations)} derived metrics passed provenance validation."
        )

    return ProvenanceAudit(
        applicable=True,
        valid=not errors,
        derivation_count=len(derivations),
        validated_count=validated,
        unknown_citation_ids=sorted(unknown),
        invalid_formula_ids=sorted(set(invalid_formula_ids)),
        mismatched_outputs=sorted(set(mismatched_outputs)),
        errors=errors,
    )
