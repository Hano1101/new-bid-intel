"""Append-only structured notice snapshots; never archives source file bytes."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bs4 import BeautifulSoup, NavigableString, Tag

from app.schemas import ImportResult

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS notice_version_groups (
        group_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL,
        identity_status TEXT NOT NULL, identity_json TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS notice_version_identities (
        dataset_id TEXT NOT NULL, token TEXT NOT NULL, kind TEXT NOT NULL,
        group_id TEXT NOT NULL REFERENCES notice_version_groups(group_id),
        UNIQUE(dataset_id, token, group_id))""",
    """CREATE INDEX IF NOT EXISTS idx_notice_version_identity
        ON notice_version_identities(dataset_id, token)""",
    """CREATE TABLE IF NOT EXISTS notice_versions (
        version_id TEXT PRIMARY KEY, group_id TEXT NOT NULL
            REFERENCES notice_version_groups(group_id),
        dataset_id TEXT NOT NULL, notice_id INTEGER NOT NULL,
        imported_at TEXT NOT NULL, reason TEXT NOT NULL,
        identity_status TEXT NOT NULL, identity_json TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL,
        UNIQUE(dataset_id, group_id, snapshot_hash))""",
    """CREATE INDEX IF NOT EXISTS idx_notice_versions_group
        ON notice_versions(dataset_id, group_id, imported_at)""",
    """CREATE TABLE IF NOT EXISTS notice_version_links (
        dataset_id TEXT NOT NULL, notice_id INTEGER NOT NULL,
        version_id TEXT NOT NULL REFERENCES notice_versions(version_id),
        PRIMARY KEY(dataset_id, notice_id))""",
    """CREATE TRIGGER IF NOT EXISTS notice_versions_no_update
        BEFORE UPDATE ON notice_versions BEGIN
        SELECT RAISE(ABORT, 'notice versions are immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS notice_versions_no_delete
        BEFORE DELETE ON notice_versions BEGIN
        SELECT RAISE(ABORT, 'notice versions are immutable'); END""",
)


def initialize_versions(connection: sqlite3.Connection) -> None:
    # execute(), rather than executescript(), preserves the caller's transaction.
    for statement in SCHEMA:
        connection.execute(statement)


def dataset_id_for(path: Path) -> str:
    return path.stem if path.parent.name == "datasets" and re.fullmatch(
        r"[0-9a-f]{32}", path.stem,
    ) else "default"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", value)


def html_structure(content: bytes) -> tuple[str, str]:
    """Only a transient DOM is used; the saved body contains plain text."""
    soup = BeautifulSoup(content, "html.parser")

    def node(element):
        if isinstance(element, NavigableString):
            return _text(str(element)) or None
        if not isinstance(element, Tag):
            return None
        return [element.name, dict(sorted(element.attrs.items())),
                [value for child in element.children if (value := node(child)) is not None]]

    canonical = node(soup)
    for hidden in soup(["script", "style"]):
        hidden.decompose()
    return _text(soup.get_text(" ", strip=True)), _hash(canonical)


def _identity(metadata: dict, supplied: dict | None) -> tuple[dict, dict[str, str]]:
    supplied = supplied or {}
    identity = {key: str(supplied[key]).strip() for key in (
        "official_notice_id", "source_unique_id", "namespace",
    ) if supplied.get(key) and str(supplied[key]).strip()}
    namespace = identity.get("namespace", "local-import")
    tokens = {}
    for key in ("official_notice_id", "source_unique_id"):
        if identity.get(key):
            tokens[key] = _hash([key, namespace, identity[key]])
    number, buyer = metadata.get("project_number"), metadata.get("procurement_unit")
    missing = {"", "无", "未知", "未公示", "未提供", "见附件", "详见附件", "none", "null", "n/a", "-", "—"}
    if number and buyer and _text(number).casefold() not in missing and _text(buyer).casefold() not in missing:
        identity["project_number"] = _text(number)
        identity["procurement_unit"] = _text(buyer)
        tokens["project_buyer"] = _hash(["project_buyer", _text(number), _text(buyer)])
    return identity, tokens


