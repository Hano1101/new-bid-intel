"""Dataset-scoped, signal-driven manual review queue.

Review decisions are append-only events stored in the selected dataset database.
They deliberately never update procurement candidates or analysis tables.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi import Path as ApiPath
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth import request_username
from app.datasets import DatabasePath
from app.evidence import ITEM_FIELDS, field_state, has_field_evidence
from app.storage import connect, initialize
from app.warning_categories import WarningCategory, classify_warning

router = APIRouter(prefix="/api/v1/review-queue", tags=["manual review"])
CandidateType = Literal["item", "bid", "award"]
DecisionAction = Literal["accepted", "corrected", "rejected"]

REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY,
    candidate_type TEXT NOT NULL CHECK (candidate_type IN ('item', 'bid', 'award')),
    candidate_id INTEGER NOT NULL,
    candidate_epoch INTEGER NOT NULL DEFAULT 1 CHECK (candidate_epoch > 0),
    action TEXT NOT NULL CHECK (action IN ('accepted', 'corrected', 'rejected')),
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    candidate_snapshot_json TEXT NOT NULL,
    before_values_json TEXT NOT NULL,
    after_values_json TEXT NOT NULL,
    changes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_events_candidate
ON review_events(candidate_type, candidate_id, id DESC);
CREATE TABLE IF NOT EXISTS review_candidate_epochs (
    candidate_type TEXT NOT NULL CHECK (candidate_type IN ('item', 'bid', 'award')),
    candidate_id INTEGER NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch > 0),
    PRIMARY KEY (candidate_type, candidate_id)
);
"""

_ITEM_EDITABLE = {
    "package_code", "product_name", "category", "brand", "model", "quantity",
    "quantity_unit", "unit_price", "total_price",
}
_BID_EDITABLE = {"package_code", "organization_name", "outcome"}
_AWARD_EDITABLE = {"package_code", "organization_name", "award_amount"}
_TEXT_FIELDS = {
    "package_code", "product_name", "category", "brand", "model", "quantity_unit",
    "organization_name",
}
_DECIMAL_FIELDS = {"quantity", "unit_price", "total_price", "award_amount"}
_ITEM_FIELD_LABELS = {
    "product_name": "标的名称", "category": "品目", "brand": "品牌", "model": "规格型号",
    "quantity": "数量", "quantity_unit": "数量单位", "unit_price": "单价", "total_price": "总价",
}
_TYPE_ORDER = {"item": 0, "bid": 1, "award": 2}
_REASON_PRIORITY = {
    "numeric_conflict": 1,
    "source_evidence_missing": 1,
    "source_file_missing": 1,
    "source_location_missing": 1,
    "field_evidence_missing": 1,
    "field_missing": 2,
    "parsing_warning": 2,
    "default_package": 3,
}


class DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DecisionAction
    reason: str = Field(min_length=1, max_length=2000)
    candidate_epoch: int = Field(gt=0, strict=True)
    corrected_values: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_values(self):
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        if self.action == "corrected" and not self.corrected_values:
            raise ValueError("corrected_values is required for a corrected decision")
        if self.action != "corrected" and self.corrected_values:
            raise ValueError("corrected_values is only valid for a corrected decision")
        return self


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _object(value: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _list(value: str | None) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _ensure_review_schema(path: Path) -> None:
    initialize(path)
    with connect(path) as connection:
        connection.executescript(REVIEW_SCHEMA)
        event_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(review_events)")
        }
        if "candidate_epoch" not in event_columns:
            connection.execute(
                "ALTER TABLE review_events ADD COLUMN candidate_epoch INTEGER NOT NULL DEFAULT 1 "
                "CHECK (candidate_epoch > 0)"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_events_identity "
            "ON review_events(candidate_type, candidate_id, candidate_epoch, id DESC)"
        )
        for name, table, kind in (
            ("review_item_epoch_delete", "procurement_items", "item"),
            ("review_bid_epoch_delete", "bid_participations", "bid"),
            ("review_award_epoch_delete", "awards", "award"),
        ):
            connection.executescript(
                f"""CREATE TRIGGER IF NOT EXISTS {name}
                    AFTER DELETE ON {table}
                    BEGIN
                        INSERT INTO review_candidate_epochs(candidate_type, candidate_id, epoch)
                        VALUES ('{kind}', OLD.id, 2)
                        ON CONFLICT(candidate_type, candidate_id)
                        DO UPDATE SET epoch = review_candidate_epochs.epoch + 1;
                    END;"""
            )


