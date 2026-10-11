"""Read-only, conservative comparisons of saved notice snapshots.

Database row IDs identify evidence links, not identity across two imports. A
tentative correspondence is always visible as requiring human confirmation.
This module neither reads files nor calls the extraction or evaluation layers.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

_NUMERIC_FIELDS = {
    "project_budget", "announced_total_award", "budget_amount", "award_amount",
    "package_budget", "package_award_total", "quantity", "unit_price", "total_price",
    "byte_size", "amount", "total_amount", "成交金额", "预算金额", "数量", "单价", "总价",
}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "caption", "dd", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "th", "thead", "tr", "ul",
}
_ENTITY_FIELDS = {
    "package": ("package_code", "package_name", "package_budget", "package_award_total"),
    "bidder": ("package_code", "organization_name", "outcome", "consortium_members"),
    "award": ("package_code", "organization_name", "award_amount"),
    "item": (
        "package_code", "product_name", "category", "brand", "model", "quantity",
        "quantity_unit", "unit_price", "total_price",
    ),
    "source_file": ("source_file", "sha256", "byte_size", "kind"),
    "body": ("source_file", "text"),
}
_PROVENANCE_FIELDS = ("source_file", "source_location", "source_evidence", "source_sha256")
_UNCERTAIN_IDENTITIES = {
    "identity_ambiguous", "manual_link_required", "pending", "unconfirmed", "candidate",
}
_IGNORED_ROW_FIELDS = {"id", "notice_id", "project_id", "package_id", "created_at"}


def _decimal(value: Any) -> str | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    if number == 0:
        return "0"
    # Fixed notation avoids context-dependent Decimal.normalize() rounding.
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _text(value: str) -> str:
    # Collapsing, rather than deleting, whitespace preserves "AB" versus "A B"
    # and "10" versus "1 0". No case folding or guessed package normalization.
    return re.sub(r"\s+", " ", value).strip()


def _body_text(value: str) -> str:
    if not re.search(r"<[!/a-zA-Z]", value):
        return _text(value)
    soup = BeautifulSoup(value, "html.parser")
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag):
            if node.name in {"script", "style"}:
                return
            block = node.name in _BLOCK_TAGS
            if block:
                parts.append("\n")
            for child in node.children:
                walk(child)
            if block:
                parts.append("\n")

    walk(soup)
    return _text("".join(parts))


def normalize_value(value: Any, field: str = "") -> Any:
    """Return a JSON-compatible semantic value without altering the saved value.

    Numeric equivalence applies to numeric objects and known amount/quantity
    fields, never to identifiers such as package codes or model numbers. JSON
    objects ignore key order; arrays keep order and duplicate entries.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {str(key): normalize_value(entry, str(key))
                for key, entry in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [normalize_value(entry, field) for entry in value]
    if isinstance(value, (Decimal, int, float)):
        return _decimal(value) or str(value)
    if isinstance(value, str):
        text = _text(value)
        if field in {"body", "text", "body_text"}:
            return _body_text(value)
        if field in _NUMERIC_FIELDS:
            # Recognize only valid thousands grouping, never remove arbitrary
            # spaces or punctuation from numbers and accidentally change them.
            if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
                text = text.replace(",", "")
            numeric = _decimal(text)
            if numeric is not None:
                return numeric
        if field == "json" or field.endswith("_json"):
            try:
                return normalize_value(json.loads(value))
            except (ValueError, TypeError):
                pass
        return text
    return value


def _json_value(value: Any) -> Any:
    """Preserve displayed decimal formatting while making responses serializable."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(entry) for entry in value]
    return value


def _signature(value: Any) -> str:
    return json.dumps(normalize_value(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _row_signature(row: dict[str, Any]) -> str:
    return _signature({key: value for key, value in row.items() if key not in _IGNORED_ROW_FIELDS})


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _tuple_key(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    values = [normalize_value(row.get(field), field) for field in fields]
    return _signature(values) if all(_present(value) for value in values) else None


def _stable_key(row: dict[str, Any]) -> str | None:
    for field in ("stable_id", "entity_id", "official_id", "source_unique_id"):
        if _present(row.get(field)):
            return f"{field}:{_signature(row[field])}"
    return None


def _natural_key(entity_type: str, row: dict[str, Any]) -> str | None:
    if entity_type == "package":
        return _tuple_key(row, ("package_code",))
    if entity_type in {"bidder", "award"}:
        return _tuple_key(row, ("package_code", "organization_name"))
    if entity_type == "item":
        if not _present(row.get("product_name")) or not _present(row.get("package_code")):
            return None
        # Missing brand/model are not invented. The full key can still be
        # duplicated; matching below operates on multisets instead of dict rows.
        return _signature([row.get(field) for field in
                           ("package_code", "product_name", "brand", "model")])
    return _tuple_key(row, ("source_file",))


def _candidate_keys(entity_type: str) -> list[Callable[[dict[str, Any]], str | None]]:
    location = lambda row: _tuple_key(row, ("source_file", "source_location"))
    if entity_type == "package":
        return [location, lambda row: _tuple_key(row, ("package_name",))]
    if entity_type in {"bidder", "award"}:
        return [location, lambda row: _tuple_key(row, ("organization_name",))]
    if entity_type == "item":
        return [
            location,
            lambda row: _tuple_key(row, ("package_code", "product_name")),
            lambda row: _tuple_key(row, ("product_name", "brand", "model")),
        ]
    if entity_type == "source_file":
        return [lambda row: _tuple_key(row, ("sha256",))]
    return []


def _match_rows(
    entity_type: str, before: list[dict[str, Any]], after: list[dict[str, Any]],
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None, bool]]:
    remaining_before = set(range(len(before)))
    remaining_after = set(range(len(after)))
    pairs: list[tuple[dict[str, Any] | None, dict[str, Any] | None, bool]] = []
    ambiguous_before: set[int] = set()
    ambiguous_after: set[int] = set()
    natural_counts_before = Counter(_natural_key(entity_type, row) for row in before)
    natural_counts_after = Counter(_natural_key(entity_type, row) for row in after)

    def pair_on(key_function: Callable, *, tentative: bool = False, exact: bool = False) -> None:
        left: dict[str, list[int]] = defaultdict(list)
        right: dict[str, list[int]] = defaultdict(list)
        for index in sorted(remaining_before):
            key = key_function(before[index])
            if key is not None:
                left[key].append(index)
        for index in sorted(remaining_after):
            key = key_function(after[index])
            if key is not None:
                right[key].append(index)
        for key in sorted(left.keys() & right.keys()):
            old_indices, new_indices = left[key], right[key]
            if exact:
                # Equal saved observations can cancel as a multiset. This never
                # pairs unequal rows by their list positions or drops duplicates.
                indices = zip(old_indices, new_indices, strict=False)
            elif len(old_indices) == len(new_indices) == 1:
                indices = [(old_indices[0], new_indices[0])]
            else:
                ambiguous_before.update(old_indices)
                ambiguous_after.update(new_indices)
                continue
            for old_index, new_index in indices:
                old, new = before[old_index], after[new_index]
                old_stable, new_stable = _stable_key(old), _stable_key(new)
                if old_stable and new_stable and old_stable != new_stable:
                    # A shared name or location must not override conflicting
                    # explicitly stable identities.
                    ambiguous_before.add(old_index)
                    ambiguous_after.add(new_index)
                    continue
                natural_key = _natural_key(entity_type, old)
                repeated = (natural_key is not None and
                            max(natural_counts_before[natural_key],
                                natural_counts_after[natural_key]) > 1)
                manual = tentative or (repeated and not exact)
                pairs.append((old, new, manual))
                remaining_before.remove(old_index)
                remaining_after.remove(new_index)

    pair_on(_row_signature, exact=True)
    pair_on(_stable_key)
    pair_on(lambda row: _natural_key(entity_type, row))
    for key_function in _candidate_keys(entity_type):
        pair_on(key_function, tentative=True)
    pairs.extend((before[index], None, index in ambiguous_before)
                 for index in sorted(remaining_before))
    pairs.extend((None, after[index], index in ambiguous_after)
                 for index in sorted(remaining_after))
    return pairs


def _source(version: dict[str, Any], row: dict[str, Any] | None,
            field: str = "") -> dict[str, Any] | None:
    if row is None:
        return None
    evidence = row.get("field_evidence", {}).get(field, {})
    if not isinstance(evidence, dict):
        evidence = {}
    result = {key: version[key] for key in ("version_id", "notice_id", "dataset_id")
              if version.get(key) is not None}
    if row.get("id") is not None:
        result["candidate_id"] = row["id"]
    for key in _PROVENANCE_FIELDS:
        value = evidence.get(key, row.get(key))
        if value is not None:
            result[key] = _json_value(value)
    return result or None


def _key(entity_type: str, row: dict[str, Any]) -> str:
    identity = _stable_key(row) or _natural_key(entity_type, row)
    if identity is None:
        identity = _tuple_key(row, ("source_file", "source_location")) or "unidentified"
    return f"{entity_type}:{identity}"


def compare_snapshots(
    before: dict[str, Any], after: dict[str, Any], *, include_unchanged: bool = False,
) -> dict[str, Any]:
    """Compare immutable version details; never infer notice or entity identity.

    Callers must select versions belonging to the same dataset and version group.
    Added/removed entities are emitted as whole rows (``field='*'``); matched
    entities produce field changes, with provenance changes counted separately.
    """
    for field in ("dataset_id", "group_id"):
        if (before.get(field) is not None and after.get(field) is not None
                and before[field] != after[field]):
            raise ValueError(f"versions must belong to the same {field}")
    old_snapshot = before.get("snapshot", {})
    new_snapshot = after.get("snapshot", {})
    changes: list[dict[str, Any]] = []
    global_manual = any(version.get("identity_status") in _UNCERTAIN_IDENTITIES
                        for version in (before, after))

    def emit(entity_type: str, entity_key: str, field: str, old_value: Any,
             new_value: Any, old_row: dict[str, Any] | None,
             new_row: dict[str, Any] | None, *, manual: bool = False,
             provenance: bool = False, classification: str | None = None,
             row_change: str | None = None, source_field: str | None = None) -> None:
        equal = normalize_value(old_value, field) == normalize_value(new_value, field)
        raw_equal = _json_value(old_value) == _json_value(new_value)
        if row_change is not None:
            change_type = row_change
        elif equal and raw_equal:
            if not include_unchanged:
                return
            change_type = "unchanged"
        elif not _present(old_value) and _present(new_value):
            change_type = "added"
        elif _present(old_value) and not _present(new_value):
            change_type = "removed"
        else:
            change_type = "changed"
        category = classification or (
            "unchanged" if change_type == "unchanged"
            else "format_only" if equal and row_change is None
            else "provenance_only" if provenance
            else "possible_semantic"
        )
        changes.append({
            "entity_type": entity_type, "entity_key": entity_key, "field": field,
            "change_type": change_type, "before": _json_value(old_value),
            "after": _json_value(new_value),
            "before_source": _source(before, old_row, source_field or field),
            "after_source": _source(after, new_row, source_field or field),
            "requires_manual_confirmation": bool(manual or global_manual),
            "classification": category,
        })

    old_metadata = old_snapshot.get("metadata", {})
    new_metadata = new_snapshot.get("metadata", {})
    old_metadata_source = {"field_evidence": old_snapshot.get("metadata_evidence", {})}
    new_metadata_source = {"field_evidence": new_snapshot.get("metadata_evidence", {})}
    for field in sorted(old_metadata.keys() | new_metadata.keys()):
        states = [snapshot.get("metadata_field_status", {}).get(field)
                  for snapshot in (old_snapshot, new_snapshot)]
        emit("metadata", "notice", field, old_metadata.get(field), new_metadata.get(field),
             old_metadata_source, new_metadata_source,
             manual=any(state in {"unverified", "unknown"} for state in states))
    for collection in ("metadata_evidence", "metadata_field_status"):
        old_values, new_values = old_snapshot.get(collection, {}), new_snapshot.get(collection, {})
        for field in sorted(old_values.keys() | new_values.keys()):
            emit("metadata", "notice", f"{collection}.{field}", old_values.get(field),
                 new_values.get(field), old_metadata_source, new_metadata_source,
                 provenance=True, source_field=field)

    for entity_type, collection in (
        ("body", "body"), ("source_file", "source_files"), ("package", "packages"),
        ("bidder", "bidders"), ("award", "awards"), ("item", "items"),
    ):
        keys_used: Counter = Counter()
        pairs = _match_rows(entity_type, old_snapshot.get(collection, []),
                            new_snapshot.get(collection, []))
        for old, new, manual in pairs:
            key = _key(entity_type, old if old is not None else new)
            keys_used[key] += 1
            if keys_used[key] > 1:
                key = f"{key}#{keys_used[key]}"
            if old is None or new is None:
                emit(entity_type, key, "*", old, new, old, new, manual=manual,
                     row_change="added" if old is None else "removed")
                continue
            for field in _ENTITY_FIELDS[entity_type]:
                if field not in old and field not in new:
                    continue
                provenance = field == "source_file"
                classification = None
                field_manual = manual
                if entity_type == "source_file" and field in {"sha256", "byte_size"}:
                    if (old.get("normalized_sha256") and
                            old["normalized_sha256"] == new.get("normalized_sha256") and
                            normalize_value(old.get(field), field) !=
                            normalize_value(new.get(field), field)):
                        classification = "format_only"
                    elif normalize_value(old.get(field), field) != normalize_value(
                        new.get(field), field,
                    ):
                        # A changed binary digest cannot establish whether the
                        # underlying content or merely its container changed.
                        field_manual = True
                states = [row.get("field_status", {}).get(field) for row in (old, new)]
                field_manual |= any(state in {"unverified", "unknown"} for state in states)
                emit(entity_type, key, field, old.get(field), new.get(field), old, new,
                     manual=field_manual, provenance=provenance, classification=classification)
            if entity_type != "source_file":
                for field in _PROVENANCE_FIELDS:
                    if (field in _ENTITY_FIELDS[entity_type]
                            or field not in old and field not in new):
                        continue
                    emit(entity_type, key, field, old.get(field), new.get(field), old, new,
                         manual=manual, provenance=True)
                for field in ("field_evidence", "field_status"):
                    old_values, new_values = old.get(field, {}), new.get(field, {})
                    for candidate_field in sorted(old_values.keys() | new_values.keys()):
                        emit(entity_type, key, f"{field}.{candidate_field}",
                             old_values.get(candidate_field), new_values.get(candidate_field),
                             old, new, manual=manual, provenance=True, source_field=candidate_field)

    classification_counts = Counter(change["classification"] for change in changes)
    return {
        "before_version_id": before.get("version_id"),
        "after_version_id": after.get("version_id"),
        "changes": changes,
        "summary": {
            "total": len(changes), "semantic": classification_counts["possible_semantic"],
            "format_only": classification_counts["format_only"],
            "provenance_only": classification_counts["provenance_only"],
            "requires_manual_confirmation": sum(change["requires_manual_confirmation"]
                                                for change in changes),
            "by_entity_type": dict(Counter(change["entity_type"] for change in changes)),
            "by_change_type": dict(Counter(change["change_type"] for change in changes)),
        },
    }
