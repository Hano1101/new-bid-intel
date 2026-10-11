from copy import deepcopy
from decimal import Decimal

import pytest

from app.notice_version_diff import compare_snapshots, normalize_value


def version(version_id, **snapshot):
    return {
        "version_id": version_id, "group_id": "notice-group", "notice_id": version_id,
        "dataset_id": "default", "identity_status": "matched",
        "snapshot": {
            "metadata": {}, "metadata_evidence": {}, "metadata_field_status": {},
            "body": [], "source_files": [], "packages": [], "bidders": [],
            "awards": [], "items": [], **snapshot,
        },
    }


def item(**updates):
    return {
        "id": 10, "package_code": "1", "product_name": "打印机", "brand": "甲",
        "model": "AB 10", "category": "办公设备", "quantity": "1.0",
        "quantity_unit": "台", "unit_price": "100.00", "total_price": "100.00",
        "source_file": "报价.xlsx", "source_location": "sheet:1/row:2",
        "source_evidence": "打印机 | 甲 | AB 10 | 1 | 100.00", **updates,
    }


def rows(diff, entity_type=None, field=None):
    return [row for row in diff["changes"]
            if (entity_type is None or row["entity_type"] == entity_type)
            and (field is None or row["field"] == field)]


@pytest.mark.parametrize("left,right,field", [
    (Decimal("1.000"), "1.0", "quantity"),
    ("1000.0", "1,000.00", "total_price"),
    ("+1e3", 1000, "project_budget"),
    ("-0.00", "0", "award_amount"),
    ({"b": "1.00", "a": {"quantity": "2.0"}},
     {"a": {"quantity": "2.00"}, "b": "1.00"}, ""),
    ('{"b":1.00,"a":[2]}', '{"a":[2.0],"b":1}', "source_json"),
    ("  A  B \n", "A B", "product_name"),
])
def test_value_normalization_preserves_semantics(left, right, field):
    assert normalize_value(left, field) == normalize_value(right, field)


@pytest.mark.parametrize("left,right,field", [
    ("01", "1", "package_code"),
    ("AB", "A B", "model"),
    ("10", "1 0", "quantity"),
    ("供应商甲", "供应商乙", "organization_name"),
    (True, "1", "quantity"),
    ("1,00", "100", "total_price"),
])
def test_normalization_does_not_merge_real_values(left, right, field):
    assert normalize_value(left, field) != normalize_value(right, field)


def test_numeric_normalization_does_not_round_long_decimals():
    raw = "123456789012345678901234567890.12345678900"
    assert normalize_value(raw, "unit_price") == raw[:-2]


def test_identical_snapshots_have_no_changes_and_never_mutate_inputs():
    before = version(1, items=[item()], metadata={"project_name": "原项目"})
    after = deepcopy(before)
    after["version_id"], after["notice_id"] = 2, 2
    after["snapshot"]["items"][0]["id"] = 20
    original = deepcopy((before, after))
    diff = compare_snapshots(before, after)
    assert diff["changes"] == []
    assert diff["summary"]["total"] == 0
    assert (before, after) == original


def test_metadata_name_buyer_number_and_amount_changes_are_detected():
    before = version(1, metadata={
        "project_name": "原项目", "project_number": "2026-A", "procurement_unit": "原单位",
        "project_budget": "100", "announced_total_award": None,
    })
    after = version(2, metadata={
        "project_name": "新项目", "project_number": "2026-B", "procurement_unit": "新单位",
        "project_budget": "101", "announced_total_award": "95",
    })
    diff = compare_snapshots(before, after)
    assert {row["field"] for row in rows(diff, "metadata")} == {
        "project_name", "project_number", "procurement_unit", "project_budget",
        "announced_total_award",
    }
    assert diff["summary"]["semantic"] == 5
    assert rows(diff, "metadata", "announced_total_award")[0]["change_type"] == "added"


def test_equivalent_amounts_are_format_changes_and_json_order_is_ignored():
    before = version(1, items=[item(quantity="1.0")], metadata={"project_budget": "100.0"})
    after = version(2, items=[item(quantity="1.00")], metadata={"project_budget": "100.00"})
    evidence = {"source_file": "notice.html", "source_location": "line:1",
                "source_evidence": "项目预算：100"}
    before["snapshot"]["metadata_evidence"] = {"project_budget": evidence}
    after["snapshot"]["metadata_evidence"] = {"project_budget": dict(reversed(evidence.items()))}
    diff = compare_snapshots(before, after)
    assert diff["summary"]["semantic"] == 0
    assert diff["summary"]["format_only"] == 2
    assert diff["summary"]["provenance_only"] == 0