def _candidate_epoch(
    connection: sqlite3.Connection, candidate_type: str, candidate_id: int,
) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO review_candidate_epochs(candidate_type, candidate_id, epoch) "
        "VALUES (?, ?, 1)", (candidate_type, candidate_id),
    )
    row = connection.execute(
        "SELECT epoch FROM review_candidate_epochs WHERE candidate_type=? AND candidate_id=?",
        (candidate_type, candidate_id),
    ).fetchone()
    assert row is not None
    return int(row["epoch"])


def _editable_values(candidate_type: str, row: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "item": _ITEM_EDITABLE,
        "bid": _BID_EDITABLE,
        "award": _AWARD_EDITABLE,
    }[candidate_type]
    return {key: row.get(key) for key in sorted(fields)}


def _candidate_snapshot(row: dict[str, Any], candidate_type: str) -> dict[str, Any]:
    field_status = row.pop("field_status_json", None)
    field_evidence = row.pop("field_evidence_json", None)
    warnings = row.pop("warnings_json", None)
    row["candidate_type"] = candidate_type
    row["values"] = _editable_values(candidate_type, row)
    row["warnings"] = warnings if isinstance(warnings, list) else _list(warnings)
    if candidate_type == "item":
        saved_states = _object(field_status)
        all_evidence = _object(field_evidence)
        row["field_status"] = {
            field: field_state(row.get(field), saved_states.get(field), all_evidence.get(field))
            for field in ITEM_FIELDS
        }
        row["field_evidence"] = {
            field: evidence for field, evidence in all_evidence.items()
            if field in ITEM_FIELDS and has_field_evidence(evidence)
        }
    elif "consortium_members_json" in row:
        row["consortium_members"] = _list(row.pop("consortium_members_json"))
    row["evidence_url"] = f"/api/v1/notices/{row['notice_id']}"
    return row