def _resolve_group(connection, dataset_id, identity, tokens):
    strong = {key: value for key, value in tokens.items() if key != "project_buyer"}
    selected = strong or tokens
    matches = set()
    for token in selected.values():
        matches.update(row[0] for row in connection.execute(
            "SELECT group_id FROM notice_version_identities WHERE dataset_id = ? AND token = ?",
            (dataset_id, token),
        ))
    if len(matches) == 1:
        group_id = next(iter(matches))
        known = json.loads(connection.execute(
            "SELECT identity_json FROM notice_version_groups WHERE group_id = ? AND dataset_id = ?",
            (group_id, dataset_id),
        ).fetchone()[0])
        # Strong identities added to a formerly weak group remain authoritative.
        known_tokens = {row['kind']: row['token'] for row in connection.execute(
            "SELECT kind, token FROM notice_version_identities WHERE dataset_id=? AND group_id=?",
            (dataset_id, group_id),
        ) if row['kind'] != 'project_buyer'}
        conflicting = any(known.get(key) and identity.get(key) and known[key] != identity[key]
                          for key in ("official_notice_id", "source_unique_id", "namespace"))
        conflicting = conflicting or any(kind in tokens and tokens[kind] != token
                                         for kind, token in known_tokens.items())
        if not conflicting:
            return group_id, "new_version"
        return None, "identity_ambiguous"
    if matches:
        return None, "identity_ambiguous"
    # A new official identity must not be attached to a different official notice
    # simply because both announcements concern the same procurement project.
    if strong and tokens.get("project_buyer"):
        weak = connection.execute(
            "SELECT DISTINCT g.group_id, g.identity_json FROM notice_version_groups g "
            "JOIN notice_version_identities i ON i.group_id = g.group_id "
            "WHERE i.dataset_id = ? AND i.token = ?",
            (dataset_id, tokens["project_buyer"]),
        ).fetchall()
        eligible = [row["group_id"] for row in weak if not connection.execute(
            "SELECT 1 FROM notice_version_identities WHERE dataset_id=? AND group_id=? "
            "AND kind IN ('official_notice_id', 'source_unique_id')",
            (dataset_id, row["group_id"]),
        ).fetchone()]
        if len(weak) == len(eligible) == 1:
            return eligible[0], "new_version"
    return None, "matched" if tokens else "manual_link_required"


def build_snapshot(connection, result, source_records, documents=None, source_texts=None,
                   version_packages=None):
    snapshot = result.model_dump(mode="json")
    for key in ("notice_id", "items_found", "participants", "source_files",
                "version_status", "version_id", "version_group_id", "identity_status"):
        snapshot.pop(key, None)
    notice_id = result.notice_id
    snapshot["packages"] = [dict(row) for row in connection.execute(
        "SELECT p.* FROM packages p JOIN projects pr ON pr.id = p.project_id WHERE pr.notice_id = ? ORDER BY p.id",
        (notice_id,),
    )]
    if version_packages is not None:
        snapshot["packages"] = version_packages
    queries = {
        "bidders": "SELECT b.*, b.raw_name AS organization_name, p.package_code FROM bid_participations b JOIN packages p ON p.id=b.package_id JOIN projects pr ON pr.id=p.project_id WHERE pr.notice_id=? ORDER BY b.id",
        "awards": "SELECT a.*, a.raw_name AS organization_name, p.package_code FROM awards a JOIN packages p ON p.id=a.package_id JOIN projects pr ON pr.id=p.project_id WHERE pr.notice_id=? ORDER BY a.id",
        "items": "SELECT i.*, p.package_code FROM procurement_items i LEFT JOIN packages p ON p.id=i.package_id WHERE i.notice_id=? ORDER BY i.id",
    }
    for name, query in queries.items():
        snapshot[name] = [dict(row) for row in connection.execute(query, (notice_id,))]
        for row in snapshot[name]:
            for key in list(row):
                if key.endswith("_json"):
                    row[key.removesuffix("_json")] = json.loads(row.pop(key))
    normalization = {}
    body = []
    for name, content in documents or []:
        if name.lower().endswith((".html", ".htm")):
            text, digest = html_structure(content)
            normalization[name] = digest
            body.append({"source_file": name, "text": text, "source_location": "body"})
    if not body:
        body = [{"source_file": name, "text": text, "source_location": "parsed_text"}
                for name, text in (source_texts or {}).items()]
    snapshot["body"] = body
    snapshot["body_status"] = "available" if body else "not_saved"
    snapshot["source_files"] = [{
        "source_file": name, "sha256": digest, "byte_size": size,
        "normalized_sha256": normalization.get(name),
        "kind": "body" if name.lower().endswith((".html", ".htm")) else "attachment",
    } for name, digest, size in sorted(source_records)]
    hashed_names = {row["source_file"] for row in snapshot["source_files"]}
    snapshot["source_files"].extend({
        "source_file": name, "sha256": None, "byte_size": None,
        "normalized_sha256": None, "kind": "unknown",
    } for name in result.source_files if name not in hashed_names)
    return snapshot


