from __future__ import annotations

from decimal import Decimal

from app import bidder_result_details, parsers
from app.bidder_result_details import merge_bidder_details
from app.ingestion import _ingest_expanded, extract_scoped_bidder_details
from app.parsers import SourceDocument
from app.schemas import ImportResult, NoticeMetadata
from app.storage import (
    BIDDER_RESULT_DETAILS_SCHEMA,
    SCHEMA,
    connect,
    initialize,
    read_bidder_result_details,
    save_import,
)


def _base_result() -> ImportResult:
    return ImportResult(
        notice_id=0,
        source_files=["notice.html"],
        items_found=0,
        items=[],
        metadata=NoticeMetadata(project_name="合成采购项目"),
    )


def _detail(package: str, *, amount=None, qualification=None, source="review.html"):
    return {
        "package_code": package,
        "raw_name": "甲供应商",
        "qualification_status": qualification,
        "compliance_status": None,
        "review_status": None,
        "bid_amount": Decimal(amount) if amount is not None else None,
        "evaluation_score": None,
        "unsuccessful_reason": None,
        "source_file": source,
        "source_location": "table:1/row:2",
        "source_evidence": f"{package} | 甲供应商",
        "field_evidence": {},
    }


def test_save_import_keeps_complementary_and_conflicting_observations_separate_by_package(tmp_path):
    database = tmp_path / "details.db"
    first = _detail("1", amount="100.00", source="报价表.xlsx")
    complementary = _detail("1", qualification="通过", source="评审表.xlsx")
    conflicting = _detail("1", amount="101.00", source="更正评审表.xlsx")
    other_package = _detail("2", amount="200.00", qualification="未通过")

    saved = save_import(
        database,
        _base_result(),
        bidder_result_details=[first, complementary, conflicting, other_package],
    )

    with connect(database) as connection:
        observations = read_bidder_result_details(connection, saved.notice_id)
    assert len(observations) == 4
    merged = merge_bidder_details(observations)
    by_package = {row["package_code"]: row for row in merged}
    assert set(by_package) == {"1", "2"}
    assert by_package["1"]["qualification_status"] == "通过"
    assert by_package["1"]["bid_amount"] is None
    assert by_package["1"]["field_evidence"]["bid_amount"]["conflict"] is True
    assert by_package["2"]["qualification_status"] == "未通过"
    assert by_package["2"]["bid_amount"] == "200"


def test_source_key_retry_appends_new_details_without_replacing_old_conflicts(tmp_path):
    database = tmp_path / "retry.db"
    original = _detail("1", amount="100")
    corrected = _detail("1", amount="101", source="correction.xlsx")
    first = save_import(
        database, _base_result(), source_key="job:0", bidder_result_details=[original],
    )
    second = save_import(
        database, _base_result(), source_key="job:0", bidder_result_details=[corrected],
    )
    assert second.notice_id == first.notice_id
    with connect(database) as connection:
        observations = read_bidder_result_details(connection, first.notice_id)
    assert len(observations) == 2
    assert merge_bidder_details(observations)[0]["bid_amount"] is None

    # Replaying the original source is idempotent and does not erase the correction.
    save_import(database, _base_result(), source_key="job:0", bidder_result_details=[original])
    with connect(database) as connection:
        assert len(read_bidder_result_details(connection, first.notice_id)) == 2


def test_duplicate_content_snapshot_transfers_added_details_to_original_notice(tmp_path):
    database = tmp_path / "duplicate-snapshot.db"
    first = save_import(
        database, _base_result(), bidder_result_details=[_detail("1", amount="100")],
    )
    second = save_import(
        database, _base_result(), bidder_result_details=[_detail("1", qualification="通过")],
    )
    assert second.version_status == "duplicate_snapshot"
    assert second.notice_id == first.notice_id
    with connect(database) as connection:
        rows = read_bidder_result_details(connection, first.notice_id)
    merged = merge_bidder_details(rows)[0]
    assert merged["bid_amount"] == "100"
    assert merged["qualification_status"] == "通过"


def test_initialize_adds_sidecar_to_existing_database_and_notice_delete_cascades(tmp_path):
    database = tmp_path / "legacy.db"
    with connect(database) as connection:
        connection.executescript(SCHEMA.replace(BIDDER_RESULT_DETAILS_SCHEMA, ""))
    initialize(database)
    saved = save_import(database, _base_result(), bidder_result_details=[_detail("1", amount="9")])

    with connect(database) as connection:
        assert len(read_bidder_result_details(connection, saved.notice_id)) == 1
        connection.execute("DELETE FROM notices WHERE id=?", (saved.notice_id,))
        assert connection.execute("SELECT count(*) FROM bidder_result_details").fetchone()[0] == 0


def test_import_flow_extracts_primary_bidder_sidecar_without_changing_import_result(tmp_path):
    database = tmp_path / "ingestion.db"
    html = """<html><body><h1>项目名称：合成采购项目</h1><table>
      <tr><th>采购包号</th><th>投标人名称</th><th>资格性审查</th><th>符合性审查</th>
      <th>最终报价(元)</th><th>综合得分</th><th>未中标原因</th></tr>
      <tr><td>1</td><td>甲供应商</td><td>通过</td><td>通过</td><td>1234</td>
      <td>98.5</td><td></td></tr></table></body></html>""".encode()
    result = _ingest_expanded(
        [SourceDocument("notice.html", html)], [], database_path=database,
        extraction_mode="rules",
    )

    # The existing ImportResult and extraction projection retain their contract.
    assert result.notice_id > 0
    assert not hasattr(result, "bidder_result_details")
    with connect(database) as connection:
        rows = read_bidder_result_details(connection, result.notice_id)
    assert len(rows) == 1
    assert rows[0]["raw_name"] == "甲供应商"
    assert rows[0]["qualification_status"] == "通过"
    assert rows[0]["compliance_status"] == "通过"
    assert rows[0]["review_status"] == "通过"
    assert rows[0]["bid_amount"] == "1234"
    assert rows[0]["evaluation_score"] == "98.5"


def test_scoped_sidecar_skips_reference_files_and_historical_rows(monkeypatch):
    details_by_file = {
        "notice.html": [],
        "combined.txt": [
            {**_detail("1"), "raw_name": "历史客户", "scope_evidence": "历史客户 旧合同"},
            {**_detail("1"), "raw_name": "当前投标人", "scope_evidence": "当前投标人 95分"},
        ],
    }
    texts = {
        "notice.html": "项目名称：本次采购",
        "combined.txt": "案例一览表\n历史客户 旧合同\n评审结果汇总表\n当前投标人 95分",
    }
    parsed_files = []

    def parse(document, **kwargs):
        parsed_files.append(document.filename)
        return texts.get(document.filename, "投标人名称：参考供应商"), [], [], []

    monkeypatch.setattr(parsers, "parse_document_with_participants", parse)
    monkeypatch.setattr(
        bidder_result_details, "extract_bidder_details",
        lambda document: details_by_file.get(
            document.filename, [_detail("1", source=document.filename)],
        ),
    )
    rows = extract_scoped_bidder_details([
        SourceDocument("notice.html", b"notice"),
        SourceDocument("combined.txt", b"combined"),
        SourceDocument("招标文件.pdf", b"reference"),
    ])
    assert parsed_files == ["notice.html", "combined.txt"]
    assert {row["raw_name"] for row in rows} == {"当前投标人"}