def _load_candidates(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    item_rows = connection.execute(
        """SELECT i.id AS candidate_id, i.notice_id, i.package_id,
                  i.product_name, i.category, i.brand, i.model, i.quantity, i.quantity_unit,
                  i.unit_price, i.total_price, i.source_file, i.source_location,
                  i.source_evidence, i.field_status_json, i.field_evidence_json,
                  i.extraction_method, n.project_name, n.project_number, n.warnings_json,
                  p.package_code, p.package_name
           FROM procurement_items i
           JOIN notices n ON n.id = i.notice_id
           LEFT JOIN packages p ON p.id = i.package_id
           ORDER BY n.id, i.id"""
    ).fetchall()
    bid_rows = connection.execute(
        """SELECT b.id AS candidate_id, pr.notice_id, b.package_id, b.raw_name AS organization_name,
                  b.outcome, b.consortium_members_json, b.source_file, b.source_location,
                  b.source_evidence, n.project_name, n.project_number, n.warnings_json,
                  p.package_code, p.package_name
           FROM bid_participations b
           JOIN packages p ON p.id = b.package_id
           JOIN projects pr ON pr.id = p.project_id
           JOIN notices n ON n.id = pr.notice_id
           ORDER BY n.id, b.id"""
    ).fetchall()
    award_rows = connection.execute(
        """SELECT a.id AS candidate_id, pr.notice_id, a.package_id,
                  a.raw_name AS organization_name, a.award_amount, a.source_file,
                  a.source_location, a.source_evidence, n.project_name, n.project_number,
                  n.warnings_json, p.package_code, p.package_name
           FROM awards a
           JOIN packages p ON p.id = a.package_id
           JOIN projects pr ON pr.id = p.project_id
           JOIN notices n ON n.id = pr.notice_id
           ORDER BY n.id, a.id"""
    ).fetchall()
    result = []
    for kind, rows in (("item", item_rows), ("bid", bid_rows), ("award", award_rows)):
        result.extend(_candidate_snapshot(dict(row), kind) for row in rows)
    return result


def _priority(rank: int) -> dict[str, Any]:
    label = {1: "优先核对来源或数值", 2: "核对字段或解析告警", 3: "核对默认包号"}[rank]
    return {"rank": rank, "label": label}


def _add_reason(reasons: list[dict[str, Any]], code: str, detail: str) -> None:
    reasons.append({"code": code, "detail": detail, "priority": _REASON_PRIORITY[code]})


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _review_reasons(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    kind = candidate["candidate_type"]
    if kind == "item":
        for field in ITEM_FIELDS:
            value = candidate.get(field)
            state = candidate["field_status"].get(field, "unknown")
            label = _ITEM_FIELD_LABELS[field]
            if value is None or value == "":
                if state in {"unknown", "unverified"}:
                    _add_reason(reasons, "field_missing", f"标的字段“{label}”当前为空，来源状态为“{state}”")
            elif state != "present":
                _add_reason(reasons, "field_evidence_missing", f"标的字段“{label}”有值，但缺少完整字段级来源证据或状态未核实")
        quantity = _as_decimal(candidate.get("quantity"))
        unit_price = _as_decimal(candidate.get("unit_price"))
        total_price = _as_decimal(candidate.get("total_price"))
        if quantity is not None and unit_price is not None and total_price is not None:
            expected = quantity * unit_price
            if expected != total_price:
                _add_reason(
                    reasons,
                    "numeric_conflict",
                    f"数量 × 单价 = {expected}，与当前总价 {total_price} 不一致（规则为精确十进制比较）",
                )
    if candidate.get("package_code") == "default":
        _add_reason(reasons, "default_package", "包号为系统占位值 default；需要人工核对原公告包号")

    for name, label in (("source_evidence", "来源片段"), ("source_file", "来源文件"),
                        ("source_location", "原文定位")):
        if not (candidate.get(name) or "").strip():
            code = {"source_evidence": "source_evidence_missing", "source_file": "source_file_missing",
                    "source_location": "source_location_missing"}[name]
            _add_reason(reasons, code, f"{kind}记录缺少{label}")

    matching_warnings = []
    for warning in candidate.get("warnings", []):
        if not isinstance(warning, str):
            continue
        category = classify_warning(warning)
        if category not in {WarningCategory.OTHER, WarningCategory.ROLE_SKIPPED}:
            matching_warnings.append({"category": category.value, "text": warning})
    for warning in matching_warnings:
        _add_reason(reasons, "parsing_warning", f"关联公告有解析告警（{warning['category']}）：{warning['text']}")
    return reasons


def _load_latest_events(
    connection: sqlite3.Connection,
) -> dict[tuple[str, int, int], dict[str, Any]]:
    latest = {}
    for row in connection.execute(
        """SELECT e.* FROM review_events e
           JOIN (SELECT candidate_type, candidate_id, candidate_epoch, MAX(id) AS latest_id
                 FROM review_events GROUP BY candidate_type, candidate_id, candidate_epoch) x
             ON x.latest_id = e.id"""
    ):
        event = dict(row)
        event["after_values"] = _object(event.pop("after_values_json"))
        event["changes"] = _object(event.pop("changes_json"))
        event["candidate_snapshot"] = _object(event.pop("candidate_snapshot_json"))
        event.pop("before_values_json", None)
        event.pop("id", None)
        latest[(event["candidate_type"], event["candidate_id"], event["candidate_epoch"])] = event
    return latest


def _enrich_candidate(candidate: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    reasons = _review_reasons(candidate)
    if not reasons:
        return candidate
    candidate["reasons"] = reasons
    candidate["priority"] = _priority(min(reason["priority"] for reason in reasons))
    candidate["status"] = "processed" if event else "pending"
    candidate["latest_review"] = event
    return candidate


def _candidate_key(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        candidate["priority"]["rank"], int(candidate["notice_id"]),
        _TYPE_ORDER[candidate["candidate_type"]], int(candidate["candidate_id"]),
    )


@router.get("")
def list_review_queue(
    database: DatabasePath,
    status: Literal["pending", "processed", "all"] = Query(default="pending"),
    candidate_type: CandidateType | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _ensure_review_schema(database)
    with connect(database) as connection:
        # Candidate snapshots, decisions and epochs must describe the same import.
        # Epoch initialization writes here, so reserve the writer before reading.
        connection.execute("BEGIN IMMEDIATE")
        events = _load_latest_events(connection)
        candidates = _load_candidates(connection)
        epochs = {
            (candidate["candidate_type"], candidate["candidate_id"]): _candidate_epoch(
                connection, candidate["candidate_type"], candidate["candidate_id"],
            )
            for candidate in candidates
        }
    rows = []
    for candidate in candidates:
        epoch = epochs[(candidate["candidate_type"], candidate["candidate_id"])]
        candidate["candidate_epoch"] = epoch
        event = events.get((candidate["candidate_type"], candidate["candidate_id"], epoch))
        enriched = _enrich_candidate(candidate, event)
        if "reasons" not in enriched:
            continue
        if candidate_type and candidate["candidate_type"] != candidate_type:
            continue
        if status != "all" and enriched["status"] != status:
            continue
        rows.append(enriched)
    rows.sort(key=_candidate_key)
    return {"items": rows[offset:offset + limit], "total": len(rows),
            "status": status, "limit": limit, "offset": offset}


def _load_current_candidate(
    connection: sqlite3.Connection, candidate_type: str, candidate_id: int,
) -> dict[str, Any] | None:
    table, fields, join = {
        "item": (
            "procurement_items",
            (
                "i.id AS candidate_id, i.notice_id, i.package_id, i.product_name, "
                "i.category, i.brand, i.model, i.quantity, i.quantity_unit, i.unit_price, i.total_price, "
                "i.source_file, i.source_location, i.source_evidence, i.field_status_json, "
                "i.field_evidence_json, i.extraction_method, n.project_name, n.project_number, "
                "n.warnings_json, p.package_code, p.package_name"
            ),
            "JOIN notices n ON n.id=i.notice_id LEFT JOIN packages p ON p.id=i.package_id",
        ),
        "bid": (
            "bid_participations",
            (
                "b.id AS candidate_id, pr.notice_id, b.package_id, "
                "b.raw_name AS organization_name, b.outcome, b.consortium_members_json, "
                "b.source_file, b.source_location, b.source_evidence, n.project_name, n.project_number, "
                "n.warnings_json, p.package_code, p.package_name"
            ),
            (
                "JOIN packages p ON p.id=b.package_id JOIN projects pr ON pr.id=p.project_id "
                "JOIN notices n ON n.id=pr.notice_id"
            ),
        ),
        "award": (
            "awards",
            (
                "a.id AS candidate_id, pr.notice_id, a.package_id, "
                "a.raw_name AS organization_name, a.award_amount, a.source_file, a.source_location, "
                "a.source_evidence, n.project_name, n.project_number, n.warnings_json, "
                "p.package_code, p.package_name"
            ),
            (
                "JOIN packages p ON p.id=a.package_id JOIN projects pr ON pr.id=p.project_id "
                "JOIN notices n ON n.id=pr.notice_id"
            ),
        ),
    }[candidate_type]
    alias = {"item": "i", "bid": "b", "award": "a"}[candidate_type]
    row = connection.execute(
        f"SELECT {fields} FROM {table} {alias} {join} WHERE {alias}.id=?", (candidate_id,),
    ).fetchone()
    return _candidate_snapshot(dict(row), candidate_type) if row else None


def _normalize_corrections(candidate_type: str, values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"item": _ITEM_EDITABLE, "bid": _BID_EDITABLE, "award": _AWARD_EDITABLE}[candidate_type]
    unknown = set(values) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"不可修改字段：{', '.join(sorted(unknown))}")
    normalized = {}
    for field, value in values.items():
        if field == "outcome":
            if not isinstance(value, str) or value not in {"winner", "nonwinner", "unknown"}:
                raise HTTPException(status_code=422, detail="outcome 只能是 winner、nonwinner 或 unknown")
            normalized[field] = value
        elif field in _TEXT_FIELDS:
            if value is not None and not isinstance(value, str):
                raise HTTPException(status_code=422, detail=f"{field} 必须是字符串或 null")
            if field == "package_code" and (not isinstance(value, str) or not value.strip()):
                raise HTTPException(status_code=422, detail="package_code 必须为非空字符串")
            normalized[field] = value.strip() if isinstance(value, str) else None
        elif field in _DECIMAL_FIELDS:
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float, str))):
                raise HTTPException(status_code=422, detail=f"{field} 必须是数字、数字字符串或 null")
            parsed = _as_decimal(value)
            if value is not None and parsed is None:
                raise HTTPException(status_code=422, detail=f"{field} 必须是有限十进制数")
            normalized[field] = str(parsed) if parsed is not None else None
    return normalized


