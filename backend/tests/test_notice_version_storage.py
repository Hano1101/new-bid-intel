"""Synthetic append-only snapshot tests; no model, Gold, or historical inputs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest

from app import notice_versions
from app.notice_version_diff import compare_snapshots
from app.notice_versions import (
    dataset_id_for,
    get_version,
    list_versions,
    version_evidence,
)
from app.schemas import ImportResult, ItemCandidate, NoticeMetadata, ParticipantCandidate
from app.storage import SCHEMA, connect, count_notices, get_notice_detail, initialize, save_import


def snapshot(
    *, name="合成设备采购", number="SYNTH-2026-001", buyer="合成采购中心",
    price="100.00", product="合成终端", source="notice.html", location="table:1/row:2",
) -> ImportResult:
    return ImportResult(
        notice_id=0, source_files=[source], items_found=1,
        metadata=NoticeMetadata(
            project_name=name, project_number=number, procurement_unit=buyer,
            project_budget=Decimal("1000.00"), announced_total_award=Decimal(price),
        ),
        metadata_evidence={"project_name": {
            "source_file": source, "source_location": "text:line:1",
            "source_evidence": f"项目名称：{name}",
        }},
        metadata_field_status={"project_name": "present"},
        items=[ItemCandidate(
            package_code="1", product_name=product, category="信息化设备", brand="合成品牌",
            model="SYNTH-X1", quantity=Decimal("1.00"), quantity_unit="台",
            unit_price=Decimal(price), total_price=Decimal(price),
            source_file=source, source_location=location, source_evidence=f"{product} | {price}元",
            field_evidence={"unit_price": {
                "source_file": source, "source_location": f"{location}/column:6",
                "source_evidence": f"单价 {price}元",
            }},
            field_status={"unit_price": "present"},
        )],
        participants=[ParticipantCandidate(
            package_code="1", organization_name="合成供应商", outcome="winner",
            award_amount=Decimal(price), source_file=source, source_location="table:2/row:2",
            source_evidence=f"合成供应商 | {price}元",
        )],
    )


def save(path, result=None, content=b"<p>synthetic notice</p>", **kwargs):
    result = result or snapshot()
    return save_import(
        path, result, source_documents=[(result.source_files[0], content)], **kwargs,
    )


def stored(path, saved):
    version = get_version(path, saved.version_id)
    assert version is not None
    return version


def table_counts(path):
    tables = (
        "notices", "projects", "packages", "bid_participations", "awards",
        "procurement_items", "notice_sources", "import_receipts", "organizations",
        "organization_aliases", "notice_version_groups", "notice_version_identities",
        "notice_versions", "notice_version_links",
    )
    with connect(path) as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in tables}


def test_versions_coexist_and_the_previous_snapshot_is_unchanged(tmp_path):
    database = tmp_path / "versions.db"
    first = save(database, version_reason="synthetic initial notice")
    frozen = stored(database, first)
    second = save(database, snapshot(name="合成设备采购更正", price="120.00"),
                  content=b"<p>synthetic correction</p>", version_reason="synthetic correction")

    assert first.version_status == "matched"
    assert second.version_status == "new_version"
    assert second.version_id != first.version_id
    assert second.version_group_id == first.version_group_id
    assert first.notice_id != second.notice_id
    assert count_notices(database) == 2
    assert stored(database, first) == frozen
    assert frozen["reason"] == "synthetic initial notice"
    assert frozen["snapshot"]["items"][0]["unit_price"] == "100.00"
    assert stored(database, second)["snapshot"]["items"][0]["unit_price"] == "120.00"
    history = list_versions(database, first.notice_id)
    assert [row["version_id"] for row in history["versions"]] == [
        second.version_id, first.version_id,
    ]
    assert history["latest_version_id"] == second.version_id
    assert history["versions"][0]["is_latest"] is True
    assert history["versions"][1]["is_latest"] is False


def test_identical_snapshot_and_files_return_the_original_version(tmp_path):
    database = tmp_path / "duplicate.db"
    first = save(database)
    second = save(database)

    assert second.version_status == "duplicate_snapshot"
    assert second.version_id == first.version_id
    assert second.version_group_id == first.version_group_id
    assert second.notice_id == first.notice_id
    counts = table_counts(database)
    assert counts["notices"] == counts["notice_versions"] == counts["notice_version_links"] == 1
    assert counts["projects"] == counts["packages"] == counts["procurement_items"] == 1
    assert counts["bid_participations"] == counts["awards"] == 1


def test_same_files_ignore_extraction_diagnostics_order_and_decimal_format(tmp_path):
    database = tmp_path / "equivalent.db"
    first_result = snapshot()
    first_result.source_files.append("attachment.pdf")
    documents = [("notice.html", b"<p>synthetic notice</p>"), ("attachment.pdf", b"synthetic")]
    first = save_import(database, first_result, source_documents=documents)
    second_result = first_result.model_copy(deep=True)
    second_result.source_files.reverse()
    second_result.items[0].unit_price = Decimal("100.0")
    second_result.items[0].confidence = 0.2
    second_result.items[0].extraction_method = "synthetic alternate parser"
    second_result.warnings = ["synthetic parser diagnostics"]
    second_result.metadata_evidence["project_name"] = dict(
        reversed(list(second_result.metadata_evidence["project_name"].items())),
    )
    second = save_import(database, second_result, source_documents=list(reversed(documents)))

    assert second.version_status == "duplicate_snapshot"
    assert second.version_id == first.version_id
    assert count_notices(database) == 1


def test_html_format_change_keeps_a_file_version_without_false_semantic_changes(tmp_path):
    database = tmp_path / "format.db"
    first = save(database, content=b'<html><p class="a" id="b">synthetic notice</p></html>')
    second = save(database, content=(
        b'<html>\n  <p id="b" class="a"> synthetic   notice </p>\n</html>'
    ))
    assert second.version_status == "new_version"
    changes = compare_snapshots(stored(database, first), stored(database, second))

    assert changes["summary"]["semantic"] == 0
    assert changes["summary"]["format_only"] >= 1
    assert {row["entity_type"] for row in changes["changes"]} == {"source_file"}
    assert all(row["classification"] == "format_only" for row in changes["changes"])


@pytest.mark.parametrize("number", [None, "未知", "未公示", "未提供", "见附件", "N/A", "—"])
def test_missing_or_placeholder_identity_never_merges_same_name_notices(tmp_path, number):
    database = tmp_path / "unconfirmed.db"
    first = save(database, snapshot(number=number))
    second = save(database, snapshot(number=number, price="200.00"),
                  content=b"<p>different synthetic notice with the same title</p>")

    assert first.version_status == second.version_status == "manual_link_required"
    assert first.identity_status == second.identity_status == "manual_link_required"
    assert first.version_group_id != second.version_group_id
    assert len(list_versions(database, first.notice_id)["versions"]) == 1
    assert len(list_versions(database, second.notice_id)["versions"]) == 1
    assert count_notices(database) == 2


def test_identical_material_can_deduplicate_while_identity_remains_unconfirmed(tmp_path):
    database = tmp_path / "pending-duplicate.db"
    first = save(database, snapshot(number=None))
    second = save(database, snapshot(number=None))

    assert first.version_status == "manual_link_required"
    assert second.version_status == "duplicate_snapshot"
    assert second.identity_status == "manual_link_required"
    assert second.version_id == first.version_id
    assert count_notices(database) == 1


def test_project_number_and_buyer_match_even_when_project_name_changes(tmp_path):
    database = tmp_path / "project-buyer.db"
    first = save(database)
    second = save(database, snapshot(name="合成公告更正名称"))
    changes = compare_snapshots(stored(database, first), stored(database, second))["changes"]

    assert second.version_group_id == first.version_group_id
    name = next(row for row in changes if row["field"] == "project_name")
    assert name["before"] == "合成设备采购"
    assert name["after"] == "合成公告更正名称"
    assert name["change_type"] == "changed"


def test_project_number_alone_never_merges_different_buyers(tmp_path):
    database = tmp_path / "buyer-conflict.db"
    first = save(database)
    second = save(database, snapshot(buyer="另一合成采购中心"))

    assert second.version_group_id != first.version_group_id
    assert second.version_status == "matched"


def test_ambiguous_identical_material_deduplicates_without_resolving_the_identity(tmp_path):
    database = tmp_path / "ambiguous-duplicate.db"
    save(database, version_identity={"official_notice_id": "official-one", "source_unique_id": "source-one"})
    save(database, snapshot(price="200.00"), version_identity={
        "official_notice_id": "official-two", "source_unique_id": "source-two",
    })
    identity = {"official_notice_id": "official-one", "source_unique_id": "source-two"}
    first = save(database, snapshot(price="300.00"), version_identity=identity)
    repeated = save(database, snapshot(price="300.00"), version_identity=identity)
    assert first.version_status == "identity_ambiguous"
    assert repeated.version_status == "duplicate_snapshot"
    assert repeated.identity_status == "identity_ambiguous"
    assert first.version_id == repeated.version_id


@pytest.mark.parametrize("identity_field", ["official_notice_id", "source_unique_id"])
def test_explicit_stable_identity_tracks_buyer_and_project_number_changes(tmp_path, identity_field):
    database = tmp_path / "official-identity.db"
    identity = {identity_field: "synthetic-notice-001", "namespace": "synthetic-source"}
    first = save(database, version_identity=identity)
    second = save(database, snapshot(buyer="更正后的合成采购中心", number="SYNTH-CORRECTED-002"),
                  version_identity=identity)
    changes = compare_snapshots(stored(database, first), stored(database, second))["changes"]

    assert second.version_status == "new_version"
    assert second.version_group_id == first.version_group_id
    fields = {row["field"]: row for row in changes if row["entity_type"] == "metadata"}
    assert fields["procurement_unit"]["after"] == "更正后的合成采购中心"
    assert fields["project_number"]["after"] == "SYNTH-CORRECTED-002"
    assert fields["procurement_unit"]["change_type"] == "changed"
    assert fields["project_number"]["change_type"] == "changed"


def test_same_official_id_in_different_source_namespaces_is_separate(tmp_path):
    database = tmp_path / "namespace.db"
    first = save(database, version_identity={
        "official_notice_id": "synthetic-001", "namespace": "source-one",
    })
    second = save(database, version_identity={
        "official_notice_id": "synthetic-001", "namespace": "source-two",
    })

    assert first.version_group_id != second.version_group_id


@pytest.mark.parametrize("conflict", ["two_existing_groups", "contradictory_strong_field"])
def test_conflicting_strong_identities_create_an_ambiguous_separate_group(tmp_path, conflict):
    database = tmp_path / "conflicts.db"
    first = save(database, version_identity={
        "official_notice_id": "official-one", "source_unique_id": "source-one",
        "namespace": "synthetic",
    })
    second = save(database, snapshot(price="200.00"), version_identity={
        "official_notice_id": "official-two", "source_unique_id": "source-two",
        "namespace": "synthetic",
    })
    conflicting_identity = {
        "official_notice_id": "official-one" if conflict == "two_existing_groups"
        else "official-three",
        "source_unique_id": "source-two", "namespace": "synthetic",
    }
    ambiguous = save(database, snapshot(price="300.00"), version_identity=conflicting_identity)

    assert ambiguous.version_status == ambiguous.identity_status == "identity_ambiguous"
    assert ambiguous.version_group_id not in {first.version_group_id, second.version_group_id}
    assert len(list_versions(database, first.notice_id)["versions"]) == 1
    assert len(list_versions(database, second.notice_id)["versions"]) == 1


def test_upgraded_weak_group_cannot_merge_a_different_official_notice(tmp_path):
    database = tmp_path / "identity-upgrade.db"
    initial = save(database)
    upgraded = save(database, snapshot(price="120.00"), version_identity={
        "official_notice_id": "synthetic-official-one", "namespace": "synthetic",
    })
    different = save(database, snapshot(price="150.00"), version_identity={
        "official_notice_id": "synthetic-official-two", "namespace": "synthetic",
    })

    assert upgraded.version_group_id == initial.version_group_id
    assert different.version_group_id != initial.version_group_id
    assert len(list_versions(database, initial.notice_id)["versions"]) == 2


def test_dataset_paths_keep_equal_identities_snapshots_and_versions_separate(tmp_path):
    first_database = tmp_path / "datasets" / ("a" * 32 + ".db")
    second_database = tmp_path / "datasets" / ("b" * 32 + ".db")
    first = save(first_database)
    second = save(second_database)

    assert dataset_id_for(first_database) == "a" * 32
    assert dataset_id_for(second_database) == "b" * 32
    assert stored(first_database, first)["dataset_id"] == "a" * 32
    assert stored(second_database, second)["dataset_id"] == "b" * 32
    assert first.version_group_id != second.version_group_id
    assert first.version_id != second.version_id
    assert get_version(first_database, second.version_id) is None
    assert get_version(second_database, first.version_id) is None
    assert len(list_versions(first_database, first.notice_id)["versions"]) == 1
    assert len(list_versions(second_database, second.notice_id)["versions"]) == 1
    default_path = tmp_path / "not-datasets" / ("a" * 32 + ".db")
    assert dataset_id_for(default_path) == "default"
    assert dataset_id_for(tmp_path / "datasets" / "invalid.db") == "default"


def test_migration_preserves_legacy_entities_and_never_fabricates_versions(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO notices(id,project_name,source_files_json,warnings_json) "
            "VALUES (7,'legacy synthetic notice','[\"old.pdf\"]','[]')",
        )
        connection.execute(
            "INSERT INTO organizations(id,canonical_name,normalized_name) "
            "VALUES (4,'legacy supplier','legacysupplier')",
        )
        connection.execute("INSERT INTO projects(id,notice_id,project_name) VALUES (5,7,'legacy')")
        connection.execute("INSERT INTO packages(id,project_id,package_code) VALUES (8,5,'1')")
        connection.execute(
            "INSERT INTO bid_participations(id,package_id,organization_id,raw_name,outcome) "
            "VALUES (11,8,4,'legacy supplier','winner')",
        )
        connection.execute(
            "INSERT INTO awards(id,package_id,organization_id,raw_name,award_amount) "
            "VALUES (12,8,4,'legacy supplier','123.00')",
        )
        connection.execute(
            "INSERT INTO procurement_items(id,notice_id,package_id,product_name,source_file,"
            "source_location,extraction_method) "
            "VALUES (9,7,8,'legacy terminal','old.pdf','page:2','legacy')",
        )
        legacy = {
            name: connection.execute(f"SELECT * FROM {name}").fetchall()
            for name in ("notices", "organizations", "projects", "packages",
                         "bid_participations", "awards", "procurement_items")
        }

    initialize(database)
    initialize(database)
    with connect(database) as connection:
        for name, expected in legacy.items():
            assert [tuple(row) for row in connection.execute(f"SELECT * FROM {name}")] == expected
        assert connection.execute("SELECT count(*) FROM notice_versions").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM notice_version_groups").fetchone()[0] == 0
    assert get_notice_detail(database, 7)["items"][0]["id"] == 9
    history = list_versions(database, 7)
    assert history["versions"] == []
    assert history["identity_status"] == "not_tracked"
    assert history["latest_version_id"] is None


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_database_rejects_snapshot_mutation_or_deletion(tmp_path, operation):
    database = tmp_path / "immutable.db"
    saved = save(database)
    frozen = stored(database, saved)
    query = ("UPDATE notice_versions SET snapshot_json='{}' WHERE version_id=?"
             if operation == "update" else "DELETE FROM notice_versions WHERE version_id=?")

    with pytest.raises(sqlite3.IntegrityError, match="immutable"), connect(database) as connection:
        connection.execute(query, (saved.version_id,))
    assert stored(database, saved) == frozen


def test_replace_existing_retains_frozen_evidence_even_when_candidate_ids_are_reused(tmp_path):
    database = tmp_path / "replace.db"
    first = save(database, source_key="synthetic-job-source")
    frozen = stored(database, first)
    second = save(database, snapshot(product="更正后的合成终端", price="220.00"),
                  content=b"<p>synthetic replacement</p>",
                  source_key="synthetic-job-source", replace_existing=True)

    assert count_notices(database) == 1
    assert second.version_id != first.version_id
    assert first.notice_id != second.notice_id
    assert get_notice_detail(database, first.notice_id) is None
    assert get_notice_detail(database, second.notice_id)["items"][0]["product_name"] == "更正后的合成终端"
    assert stored(database, first) == frozen
    old_evidence = version_evidence(frozen)
    new_evidence = version_evidence(stored(database, second))
    assert old_evidence["version_id"] == first.version_id
    assert old_evidence["notice_id"] == first.notice_id
    for collection in ("items", "bidders", "awards"):
        old_row, new_row = old_evidence[collection][0], new_evidence[collection][0]
        assert old_row["notice_id"] == first.notice_id
        assert new_row["notice_id"] == second.notice_id
        # Legacy retry projections reuse row IDs. The version and notice IDs
        # disambiguate the frozen old/new evidence even in this case.
        assert old_row["id"] == new_row["id"]
        assert old_row["source_file"] == "notice.html"
        assert old_row["evidence_status"] == "available"
    changes = compare_snapshots(frozen, stored(database, second))["changes"]
    product = next(row for row in changes if row["entity_type"] == "item"
                   and row["field"] == "product_name")
    assert product["before_source"]["version_id"] == first.version_id
    assert product["after_source"]["version_id"] == second.version_id
    assert product["before_source"]["notice_id"] != product["after_source"]["notice_id"]
    assert old_evidence["items"][0]["source_location"] == "table:1/row:2"
    assert old_evidence["items"][0]["product_name"] == "合成终端"
    assert len(list_versions(database, first.notice_id)["versions"]) == 2
    assert len(list_versions(database, second.notice_id)["versions"]) == 2


def test_failed_version_capture_rolls_back_new_and_replacement_entities(tmp_path, monkeypatch):
    database = tmp_path / "rollback.db"
    first = save(database, source_key="synthetic-source-key")
    before_counts = table_counts(database)
    frozen = stored(database, first)
    original = notice_versions.capture_version

    def fail_after_capture(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("synthetic failure after snapshot insert")

    monkeypatch.setattr(notice_versions, "capture_version", fail_after_capture)
    with pytest.raises(ValueError, match="synthetic failure"):
        save(database, snapshot(price="700.00", buyer="rollback synthetic buyer"),
             source_key="synthetic-source-key", replace_existing=True)

    assert table_counts(database) == before_counts
    assert stored(database, first) == frozen
    assert get_notice_detail(database, first.notice_id) is not None
    with connect(database) as connection:
        assert connection.execute("SELECT notice_id FROM import_receipts").fetchone()[0] == first.notice_id


def test_concurrent_identical_imports_create_one_version_and_projection(tmp_path):
    database = tmp_path / "concurrent.db"
    initialize(database)
    barrier = Barrier(4)

    def import_once():
        barrier.wait(timeout=10)
        return save(database)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = [future.result(timeout=20) for future in
                   [executor.submit(import_once) for _ in range(4)]]

    assert len({result.version_id for result in results}) == 1
    assert len({result.notice_id for result in results}) == 1
    assert sorted(result.version_status for result in results) == [
        "duplicate_snapshot", "duplicate_snapshot", "duplicate_snapshot", "matched",
    ]
    counts = table_counts(database)
    assert counts["notice_versions"] == counts["notices"] == counts["projects"] == 1
    assert counts["procurement_items"] == counts["notice_version_links"] == 1


def test_source_bytes_are_not_archived_in_snapshot_database_or_files(tmp_path):
    database = tmp_path / "no-source-bytes.db"
    raw = b"\x00\xffSYNTHETIC_RAW_ATTACHMENT_91da4f\x80\x00"
    saved = save(database, snapshot(source="attachment.pdf"), content=raw)
    version = stored(database, saved)
    source = version["snapshot"]["source_files"][0]

    assert source["source_file"] == "attachment.pdf"
    assert source["sha256"] == hashlib.sha256(raw).hexdigest()
    assert source["byte_size"] == len(raw)
    assert version["imported_at"]
    assert version["snapshot"]["body_status"] == "not_saved"
    assert version["snapshot"]["body"] == []
    assert "SYNTHETIC_RAW_ATTACHMENT_91da4f" not in json.dumps(version)
    assert raw not in database.read_bytes()
    assert list(tmp_path.iterdir()) == [database]
    with connect(database) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        )]
        for table in tables:
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            assert all(row["type"].upper() != "BLOB" for row in columns)
