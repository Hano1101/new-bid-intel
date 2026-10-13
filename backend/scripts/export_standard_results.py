"""Export competition-format result tables from a local SQLite dataset.

Example:
    python scripts/export_standard_results.py --db .data/datasets/<id>.sqlite \
        --out ../deliverables/official_results.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.result_workbook import build_result_workbook
from app.storage import connect


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--out", required=True, help="Destination .xlsx path")
    parser.add_argument(
        "--notice-id", type=int, action="append", dest="notice_ids",
        help="Notice ID to include; repeat to select multiple. Omit to export all notices.",
    )
    args = parser.parse_args()
    database = Path(args.db).resolve()
    if not database.is_file():
        parser.error(f"database does not exist: {database}")
    destination = Path(args.out).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as connection:
        workbook = build_result_workbook(connection, args.notice_ids)
    destination.write_bytes(workbook)
    print(f"Exported result workbook to {destination} ({len(workbook):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
