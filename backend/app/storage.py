from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.evidence import ITEM_FIELDS, field_state, has_field_evidence
from app.schemas import ImportResult

BIDDER_RESULT_DETAILS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bidder_result_details (
    id INTEGER PRIMARY KEY,
    notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    package_code TEXT NOT NULL DEFAULT 'default',
    raw_name TEXT NOT NULL,
    qualification_status TEXT,
    compliance_status TEXT,
    review_status TEXT,
    bid_amount TEXT,
    evaluation_score TEXT,
    unsuccessful_reason TEXT,
    source_file TEXT,
    source_location TEXT,
    source_evidence TEXT,
    field_evidence_json TEXT NOT NULL DEFAULT '{}',
    detail_hash TEXT NOT NULL,
    UNIQUE(notice_id, detail_hash)
);
CREATE INDEX IF NOT EXISTS idx_bidder_result_notice ON bidder_result_details(notice_id, package_code);
"""

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY,
    project_name TEXT,
    project_number TEXT,
    procurement_unit TEXT,
    project_budget TEXT,
    announced_total_award TEXT,
    metadata_evidence_json TEXT NOT NULL DEFAULT '{}',
    metadata_field_status_json TEXT NOT NULL DEFAULT '{}',
    source_files_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS import_receipts (
    source_key TEXT PRIMARY KEY,
    notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS notice_sources (
    id INTEGER PRIMARY KEY,
    notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    UNIQUE(notice_id, source_file, sha256)
);
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS organization_aliases (
    id INTEGER PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    raw_name TEXT NOT NULL,
    source_notice_id INTEGER REFERENCES notices(id),
    UNIQUE(organization_id, raw_name, source_notice_id)
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    notice_id INTEGER NOT NULL UNIQUE REFERENCES notices(id) ON DELETE CASCADE,
    project_name TEXT,
    project_number TEXT,
    buyer_organization_id INTEGER REFERENCES organizations(id),
    project_budget TEXT,
    announced_total_award TEXT,
    amount_type TEXT
);
CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    package_code TEXT NOT NULL DEFAULT 'default',
    package_name TEXT,
    package_budget TEXT,
    package_award_total TEXT,
    UNIQUE(project_id, package_code)
);
CREATE TABLE IF NOT EXISTS bid_participations (
    id INTEGER PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    raw_name TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'unknown',
    consortium_members_json TEXT NOT NULL DEFAULT '[]',
    source_file TEXT,
    source_location TEXT,
    source_evidence TEXT,
    UNIQUE(package_id, organization_id)
);
""" + BIDDER_RESULT_DETAILS_SCHEMA + """
CREATE TABLE IF NOT EXISTS awards (
    id INTEGER PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    raw_name TEXT NOT NULL,
    award_amount TEXT,
    source_file TEXT,
    source_location TEXT,
    source_evidence TEXT,
    UNIQUE(package_id, organization_id)
);
CREATE TABLE IF NOT EXISTS procurement_items (
    id INTEGER PRIMARY KEY,
    notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    package_id INTEGER REFERENCES packages(id) ON DELETE SET NULL,
    product_name TEXT,
    category TEXT,
    brand TEXT,
    model TEXT,
    quantity TEXT,
    quantity_unit TEXT,
    unit_price TEXT,
    total_price TEXT,
    source_file TEXT NOT NULL,
    source_location TEXT NOT NULL,
    source_evidence TEXT,
    field_status_json TEXT NOT NULL DEFAULT '{}',
    field_evidence_json TEXT NOT NULL DEFAULT '{}',
    extraction_method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_items_product_name ON procurement_items(product_name);
CREATE INDEX IF NOT EXISTS idx_items_brand ON procurement_items(brand);
CREATE INDEX IF NOT EXISTS idx_items_category ON procurement_items(category);
CREATE INDEX IF NOT EXISTS idx_items_model ON procurement_items(model);
CREATE INDEX IF NOT EXISTS idx_items_package_id ON procurement_items(package_id);
CREATE INDEX IF NOT EXISTS idx_projects_buyer_organization ON projects(buyer_organization_id);
CREATE INDEX IF NOT EXISTS idx_bids_org ON bid_participations(organization_id, package_id);
CREATE INDEX IF NOT EXISTS idx_awards_org ON awards(organization_id, package_id);
"""


class _ClosingConnection(sqlite3.Connection):
    """Make ``with connect(...)`` release Windows file handles after commit."""

    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