def snapshot_fingerprint(snapshot: dict) -> str:
    from app.notice_version_diff import normalize_value

    ignored = {"id", "notice_id", "package_id", "project_id", "organization_id", "raw_name",
               "imported_at",
               "confidence", "extraction_method", "warnings"}

    def clean(value, field=""):
        if isinstance(value, dict):
            return {key: clean(item, key) for key, item in value.items() if key not in ignored}
        if isinstance(value, list):
            return sorted((clean(item, field) for item in value), key=_json)
        return normalize_value(value, field)

    return _hash(clean(snapshot))


def capture_version(connection, path: Path, result: ImportResult, source_records,
                    *, documents=None, source_texts=None, identity=None,
                    reason="notice_import", version_packages=None) -> dict:
    dataset_id = dataset_id_for(path)
    snapshot = build_snapshot(connection, result, source_records, documents, source_texts,
                              version_packages)
    identity, tokens = _identity(snapshot["metadata"], identity)
    group_id, status = _resolve_group(connection, dataset_id, identity, tokens)
    fingerprint = snapshot_fingerprint(snapshot)
    if group_id:
        duplicate = connection.execute(
            "SELECT * FROM notice_versions WHERE dataset_id=? AND group_id=? AND snapshot_hash=?",
            (dataset_id, group_id, fingerprint),
        ).fetchone()
    else:
        # Exact repeated material can be deduplicated without asserting a stable identity.
        duplicate = connection.execute(
            "SELECT * FROM notice_versions WHERE dataset_id=? AND snapshot_hash=? "
            "AND identity_json=? AND identity_status=? LIMIT 1",
            (dataset_id, fingerprint, _json(identity), status),
        ).fetchone()
    if duplicate:
        version_id = duplicate["version_id"]
        connection.execute(
            "INSERT OR REPLACE INTO notice_version_links VALUES (?, ?, ?)",
            (dataset_id, result.notice_id, version_id),
        )
        return {"status": "duplicate_snapshot", "version_id": version_id,
                "group_id": duplicate["group_id"], "identity_status": duplicate["identity_status"]}
    timestamp = datetime.now(UTC).isoformat()
    for source in snapshot['source_files']:
        source['imported_at'] = timestamp
    if group_id is None:
        group_id = uuid4().hex
        connection.execute("INSERT INTO notice_version_groups VALUES (?, ?, ?, ?, ?)",
                           (group_id, dataset_id, status, _json(identity), timestamp))
    if status not in {"manual_link_required", "identity_ambiguous"}:
        for kind, token in tokens.items():
            connection.execute("INSERT OR IGNORE INTO notice_version_identities VALUES (?, ?, ?, ?)",
                               (dataset_id, token, kind, group_id))
    version_id = uuid4().hex
    connection.execute("INSERT INTO notice_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (version_id, group_id, dataset_id, result.notice_id, timestamp,
                        reason, status, _json(identity), fingerprint, _json(snapshot)))
    connection.execute("INSERT OR REPLACE INTO notice_version_links VALUES (?, ?, ?)",
                       (dataset_id, result.notice_id, version_id))
    return {"status": status, "identity_status": status,
            "version_id": version_id, "group_id": group_id}