def test_html_whitespace_attributes_comments_and_json_order_have_no_semantic_diff():
    old_html = '<p class="a" id="x">项目名称：  打印机</p><p>金额：100</p>'
    new_html = '<p id="x" class="a">\n项目名称： 打印机\n</p>\n<!--说明--><p>金额：100</p>'
    before = version(1, body=[{"source_file": "a.html", "text": old_html}])
    after = version(2, body=[{"source_file": "a.html", "text": new_html}])
    diff = compare_snapshots(before, after)
    assert diff["summary"]["semantic"] == 0
    assert diff["summary"]["format_only"] == 1
    assert rows(diff, "body")[0]["field"] == "text"


@pytest.mark.parametrize("old,new", [
    ("<p>金额：100</p>", "<p>金额：101</p>"),
    ("<p>供应商甲</p>", "<p>供应商乙</p>"),
    ("<p>AB</p>", "<p>A B</p>"),
    ("<p><span>1</span><span>0</span></p>", "<p><span>1</span> <span>0</span></p>"),
])
def test_body_real_text_and_embedded_spaces_are_not_erased(old, new):
    diff = compare_snapshots(version(1, body=[{"source_file": "a.html", "text": old}]),
                             version(2, body=[{"source_file": "a.html", "text": new}]))
    assert diff["summary"]["semantic"] == 1


def test_files_added_removed_and_replaced_with_unknown_binary_semantics():
    before = version(1, source_files=[
        {"source_file": "old.pdf", "sha256": "a" * 64, "byte_size": 100},
        {"source_file": "changed.pdf", "sha256": "b" * 64, "byte_size": 100},
    ])
    after = version(2, source_files=[
        {"source_file": "added.pdf", "sha256": "c" * 64, "byte_size": 100},
        {"source_file": "changed.pdf", "sha256": "d" * 64, "byte_size": 120},
    ])
    diff = compare_snapshots(before, after)
    file_rows = rows(diff, "source_file")
    assert {row["change_type"] for row in file_rows} == {"added", "removed", "changed"}
    replacement = rows(diff, "source_file", "sha256")[0]
    assert replacement["before"] == "b" * 64 and replacement["after"] == "d" * 64
    assert replacement["classification"] == "possible_semantic"
    assert replacement["requires_manual_confirmation"]
    assert rows(diff, "source_file", "byte_size")[0]["after"] == 120


def test_hash_change_is_format_only_only_with_equivalent_normalized_hashes():
    before = version(1, source_files=[{
        "source_file": "a.html", "sha256": "a" * 64, "byte_size": 100,
        "normalized_sha256": "c" * 64, "kind": "html",
    }])
    after = version(2, source_files=[{
        "source_file": "a.html", "sha256": "b" * 64, "byte_size": 130,
        "normalized_sha256": "c" * 64, "kind": "html",
    }])
    diff = compare_snapshots(before, after)
    assert diff["summary"]["format_only"] == 2
    assert diff["summary"]["semantic"] == 0
    after["snapshot"]["source_files"][0]["normalized_sha256"] = "d" * 64
    assert compare_snapshots(before, after)["summary"]["semantic"] == 2


def test_same_file_bytes_under_new_name_are_a_tentative_provenance_change():
    before = version(1, source_files=[{"source_file": "old.pdf", "sha256": "a" * 64,
                                     "byte_size": 100}])
    after = version(2, source_files=[{"source_file": "new.pdf", "sha256": "a" * 64,
                                    "byte_size": 100}])
    diff = compare_snapshots(before, after)
    assert diff["summary"]["semantic"] == 0
    assert diff["summary"]["provenance_only"] == 1
    assert diff["changes"][0]["requires_manual_confirmation"]


def test_packages_added_removed_and_code_change_require_confirmation():
    before = version(1, packages=[
        {"package_code": "1", "package_name": "教学设备"},
        {"package_code": "2", "package_name": "删除包"},
    ])
    after = version(2, packages=[
        {"package_code": "A", "package_name": "教学设备"},
        {"package_code": "3", "package_name": "新包"},
    ])
    diff = compare_snapshots(before, after)
    assert {row["change_type"] for row in rows(diff, "package")} == {
        "added", "removed", "changed",
    }
    code = rows(diff, "package", "package_code")[0]
    assert code["before"] == "1" and code["after"] == "A"
    assert code["requires_manual_confirmation"]


def test_package_name_change_with_stable_code_is_detected():
    diff = compare_snapshots(version(1, packages=[{"package_code": "1", "package_name": "旧"}]),
                             version(2, packages=[{"package_code": "1", "package_name": "新"}]))
    assert rows(diff, "package", "package_name")[0]["after"] == "新"
    assert not rows(diff, "package", "package_name")[0]["requires_manual_confirmation"]