def _db_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(path), factory=_ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(path: Path) -> None:
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        # Version snapshots are append-only and independent from the mutable
        # normalized notice tables.  Creating these tables is a safe migration:
        # existing rows are never read back as invented historical versions.
        from app.notice_versions import initialize_versions
        initialize_versions(connection)
        for table in ("bid_participations", "awards", "procurement_items"):
            columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "source_evidence" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN source_evidence TEXT")
        item_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(procurement_items)")
        }
        if "field_status_json" not in item_columns:
            connection.execute(
                "ALTER TABLE procurement_items ADD COLUMN field_status_json TEXT NOT NULL DEFAULT '{}'"
            )
        if "field_evidence_json" not in item_columns:
            connection.execute(
                "ALTER TABLE procurement_items ADD COLUMN field_evidence_json TEXT NOT NULL DEFAULT '{}'"
            )
        notice_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(notices)")
        }
        if "metadata_evidence_json" not in notice_columns:
            connection.execute(
                "ALTER TABLE notices ADD COLUMN metadata_evidence_json TEXT NOT NULL DEFAULT '{}'"
            )
        if "metadata_field_status_json" not in notice_columns:
            connection.execute(
                "ALTER TABLE notices ADD COLUMN metadata_field_status_json TEXT NOT NULL DEFAULT '{}'"
            )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(bid_participations)")}
        if "consortium_members_json" not in columns:
            connection.execute(
                "ALTER TABLE bid_participations ADD COLUMN consortium_members_json TEXT NOT NULL DEFAULT '[]'"
            )


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


_BIDDER_DETAIL_FIELDS = (
    "package_code", "raw_name", "qualification_status", "compliance_status", "review_status",
    "bid_amount", "evaluation_score", "unsuccessful_reason", "source_file", "source_location",
    "source_evidence",
)