def _event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "candidate_type": row["candidate_type"],
        "candidate_id": row["candidate_id"], "candidate_epoch": row["candidate_epoch"],
        "action": row["action"],
        "reason": row["reason"], "actor": row["actor"], "created_at": row["created_at"],
        "candidate_snapshot": _object(row["candidate_snapshot_json"]),
        "before_values": _object(row["before_values_json"]),
        "after_values": _object(row["after_values_json"]),
        "changes": _object(row["changes_json"]),
    }


@router.post("/{candidate_type}/{candidate_id}/decisions", status_code=201)
def decide(
    payload: DecisionPayload,
    request: Request,
    database: DatabasePath,
    candidate_type: CandidateType,
    candidate_id: int = ApiPath(gt=0),
) -> dict[str, Any]:
    _ensure_review_schema(database)
    corrections = _normalize_corrections(candidate_type, payload.corrected_values)
    actor = request_username(request) or "local-reviewer"
    created_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    with connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _load_current_candidate(connection, candidate_type, candidate_id)
        if current is None:
            raise HTTPException(status_code=404, detail="当前数据集下找不到此候选记录")
        if not _review_reasons(current):
            raise HTTPException(status_code=409, detail="该候选当前不符合队列触发规则")
        candidate_epoch = _candidate_epoch(connection, candidate_type, candidate_id)
        if payload.candidate_epoch != candidate_epoch:
            raise HTTPException(status_code=409, detail="候选已被替换；请刷新队列后重新复核")
        previous = connection.execute(
            "SELECT * FROM review_events WHERE candidate_type=? AND candidate_id=? "
            "AND candidate_epoch=? ORDER BY id DESC LIMIT 1",
            (candidate_type, candidate_id, candidate_epoch),
        ).fetchone()
        if previous:
            before_values = _object(previous["after_values_json"])
            candidate_snapshot = _object(previous["candidate_snapshot_json"])
        else:
            before_values = current["values"]
            candidate_snapshot = current
        after_values = {**before_values, **corrections}
        changes = {field: {"before": before_values[field], "after": value}
                   for field, value in corrections.items() if before_values[field] != value}
        if payload.action == "corrected" and not changes:
            raise HTTPException(status_code=422, detail="修正值与当前复核值相同，没有可记录的差异")
        if previous and (
            previous["action"] == payload.action
            and previous["reason"] == payload.reason.strip()
            and _object(previous["after_values_json"]) == after_values
        ):
            raise HTTPException(status_code=409, detail="检测到重复决定；请刷新复核历史")
        cursor = connection.execute(
            """INSERT INTO review_events (
                candidate_type, candidate_id, candidate_epoch, action, reason, actor, created_at,
                candidate_snapshot_json, before_values_json, after_values_json, changes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate_type, candidate_id, candidate_epoch, payload.action, payload.reason.strip(), actor, created_at,
             _json(candidate_snapshot), _json(before_values), _json(after_values), _json(changes)),
        )
        event = connection.execute("SELECT * FROM review_events WHERE id=?", (cursor.lastrowid,)).fetchone()
    assert event is not None
    return _event_payload(event)


@router.get("/{candidate_type}/{candidate_id}/history")
def review_history(
    database: DatabasePath,
    candidate_type: CandidateType,
    candidate_id: int = ApiPath(gt=0),
) -> dict[str, Any]:
    _ensure_review_schema(database)
    with connect(database) as connection:
        rows = connection.execute(
            """SELECT * FROM review_events WHERE candidate_type=? AND candidate_id=? ORDER BY id""",
            (candidate_type, candidate_id),
        ).fetchall()
    return {"candidate_type": candidate_type, "candidate_id": candidate_id,
            "events": [_event_payload(row) for row in rows]}