def test_bidder_name_outcome_additions_and_removals():
    before = version(1, bidders=[
        {"id": 10, "package_code": "1", "organization_name": "旧名", "outcome": "unknown",
         "source_file": "n.html", "source_location": "table:1/row:2"},
        {"package_code": "2", "organization_name": "被删供应商", "outcome": "nonwinner"},
    ])
    after = version(2, bidders=[
        {"id": 20, "package_code": "1", "organization_name": "新名", "outcome": "winner",
         "source_file": "n.html", "source_location": "table:1/row:2"},
        {"package_code": "3", "organization_name": "新增供应商", "outcome": "unknown"},
    ])
    diff = compare_snapshots(before, after)
    assert rows(diff, "bidder", "organization_name")[0]["requires_manual_confirmation"]
    assert rows(diff, "bidder", "outcome")[0]["after"] == "winner"
    assert {row["change_type"] for row in rows(diff, "bidder")} == {
        "added", "removed", "changed",
    }


def test_award_amount_change_and_multiaward_add_remove():
    before = version(1, awards=[
        {"package_code": "1", "organization_name": "供应商甲", "award_amount": "100"},
        {"package_code": "1", "organization_name": "供应商乙", "award_amount": "100"},
    ])
    after = version(2, awards=[
        {"package_code": "1", "organization_name": "供应商甲", "award_amount": "110"},
        {"package_code": "1", "organization_name": "供应商丙", "award_amount": "110"},
    ])
    diff = compare_snapshots(before, after)
    amount = rows(diff, "award", "award_amount")[0]
    assert amount["before"] == "100" and amount["after"] == "110"
    assert not amount["requires_manual_confirmation"]
    assert len(rows(diff, "award", "*")) == 2


@pytest.mark.parametrize("field,value", [
    ("product_name", "扫描仪"), ("category", "其他设备"), ("brand", "乙"),
    ("model", "AB 11"), ("quantity", "2"), ("quantity_unit", "套"),
    ("unit_price", "101"), ("total_price", "102"), ("package_code", "2"),
])
def test_every_item_field_change_remains_visible(field, value):
    before = version(1, items=[item()])
    after = version(2, items=[item(id=20, **{field: value})])
    diff = compare_snapshots(before, after)
    assert rows(diff, "item", field)[0]["after"] == value
    assert rows(diff, "item", field)[0]["classification"] == "possible_semantic"
    if field in {"product_name", "brand", "model", "package_code"}:
        assert rows(diff, "item", field)[0]["requires_manual_confirmation"]


def test_item_add_and_remove_do_not_use_list_position_or_database_id():
    before = version(1, items=[item(source_file=None, source_location=None)])
    after = version(2, items=[item(product_name="不同标的", model="XX", brand="乙",
                                    source_file=None, source_location=None)])
    diff = compare_snapshots(before, after)
    assert {row["change_type"] for row in rows(diff, "item")} == {"added", "removed"}
    assert len(rows(diff, "item", "*")) == 2


def test_true_stable_entity_id_can_link_name_and_location_changes():
    before = version(1, items=[item(stable_id="official-item-1")])
    after = version(2, items=[item(id=20, stable_id="official-item-1", product_name="扫描仪",
                                    source_location="sheet:2/row:3")])
    diff = compare_snapshots(before, after)
    assert not rows(diff, "item", "product_name")[0]["requires_manual_confirmation"]
    assert rows(diff, "item", "source_location")[0]["classification"] == "provenance_only"


def test_field_evidence_and_old_new_candidate_ids_remain_clickable():
    old_evidence = {"source_file": "old.xlsx", "source_location": "sheet:1/row:2/column:4",
                    "source_evidence": "100", "source_sha256": "a" * 64}
    new_evidence = {"source_file": "new.xlsx", "source_location": "sheet:1/row:4/column:5",
                    "source_evidence": "110", "source_sha256": "b" * 64}
    before = version(1, items=[item(field_evidence={"unit_price": old_evidence})])
    after = version(2, items=[item(id=20, unit_price="110",
                                    field_evidence={"unit_price": new_evidence})])
    diff = compare_snapshots(before, after)
    price = rows(diff, "item", "unit_price")[0]
    assert price["before_source"] == {
        "version_id": 1, "notice_id": 1, "dataset_id": "default", "candidate_id": 10,
        **old_evidence,
    }
    assert price["after_source"] == {
        "version_id": 2, "notice_id": 2, "dataset_id": "default", "candidate_id": 20,
        **new_evidence,
    }
    provenance = rows(diff, "item", "field_evidence.unit_price")[0]
    assert provenance["classification"] == "provenance_only"
    assert provenance["after_source"]["source_location"] == new_evidence["source_location"]


