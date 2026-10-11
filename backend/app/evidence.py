"""Evidence states describe saved source observations, never inferred absence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.schemas import ItemCandidate

FIELD_STATES = {"present", "explicitly_not_published", "blank_in_source", "unverified", "unknown"}
ITEM_FIELDS = (
    "product_name", "category", "brand", "model", "quantity", "quantity_unit",
    "unit_price", "total_price",
)


def has_field_evidence(evidence: object) -> bool:
    return isinstance(evidence, dict) and all(
        isinstance(evidence.get(key), str) and evidence[key].strip()
        for key in ("source_file", "source_location", "source_evidence")
    )


def field_state(value: Any, saved: object, evidence: object) -> str:
    """Conservatively normalize legacy or inconsistent stored provenance."""
    populated = value is not None and value != ""
    if not isinstance(saved, str) or saved not in FIELD_STATES:
        return "unverified" if populated else "unknown"
    if populated:
        return "present" if saved == "present" and has_field_evidence(evidence) else "unverified"
    if saved in {"explicitly_not_published", "blank_in_source"}:
        return saved if has_field_evidence(evidence) else "unknown"
    return "unverified" if saved in {"present", "unverified"} else "unknown"


def carry_field_evidence(
    target: ItemCandidate, changes: dict, source: ItemCandidate,
) -> ItemCandidate:
    """Move evidence with changed values; never inherit a former empty status."""
    states = dict(target.field_status)
    evidence = dict(target.field_evidence)
    for field in ITEM_FIELDS:
        if field not in changes or changes[field] == getattr(target, field):
            continue
        source_evidence = source.field_evidence.get(field)
        states[field] = field_state(changes[field], source.field_status.get(field), source_evidence)
        evidence.pop(field, None)
        if has_field_evidence(source_evidence):
            evidence[field] = dict(source_evidence)
    return target.model_copy(update={**changes, "field_status": states, "field_evidence": evidence})