def decode_version(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["snapshot"] = json.loads(result.pop("snapshot_json"))
    result["identity"] = json.loads(result.pop("identity_json"))
    return result


def get_version(path: Path, version_id: str) -> dict | None:
    from app.storage import connect, initialize

    initialize(path)
    with connect(path) as connection:
        return decode_version(connection.execute(
            "SELECT * FROM notice_versions WHERE dataset_id=? AND version_id=?",
            (dataset_id_for(path), version_id),
        ).fetchone())


def list_versions(path: Path, notice_id: int) -> dict:
    from app.storage import connect, initialize

    initialize(path)
    dataset_id = dataset_id_for(path)
    with connect(path) as connection:
        link = connection.execute(
            "SELECT v.group_id FROM notice_versions v JOIN notice_version_links l "
            "ON l.version_id=v.version_id WHERE l.dataset_id=? AND l.notice_id=?",
            (dataset_id, notice_id),
        ).fetchone()
        if link is None:
            return {"notice_id": notice_id, "group_id": None, "identity_status": "not_tracked",
                    "versions": [], "latest_version_id": None}
        versions = [decode_version(row) for row in connection.execute(
            "SELECT * FROM notice_versions WHERE dataset_id=? AND group_id=? ORDER BY imported_at DESC, rowid DESC",
            (dataset_id, link["group_id"]),
        )]
    for index, version in enumerate(versions):
        version["is_latest"] = index == 0
        version["source_files"] = version.pop("snapshot")["source_files"]
    return {"notice_id": notice_id, "group_id": link["group_id"],
            "identity_status": versions[0]["identity_status"], "versions": versions,
            "latest_version_id": versions[0]["version_id"]}


def version_evidence(version: dict) -> dict:
    """Reuse the existing evidence dialog with frozen, version-specific candidates."""
    snapshot = version["snapshot"]
    snapshot = json.loads(_json(snapshot))
    detail = {**snapshot, "notice_id": version["notice_id"], "version_id": version["version_id"],
              "imported_at": version["imported_at"], "identity_status": version["identity_status"]}
    from app.evidence import field_state

    def source_status(record):
        hashes = {row['sha256'] for row in snapshot['source_files']
                  if row['source_file'] == record.get('source_file') and row.get('sha256')}
        record['source_sha256'] = next(iter(hashes)) if len(hashes) == 1 else None
        record['source_hash_status'] = ('available' if len(hashes) == 1
                                        else 'ambiguous' if hashes else 'not_saved')
        record['source_hash_provenance_status'] = ('unavailable' if not hashes
                                                  else record['source_hash_status'])

    for collection in ("items", "bidders", "awards"):
        detail[collection] = [{**row, "notice_id": version["notice_id"],
                              "evidence_status": "available" if row.get("source_evidence") else "missing"}
                             for row in snapshot[collection]]
        for row in detail[collection]:
            source_status(row)
            for evidence in row.get('field_evidence', {}).values():
                source_status(evidence)
            if collection == 'items':
                row['field_status'] = {field: field_state(row.get(field),
                    row.get('field_status', {}).get(field), row.get('field_evidence', {}).get(field))
                    for field in ('product_name', 'category', 'brand', 'model', 'quantity',
                                  'unit_price', 'total_price')}
    detail['metadata_field_status'] = {field: field_state(value,
        snapshot.get('metadata_field_status', {}).get(field),
        snapshot.get('metadata_evidence', {}).get(field))
        for field, value in snapshot['metadata'].items()}
    for evidence in detail.get('metadata_evidence', {}).values():
        source_status(evidence)
    return detail