def test_metadata_evidence_change_links_the_actual_field_source():
    before = version(1, metadata={"procurement_unit": "甲"}, metadata_evidence={
        "procurement_unit": {"source_file": "old.html", "source_location": "line:1",
                             "source_evidence": "采购单位：甲"},
    })
    after = version(2, metadata={"procurement_unit": "乙"}, metadata_evidence={
        "procurement_unit": {"source_file": "new.html", "source_location": "line:2",
                             "source_evidence": "采购单位：乙"},
    })
    diff = compare_snapshots(before, after)
    buyer = rows(diff, "metadata", "procurement_unit")[0]
    assert buyer["before_source"]["source_file"] == "old.html"
    assert buyer["after_source"]["source_location"] == "line:2"
    assert rows(diff, "metadata", "metadata_evidence.procurement_unit")[0][
        "classification"] == "provenance_only"


def test_duplicate_rows_are_preserved_as_a_multiset_with_distinct_keys():
    before = version(1, items=[item(id=10), item(id=11)])
    after = version(2, items=[item(id=20), item(id=21)])
    assert compare_snapshots(before, after)["changes"] == []
    unchanged = compare_snapshots(before, after, include_unchanged=True)
    assert len(rows(unchanged, "item", "product_name")) == 2
    assert len({row["entity_key"] for row in rows(unchanged, "item", "product_name")}) == 2
    after["snapshot"]["items"].pop()
    diff = compare_snapshots(before, after)
    assert len(rows(diff, "item", "*")) == 1
    assert rows(diff, "item", "*")[0]["change_type"] == "removed"


def test_ambiguous_duplicate_changes_are_not_silently_paired_or_lost():
    before = version(1, items=[item(id=10, unit_price="100"), item(id=11, unit_price="101")])
    after = version(2, items=[item(id=20, unit_price="110"), item(id=21, unit_price="111")])
    diff = compare_snapshots(before, after)
    assert len(rows(diff, "item", "*")) == 4
    assert diff["summary"]["by_change_type"] == {"removed": 2, "added": 2}
    assert all(row["requires_manual_confirmation"] for row in diff["changes"])


def test_duplicate_residual_pair_requires_confirmation():
    before = version(1, items=[item(id=10), item(id=11)])
    after = version(2, items=[item(id=20), item(id=21, unit_price="110")])
    diff = compare_snapshots(before, after)
    assert len(rows(diff, "item", "unit_price")) == 1
    assert rows(diff, "item", "unit_price")[0]["requires_manual_confirmation"]


def test_row_reordering_has_no_diff_and_distinct_locations_resolve_duplicates():
    first, second = item(id=10), item(id=11, source_location="sheet:1/row:3", quantity="2")
    before = version(1, items=[first, second])
    after = version(2, items=[deepcopy(second), deepcopy(first)])
    assert compare_snapshots(before, after)["changes"] == []
    after["snapshot"]["items"][0]["unit_price"] = "110"
    diff = compare_snapshots(before, after)
    assert len(rows(diff, "item", "unit_price")) == 1
    assert rows(diff, "item", "unit_price")[0]["before_source"]["candidate_id"] == 11


def test_uncertain_notice_identity_and_unverified_field_are_manual():
    before = version(1, metadata={"project_name": "旧"})
    after = version(2, metadata={"project_name": "新"})
    after["identity_status"] = "manual_link_required"
    assert all(row["requires_manual_confirmation"]
               for row in compare_snapshots(before, after)["changes"])
    after["identity_status"] = "matched"
    after["snapshot"]["metadata_field_status"] = {"project_name": "unverified"}
    assert rows(compare_snapshots(before, after), "metadata", "project_name")[0][
        "requires_manual_confirmation"]


@pytest.mark.parametrize("field", ["dataset_id", "group_id"])
def test_cross_dataset_and_cross_notice_groups_cannot_be_compared(field):
    before, after = version(1), version(2)
    after[field] = "other"
    with pytest.raises(ValueError, match=field):
        compare_snapshots(before, after)


def test_empty_state_summary_and_unchanged_selection():
    assert compare_snapshots(version(1), version(2))["summary"] == {
        "total": 0, "semantic": 0, "format_only": 0, "provenance_only": 0,
        "requires_manual_confirmation": 0, "by_entity_type": {}, "by_change_type": {},
    }
    before = version(1, metadata={"project_name": "同一项目"})
    after = version(2, metadata={"project_name": "同一项目"})
    diff = compare_snapshots(before, after, include_unchanged=True)
    assert diff["summary"]["by_change_type"] == {"unchanged": 1}
    assert diff["changes"][0]["classification"] == "unchanged"