def initialize_bidder_result_details(connection: sqlite3.Connection) -> None:
    """Add only the download sidecar tables, retaining the caller's transaction."""
    for statement in BIDDER_RESULT_DETAILS_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def save_bidder_result_details(
    connection: sqlite3.Connection, notice_id: int, details: list[dict[str, Any]],
) -> int:
    """Append source facts for standard downloads without changing the extraction projection.

    Keep distinct observations, including contradictory values, so the export
    merger can leave conflicts blank. A retry only deduplicates identical facts
    and their provenance; it must never overwrite a prior conflicting row.
    The caller owns the transaction and must initialize the database first.
    """
    from app.package_codes import normalize_package_code

    inserted = 0
    for detail in details:
        name = str(detail.get("raw_name") or "").strip()
        if not name:
            continue
        values = {
            field: str(detail[field]) if detail.get(field) is not None else None
            for field in _BIDDER_DETAIL_FIELDS
        }
        for field in ("bid_amount", "evaluation_score"):
            if values[field] is not None:
                try:
                    number = Decimal(values[field])
                    if number.is_finite():
                        values[field] = format(number.normalize(), "f")
                except (ArithmeticError, ValueError):
                    pass
        values.update(package_code=normalize_package_code(detail.get("package_code")), raw_name=name)
        evidence_json = json.dumps(
            detail.get("field_evidence") or {}, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        )
        payload = json.dumps(
            {**values, "field_evidence": json.loads(evidence_json)}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        detail_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        cursor = connection.execute(
            """INSERT OR IGNORE INTO bidder_result_details (
                notice_id, package_code, raw_name, qualification_status, compliance_status,
                review_status, bid_amount, evaluation_score, unsuccessful_reason,
                source_file, source_location, source_evidence, field_evidence_json, detail_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (notice_id, *(values[field] for field in _BIDDER_DETAIL_FIELDS), evidence_json, detail_hash),
        )
        inserted += cursor.rowcount
    return inserted


def read_bidder_result_details(
    connection: sqlite3.Connection, notice_id: int,
) -> list[dict[str, Any]]:
    """Return original source observations; callers may merge them for display."""
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bidder_result_details'",
    ).fetchone():
        return []
    records = []
    for row in connection.execute(
        "SELECT * FROM bidder_result_details WHERE notice_id=? ORDER BY id", (notice_id,),
    ):
        record = {field: row[field] for field in _BIDDER_DETAIL_FIELDS}
        record["field_evidence"] = json.loads(row["field_evidence_json"])
        records.append(record)
    return records


def _normalized_entity_name(name: str) -> str:
    # Conservative normalization only. Do not fuzzy-merge branches or similar names
    # before the official reference data establishes that they are the same entity.
    return "".join(name.strip().split()).casefold()


def _upsert_organization(connection: sqlite3.Connection, raw_name: str, notice_id: int) -> int:
    normalized = _normalized_entity_name(raw_name)
    if not normalized:
        raise ValueError("organization name cannot be empty")
    connection.execute(
        "INSERT OR IGNORE INTO organizations(canonical_name, normalized_name) VALUES (?, ?)",
        (raw_name.strip(), normalized),
    )
    row = connection.execute(
        "SELECT id FROM organizations WHERE normalized_name = ?", (normalized,)
    ).fetchone()
    assert row is not None
    connection.execute(
        "INSERT OR IGNORE INTO organization_aliases(organization_id, raw_name, source_notice_id) "
        "VALUES (?, ?, ?)",
        (row["id"], raw_name.strip(), notice_id),
    )
    return int(row["id"])


def save_import(
    path: Path, result: ImportResult, source_text: str = "", *, source_key: str | None = None,
    replace_existing: bool = False,
    source_documents: list[tuple[str, bytes]] | None = None,
    source_hashes: list[tuple[str, str, int]] | None = None,
    source_texts: dict[str, str] | None = None,
    version_identity: dict[str, str] | None = None,
    version_reason: str = "notice_import",
    version_packages: list[dict[str, Any]] | None = None,
    bidder_result_details: list[dict[str, Any]] | None = None,
) -> ImportResult:
    initialize(path)
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        prior = None
        next_notice_id = connection.execute(
            'SELECT COALESCE(MAX(id), 0) + 1 FROM '
            '(SELECT id FROM notices UNION ALL SELECT notice_id AS id FROM notice_versions)',
        ).fetchone()[0]
        if source_key is not None:
            prior = connection.execute(
                'SELECT notice_id FROM import_receipts WHERE source_key = ?', (source_key,),
            ).fetchone()
            if prior is not None and not replace_existing:
                save_bidder_result_details(connection, prior['notice_id'], bidder_result_details or [])
                return result.model_copy(update={'notice_id': prior['notice_id']})
            if prior is not None:
                if not connection.execute(
                    'SELECT 1 FROM notice_version_links WHERE notice_id=?', (prior['notice_id'],),
                ).fetchone():
                    raise ValueError('旧公告未保存版本，禁止覆盖；请独立导入新快照并保留旧记录')
                # Preserve the existing candidate epoch/ID behavior of retries;
                # their immutable version and evidence are independent of this
                # mutable projection. A failure rolls the entire delete back.
                connection.execute('DELETE FROM organization_aliases WHERE source_notice_id=?',
                                   (prior['notice_id'],))
                connection.execute('DELETE FROM notices WHERE id=?', (prior['notice_id'],))
        cursor = connection.execute(
            """INSERT INTO notices (
                id, project_name, project_number, procurement_unit, project_budget,
                announced_total_award, metadata_evidence_json, metadata_field_status_json,
                source_files_json, warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                # Deleted mutable projections must never reuse a historical
                # version's notice ID, or a history/evidence link can change owner.
                next_notice_id,
                result.metadata.project_name,
                result.metadata.project_number,
                result.metadata.procurement_unit,
                _decimal_text(result.metadata.project_budget),
                _decimal_text(result.metadata.announced_total_award),
                json.dumps(result.metadata_evidence, ensure_ascii=False),
                json.dumps(result.metadata_field_status, ensure_ascii=False),
                json.dumps(result.source_files, ensure_ascii=False),
                json.dumps(result.warnings, ensure_ascii=False),
            ),
        )
        notice_id = int(cursor.lastrowid)
        source_records = {
            (source_file, hashlib.sha256(content).hexdigest(), len(content))
            for source_file, content in source_documents or []
            if source_file not in {record[0] for record in source_hashes or []}
        }
        for source_file, digest, byte_size in source_hashes or []:
            if (not isinstance(source_file, str) or not source_file
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                    or not isinstance(byte_size, int) or isinstance(byte_size, bool)
                    or byte_size < 0):
                raise ValueError("source hash record is malformed")
            source_records.add((source_file, digest, byte_size))
        for source_file, digest, byte_size in sorted(source_records):
            connection.execute(
                """INSERT OR IGNORE INTO notice_sources (
                       notice_id, source_file, sha256, byte_size
                   ) VALUES (?, ?, ?, ?)""",
                (notice_id, source_file, digest, byte_size),
            )
        buyer_id = None
        if result.metadata.procurement_unit:
            buyer_id = _upsert_organization(connection, result.metadata.procurement_unit, notice_id)
        project_cursor = connection.execute(
            """INSERT INTO projects (
                notice_id, project_name, project_number, buyer_organization_id,
                project_budget, announced_total_award, amount_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                notice_id,
                result.metadata.project_name,
                result.metadata.project_number,
                buyer_id,
                _decimal_text(result.metadata.project_budget),
                _decimal_text(result.metadata.announced_total_award),
                "budget_and_award"
                if result.metadata.project_budget is not None
                and result.metadata.announced_total_award is not None
                else "budget"
                if result.metadata.project_budget is not None
                else "announced_total_award"
                if result.metadata.announced_total_award is not None
                else None,
            ),
        )
        project_id = int(project_cursor.lastrowid)
        codes = sorted({row.package_code for row in [*result.items, *result.participants]}) or ["default"]
        package_ids = {}
        for code in codes:
            package_cursor = connection.execute(
                """INSERT INTO packages(project_id, package_code, package_name, package_award_total)
                   VALUES (?, ?, NULL, ?)""",
                (project_id, code, _decimal_text(result.metadata.announced_total_award)
                 if len(codes) == 1 else None),
            )
            package_ids[code] = int(package_cursor.lastrowid)
        for participant in result.participants:
            package_id = package_ids[participant.package_code]
            organization_id = _upsert_organization(
                connection, participant.organization_name, notice_id
            )
            connection.execute(
                """INSERT OR IGNORE INTO bid_participations (
                    package_id, organization_id, raw_name, outcome,
                    source_file, source_location, source_evidence, consortium_members_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    package_id,
                    organization_id,
                    participant.organization_name,
                    participant.outcome,
                    participant.source_file,
                    participant.source_location,
                    participant.source_evidence,
                    json.dumps(participant.consortium_members, ensure_ascii=False),
                ),
            )
            if participant.outcome == "winner":
                connection.execute(
                    """INSERT OR IGNORE INTO awards (
                        package_id, organization_id, raw_name, award_amount,
                        source_file, source_location, source_evidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        package_id,
                        organization_id,
                        participant.organization_name,
                        _decimal_text(participant.award_amount),
                        participant.source_file,
                        participant.source_location,
                        participant.source_evidence,
                    ),
                )
        for item in result.items:
            package_id = package_ids[item.package_code]
            connection.execute(
                """INSERT INTO procurement_items (
                    notice_id, package_id, product_name, category, brand, model,
                    quantity, quantity_unit, unit_price, total_price, source_file,
                    source_location, source_evidence, field_status_json, field_evidence_json,
                    extraction_method, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    notice_id,
                    package_id,
                    item.product_name,
                    item.category,
                    item.brand,
                    item.model,
                    _decimal_text(item.quantity),
                    item.quantity_unit,
                    _decimal_text(item.unit_price),
                    _decimal_text(item.total_price),
                    item.source_file,
                    item.source_location,
                    item.source_evidence,
                    json.dumps(item.field_status, ensure_ascii=False),
                    json.dumps(item.field_evidence, ensure_ascii=False),
                    item.extraction_method,
                    item.confidence,
                ),
            )
        save_bidder_result_details(connection, notice_id, bidder_result_details or [])
        from app.notice_versions import capture_version
        version = capture_version(
            connection,
            path,
            result.model_copy(update={"notice_id": notice_id}),
            sorted(source_records),
            documents=source_documents,
            source_texts=source_texts,
            identity=version_identity,
            reason=version_reason,
            version_packages=version_packages,
        )
        if version['status'] == 'duplicate_snapshot':
            duplicate_notice_id = connection.execute(
                'SELECT notice_id FROM notice_versions WHERE version_id=?', (version['version_id'],),
            ).fetchone()[0]
            if connection.execute('SELECT 1 FROM notices WHERE id=?',
                                  (duplicate_notice_id,)).fetchone():
                connection.execute('DELETE FROM organization_aliases WHERE source_notice_id=?',
                                   (notice_id,))
                connection.execute('DELETE FROM notices WHERE id=?', (notice_id,))
                connection.execute('DELETE FROM notice_version_links WHERE notice_id=?', (notice_id,))
                notice_id = duplicate_notice_id
                save_bidder_result_details(connection, notice_id, bidder_result_details or [])
        if source_key is not None:
            connection.execute('INSERT OR REPLACE INTO import_receipts VALUES (?, ?)',
                               (source_key, notice_id))
        return result.model_copy(update={
            "notice_id": notice_id,
            "version_status": version["status"],
            "version_id": version["version_id"],
            "version_group_id": version["group_id"],
            "identity_status": version["identity_status"],
        })


def search_items(
    path: Path,
    *,
    query: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialize(path)
    clauses: list[str] = []
    values: list[Any] = []
    for column, value in (
        ("product_name", query),
        ("category", category),
        ("brand", brand),
        ("model", model),
    ):
        if value:
            clauses.append(f"{column} LIKE ?")
            values.append(f"%{value}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""SELECT i.*, n.project_name, n.project_number, n.procurement_unit,
                     p.package_code, p.package_name
              FROM procurement_items i JOIN notices n ON n.id = i.notice_id
              LEFT JOIN packages p ON p.id = i.package_id
              {where} ORDER BY i.id DESC LIMIT ?"""
    values.append(max(1, min(limit, 500)))
    with connect(path) as connection:
        return [dict(row) for row in connection.execute(sql, values).fetchall()]


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def get_notice_detail(path: Path, notice_id: int) -> dict[str, Any] | None:
    """Return only the provenance already stored for one notice."""
    initialize(path)
    with connect(path) as connection:
        notice = connection.execute(
            """SELECT n.*, p.id AS project_id
               FROM notices n LEFT JOIN projects p ON p.notice_id = n.id
               WHERE n.id = ?""",
            (notice_id,),
        ).fetchone()
        if notice is None:
            return None

        metadata_evidence = _json_object(notice["metadata_evidence_json"])
        metadata_field_status = _json_object(notice["metadata_field_status_json"])

        packages = [dict(row) for row in connection.execute(
            "SELECT id, package_code, package_name FROM packages WHERE project_id = ? ORDER BY id",
            (notice["project_id"],),
        )] if notice["project_id"] is not None else []
        items = [dict(row) for row in connection.execute(
            """SELECT i.*, p.package_code, p.package_name
               FROM procurement_items i LEFT JOIN packages p ON p.id = i.package_id
               WHERE i.notice_id = ? ORDER BY i.id""",
            (notice_id,),
        )]
        bidders = [dict(row) for row in connection.execute(
            """SELECT b.id, b.package_id, p.package_code, p.package_name,
                      b.raw_name AS organization_name, b.outcome,
                      b.consortium_members_json, b.source_file, b.source_location,
                      b.source_evidence
               FROM bid_participations b
               JOIN packages p ON p.id = b.package_id
               JOIN projects pr ON pr.id = p.project_id
               WHERE pr.notice_id = ? ORDER BY b.id""",
            (notice_id,),
        )]
        awards = [dict(row) for row in connection.execute(
            """SELECT a.id, a.package_id, p.package_code, p.package_name,
                      a.raw_name AS organization_name, a.award_amount,
                      a.source_file, a.source_location, a.source_evidence
               FROM awards a
               JOIN packages p ON p.id = a.package_id
               JOIN projects pr ON pr.id = p.project_id
               WHERE pr.notice_id = ? ORDER BY a.id""",
            (notice_id,),
        )]
        saved_sources = [dict(row) for row in connection.execute(
            "SELECT source_file, sha256, byte_size FROM notice_sources WHERE notice_id = ? ORDER BY id",
            (notice_id,),
        )]

    sources_by_name: dict[str, dict[str, dict[str, Any]]] = {}
    for source in saved_sources:
        source_by_name = sources_by_name.setdefault(source["source_file"], {})
        source_by_name[source["sha256"]] = {
            "source_file": source["source_file"], "sha256": source["sha256"],
            "byte_size": source["byte_size"], "hash_status": "available",
            "hash_provenance_status": "available",
            "file_available": False,
        }
    file_names = _json_list(notice["source_files_json"])
    for row in [*items, *bidders, *awards]:
        name = row.get("source_file")
        if name and name not in sources_by_name:
            sources_by_name[name] = {"not_saved": {
                "source_file": name, "sha256": None, "byte_size": None,
                "hash_status": "not_saved", "hash_provenance_status": "unavailable",
                "file_available": False,
            }}
    for name in file_names:
        if isinstance(name, str) and name and name not in sources_by_name:
            sources_by_name[name] = {"not_saved": {
                "source_file": name, "sha256": None, "byte_size": None,
                "hash_status": "not_saved", "hash_provenance_status": "unavailable",
                "file_available": False,
            }}
    for row in [*items, *bidders, *awards]:
        row["evidence_status"] = "available" if (row.get("source_evidence") or "").strip() else "missing"
        matching_sources = list(sources_by_name.get(row.get("source_file") or "", {}).values())
        matching_hashes = {source["sha256"] for source in matching_sources if source["sha256"]}
        if len(matching_hashes) == 1:
            row["source_sha256"] = next(iter(matching_hashes))
            row["source_hash_status"] = "available"
            row["source_hash_provenance_status"] = "available"
        elif len(matching_hashes) > 1:
            row["source_sha256"] = None
            row["source_hash_status"] = "ambiguous"
            row["source_hash_provenance_status"] = "ambiguous"
        else:
            row["source_sha256"] = None
            row["source_hash_status"] = "not_saved"
            row["source_hash_provenance_status"] = "unavailable"
        if "consortium_members_json" in row:
            row["consortium_members"] = _json_list(row.pop("consortium_members_json"))

    for row in items:
        saved_statuses = _json_object(row.pop("field_status_json", None))
        row["field_evidence"] = {
            field: evidence for field, evidence in
            _json_object(row.pop("field_evidence_json", None)).items()
            if field in ITEM_FIELDS and has_field_evidence(evidence)
        }
        row["field_status"] = {
            field: field_state(row.get(field), saved_statuses.get(field),
                               row["field_evidence"].get(field))
            for field in ITEM_FIELDS
        }

    metadata = {
        "project_name": notice["project_name"],
        "project_number": notice["project_number"],
        "procurement_unit": notice["procurement_unit"],
        "project_budget": notice["project_budget"],
        "announced_total_award": notice["announced_total_award"],
    }
    metadata_states: dict[str, str] = {}
    metadata_evidence = {
        field: evidence for field, evidence in metadata_evidence.items()
        if field in metadata and has_field_evidence(evidence)
    }
    for field, value in metadata.items():
        # Legacy NULLs never prove explicit omission; populated values without
        # a saved field source remain unverified, even if a row excerpt exists.
        metadata_states[field] = field_state(
            value, metadata_field_status.get(field), metadata_evidence.get(field),
        )

    all_field_evidence = [*metadata_evidence.values(), *(
        evidence for row in items for evidence in row["field_evidence"].values()
    )]
    for field_evidence in all_field_evidence:
        source_name = field_evidence.get("source_file")
        matching_sources = list(sources_by_name.get(source_name or "", {}).values())
        hashes = {source.get("sha256") for source in matching_sources if source.get("sha256")}
        if len(hashes) == 1:
            field_evidence["source_sha256"] = next(iter(hashes))
            field_evidence["source_hash_status"] = "available"
            field_evidence["source_hash_provenance_status"] = "available"
        elif len(hashes) > 1:
            field_evidence["source_sha256"] = None
            field_evidence["source_hash_status"] = "ambiguous"
            field_evidence["source_hash_provenance_status"] = "ambiguous"
        else:
            field_evidence["source_sha256"] = None
            field_evidence["source_hash_status"] = "not_saved"
            field_evidence["source_hash_provenance_status"] = "unavailable"

    return {
        "notice_id": notice_id,
        "metadata": metadata,
        "metadata_evidence": metadata_evidence,
        "metadata_field_status": metadata_states,
        "metadata_evidence_status": (
            "available" if any(isinstance(value, dict) for value in metadata_evidence.values())
            else "missing"
        ),
        "source_files": [
            source for same_name_sources in sources_by_name.values()
            for source in same_name_sources.values()
        ],
        "warnings": _json_list(notice["warnings_json"]),
        "packages": packages,
        "items": items,
        "bidders": bidders,
        "awards": awards,
        "capabilities": {
            "evidence_granularity": "field_level_when_available; otherwise record_level",
            "metadata_evidence": "field_level_when_available",
            "explicit_empty_status": "supported; legacy records are unknown",
            "source_files_retained": False,
        },
    }


def count_notices(path: Path) -> int:
    initialize(path)
    with connect(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM notices").fetchone()[0])
