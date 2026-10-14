"""Offline, resumable supplementation of result fields from retained source bytes.

Run with explicit database, source directory and private audit directory. It does
not call a model or replace the existing item/award projection. A SQLite backup
precedes writes. Per-notice receipts retain failures and unsupported sources.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from app.archive_files import DiskDocument, expand_paths
from app.attachment_scope import classify_attachment_scope
from app.bidder_result_details import extract_bidder_details
from app.file_formats import inspect_content
from app.ingestion import _current_bidder_result_details, _reference_attachment, _unfilled_template
from app.parsers import parse_document_with_participants
from app.storage import initialize_bidder_result_details, save_bidder_result_details

_UUID = re.compile(r"t\d{8}_\d+")
_REVIEW_TEXT = re.compile(r"审查|投标报价|响应报价|最终报价|未中标|未成交|得分|报价金额")
_RECEIPT_VERSION = 2


def run(database: Path, sources: Path, audit: Path) -> dict:
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    audit.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=60)
    connection.row_factory = sqlite3.Row
    backup = audit / "before-backfill.sqlite"
    if not backup.exists():
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
    initialize_bidder_result_details(connection)
    connection.commit()
    notices = connection.execute("SELECT id, source_files_json FROM notices ORDER BY id").fetchall()
    stats = Counter()
    for index, notice in enumerate(notices, 1):
        receipt_path = audit / f"notice-{notice['id']}.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (receipt.get("version") == _RECEIPT_VERSION
                    and not receipt["counts"].get("failed_sources")):
                stats.update(receipt["counts"])
                continue
        filenames = json.loads(notice["source_files_json"])
        uuid = next((match.group() for name in filenames if (match := _UUID.search(name))), None)
        if not uuid:
            raise ValueError(f"notice {notice['id']}: no source UUID")
        uploaded = [DiskDocument(path.name, path)
                    for suffix in (".html", ".zip") if (path := sources / (uuid + suffix)).exists()]
        workspace = tempfile.TemporaryDirectory(prefix="result-backfill-", dir=audit)
        expanded, warnings = expand_paths(uploaded, Path(workspace.name))
        counts = Counter(notices=1, sources=len(expanded))
        records = []
        ledger = []
        for document in expanded:
            entry = {"source_file": document.filename}
            try:
                if _reference_attachment(document.filename):
                    entry["status"] = "reference_material"
                    counts["reference_material"] += 1
                else:
                    detected = inspect_content(document.content)
                    if detected.format not in {"html", "docx", "doc", "rtf", "wps", "xlsx", "xls", "pdf"}:
                        entry["status"] = "unsupported_or_scan"
                        counts["unsupported_or_scan"] += 1
                    else:
                        should_extract = True
                        if detected.format == "pdf":
                            from pypdf import PdfReader

                            text = "\n".join(page.extract_text() or "" for page in
                                             PdfReader(io.BytesIO(detected.content)).pages)
                            if not text.strip():
                                entry["status"] = "scan_requires_review"
                                counts["scan_requires_review"] += 1
                                should_extract = False
                            elif not _REVIEW_TEXT.search(text):
                                entry["status"] = "no_review_labels"
                                should_extract = False
                        if should_extract:
                            details = extract_bidder_details(document)
                            if details:
                                text, items, _, parse_warnings = parse_document_with_participants(document)
                                warnings.extend(parse_warnings)
                                if document.filename.lower().endswith((".html", ".htm")):
                                    accepted = details
                                elif _unfilled_template(text, items):
                                    accepted = []
                                else:
                                    scope = classify_attachment_scope(document.filename, text)
                                    # Preserve the upload's current/historical section filter.
                                    accepted, scoped_warnings = _current_bidder_result_details(document, text, scope)
                                    warnings.extend(scoped_warnings)
                                records.extend(accepted)
                                entry.update(status="extracted" if accepted else "scope_filtered",
                                             observations=len(accepted))
                                counts["observations"] += len(accepted)
                            else:
                                entry["status"] = "no_supported_review_table"
            except Exception as exc:  # noqa: BLE001 - retain individual source failure
                entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                counts["failed_sources"] += 1
            ledger.append(entry)
        # Replace this sidecar atomically on a new parser revision; core item,
        # participation and award projections are deliberately untouched.
        connection.execute("DELETE FROM bidder_result_details WHERE notice_id=?", (notice["id"],))
        inserted = save_bidder_result_details(connection, notice["id"], records)
        connection.commit()
        counts["inserted"] = inserted
        receipt = {"version": _RECEIPT_VERSION, "notice_id": notice["id"], "uuid": uuid, "counts": dict(counts),
                   "sources": ledger, "warnings": warnings}
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        workspace.cleanup()
        stats.update(counts)
        if index % 25 == 0:
            print(json.dumps({"completed": index, "total": len(notices), **stats}), flush=True)
    connection.close()
    summary = dict(stats)
    (audit / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.database.resolve(), args.sources.resolve(), args.audit.resolve())))
