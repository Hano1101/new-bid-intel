import json
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import review_queue
from app.config import settings
from app.datasets import resolve_database
from app.main import app
from app.schemas import ImportResult, ItemCandidate, NoticeMetadata, ParticipantCandidate
from app.storage import connect, save_import


def _seed(path, title, *, warnings=None, item_count=1, source_key=None, replace_existing=False):
    items = [ItemCandidate(
        product_name=f"候选 {index}", quantity=2, unit_price=10, total_price=25,
        package_code="default" if index % 2 else "P1",
        source_file="notice.html", source_location=f"table:1/row:{index}",
        source_evidence="项目名称 | 候选文本" if index == 1 else None,
        field_status={"product_name": "present", "quantity": "present",
                      "unit_price": "present", "total_price": "present"},
        field_evidence={field: {
            "source_file": "notice.html", "source_location": f"row:{index}",
            "source_evidence": f"{field} 原文",
        } for field in ("quantity", "unit_price", "total_price")},
    ) for index in range(1, item_count + 1)]
    result = ImportResult(
        notice_id=0, source_files=["notice.html"], items_found=len(items), items=items,
        metadata=NoticeMetadata(project_name=title, project_number=f"NO-{title}"),
        participants=[
            ParticipantCandidate(organization_name=f"投标方 {title}", outcome="nonwinner",
                                 package_code="P1", source_file="notice.html",
                                 source_location="table:2/row:2", source_evidence=None),
            ParticipantCandidate(organization_name=f"中标方 {title}", outcome="winner",
                                 package_code="P1", award_amount=100, source_file="notice.html",
                                 source_location="table:2/row:3", source_evidence="中标方原文"),
        ],
        warnings=warnings or [],
    )
    return save_import(path, result, source_key=source_key, replace_existing=replace_existing)


def _rows(client, headers=None, **params):
    response = client.get("/api/v1/review-queue", headers=headers or {}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _decision(client, candidate_type, candidate_id, payload, headers=None):
    candidate_epoch = payload.get("candidate_epoch")
    if candidate_epoch is None:
        rows = _rows(client, headers=headers, status="all", candidate_type=candidate_type)["items"]
        current = next((row for row in rows if row["candidate_id"] == candidate_id), None)
        candidate_epoch = current["candidate_epoch"] if current else 1
    return client.post(
        f"/api/v1/review-queue/{candidate_type}/{candidate_id}/decisions",
        headers=headers or {}, json={**payload, "candidate_epoch": candidate_epoch},
    )


def test_queue_explains_field_evidence_default_package_parser_and_relation_signals():
    warnings = [
        "scan.pdf: 第 1 页无可提取文本，OCR 未启用",
        "files.zip: 附件容器展开失败（BadZipFile）",
    ]
    with TestClient(app) as client:
        _seed(resolve_database("default"), "触发规则", warnings=warnings)
        result = _rows(client, status="all")

    assert result["total"] == 4
    rows = {(row["candidate_type"], row["candidate_id"]): row for row in result["items"]}
    item = next(row for row in rows.values() if row["candidate_type"] == "item")
    reasons = [reason["detail"] for reason in item["reasons"]]
    assert any("字段“品目”当前为空" in reason for reason in reasons)
    assert any("字段“标的名称”有值，但缺少完整字段级来源证据" in reason for reason in reasons)
    assert any("数量 × 单价 = 20" in reason and "当前总价 25" in reason for reason in reasons)
    assert any("系统占位值 default" in reason for reason in reasons)
    assert any("ocr_skipped" in reason for reason in reasons)
    assert any("archive_failure" in reason for reason in reasons)
    assert item["priority"]["rank"] == 1

    bids = [row for row in rows.values() if row["candidate_type"] == "bid"]
    assert len(bids) == 2
    missing_evidence_bid = next(row for row in bids if row["source_evidence"] is None)
    assert any("缺少来源片段" in reason["detail"] for reason in missing_evidence_bid["reasons"])
    assert missing_evidence_bid["evidence_url"] == f"/api/v1/notices/{missing_evidence_bid['notice_id']}"


def test_queue_sorting_pagination_filters_and_handled_state_are_deterministic():
    with TestClient(app) as client:
        path = resolve_database("default")
        _seed(path, "排序甲", item_count=3)
        _seed(path, "排序乙", item_count=2)

        first = _rows(client, status="all", limit=3, offset=0)
        second = _rows(client, status="all", limit=3, offset=3)
        third = _rows(client, status="all", limit=3, offset=6)
        all_rows = _rows(client, status="all", limit=20)["items"]
        assert first["total"] == len(all_rows)
        assert first["items"] + second["items"] + third["items"] == all_rows
        keys = [(row["priority"]["rank"], row["notice_id"],
                 {"item": 0, "bid": 1, "award": 2}[row["candidate_type"]],
                 row["candidate_id"]) for row in all_rows]
        assert keys == sorted(keys)

        only_bids = _rows(client, status="all", candidate_type="bid")
        assert only_bids["total"] == 2
        assert {row["candidate_type"] for row in only_bids["items"]} == {"bid"}
        target = next(row for row in all_rows if row["candidate_type"] == "item")
        accepted = _decision(client, "item", target["candidate_id"],
                             {"action": "accepted", "reason": "已对照公告核验"})
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["candidate_snapshot"]["source_evidence"] == "项目名称 | 候选文本"

        pending = _rows(client, status="pending")
        processed = _rows(client, status="processed")
        assert target["candidate_id"] not in {row["candidate_id"] for row in pending["items"]
                                               if row["candidate_type"] == "item"}
        handled = next(row for row in processed["items"] if row["candidate_type"] == "item")
        assert handled["status"] == "processed"
        assert handled["latest_review"]["action"] == "accepted"


def test_bid_and_award_missing_file_and_location_have_specific_explanations():
    with TestClient(app) as client:
        path = resolve_database("default")
        _seed(path, "来源缺失")
        with connect(path) as connection:
            for table in ("bid_participations", "awards"):
                connection.execute(
                    f"UPDATE {table} SET source_file=NULL, source_location=NULL, source_evidence=NULL",
                )
        for kind in ("bid", "award"):
            rows = _rows(client, candidate_type=kind)["items"]
            assert rows
            for row in rows:
                reasons = {reason["code"]: reason["detail"] for reason in row["reasons"]}
                assert reasons["source_evidence_missing"] == f"{kind}记录缺少来源片段"
                assert reasons["source_file_missing"] == f"{kind}记录缺少来源文件"
                assert reasons["source_location_missing"] == f"{kind}记录缺少原文定位"


def test_accept_correct_reject_keep_original_candidate_and_append_auditable_values():
    with TestClient(app) as client:
        _seed(resolve_database("default"), "动作记录", warnings=["scan.pdf: OCR 未识别到可信文本"])
        with connect(resolve_database("default")) as connection:
            original_candidates = {
                table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
                for table in ("procurement_items", "bid_participations", "awards")
            }
            item_id = connection.execute("SELECT id FROM procurement_items ORDER BY id LIMIT 1").fetchone()[0]
            bid_id = connection.execute("SELECT id FROM bid_participations ORDER BY id LIMIT 1").fetchone()[0]
            award_id = connection.execute("SELECT id FROM awards ORDER BY id LIMIT 1").fetchone()[0]
            original_name = connection.execute(
                "SELECT product_name FROM procurement_items WHERE id=?", (item_id,),
            ).fetchone()[0]

        accepted = _decision(client, "item", item_id,
                             {"action": "accepted", "reason": "原文片段一致"})
        corrected = _decision(client, "bid", bid_id, {
            "action": "corrected", "reason": "根据公告主体列表修正名称",
            "corrected_values": {"organization_name": "人工核验主体"},
        })
        rejected = _decision(client, "award", award_id,
                             {"action": "rejected", "reason": "来源内容不支持该中标记录"})
        assert (accepted.status_code, corrected.status_code, rejected.status_code) == (201, 201, 201)
        event = corrected.json()
        assert event["before_values"]["organization_name"] == "投标方 动作记录"
        assert event["after_values"]["organization_name"] == "人工核验主体"
        assert event["changes"]["organization_name"] == {
            "before": "投标方 动作记录", "after": "人工核验主体",
        }
        assert event["reason"] == "根据公告主体列表修正名称"
        assert event["actor"] == "local-reviewer"
        datetime.fromisoformat(event["created_at"])
        assert event["candidate_snapshot"]["source_file"] == "notice.html"
        assert event["candidate_snapshot"]["source_location"] == "table:2/row:2"

        history = client.get(f"/api/v1/review-queue/bid/{bid_id}/history").json()["events"]
        assert len(history) == 1 and history[0]["changes"] == event["changes"]
        assert rejected.json()["action"] == "rejected"
        assert rejected.json()["before_values"] == rejected.json()["after_values"]
        with connect(resolve_database("default")) as connection:
            for table, originals in original_candidates.items():
                assert [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} ORDER BY id",
                )] == originals
            assert connection.execute(
                "SELECT product_name FROM procurement_items WHERE id=?", (item_id,),
            ).fetchone()[0] == original_name
            assert connection.execute(
                "SELECT raw_name FROM bid_participations WHERE id=?", (bid_id,),
            ).fetchone()[0] == "投标方 动作记录"
            assert connection.execute(
                "SELECT raw_name FROM awards WHERE id=?", (award_id,),
            ).fetchone()[0] == "中标方 动作记录"


def test_rejects_invalid_or_forged_decisions_and_duplicate_operations():
    with TestClient(app) as client:
        _seed(resolve_database("default"), "非法请求")
        candidate_id = client.get("/api/v1/review-queue", params={"candidate_type": "item"}).json()[
            "items"][0]["candidate_id"]
        path = f"/api/v1/review-queue/item/{candidate_id}/decisions"
        assert _decision(client, "item", candidate_id, {"action": "unknown", "reason": "x"}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "accepted", "reason": " "}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "accepted", "reason": "ok", "actor": "伪造"}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "accepted", "reason": "ok",
                                      "corrected_values": {"brand": "X"}}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "corrected", "reason": "ok",
                                      "corrected_values": {"confidence": 0.99}}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "corrected", "reason": "ok",
                                      "corrected_values": {"source_evidence": "伪造"}}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "corrected", "reason": "ok",
                                      "corrected_values": {"total_price": "NaN"}}).status_code == 422
        assert _decision(client, "item", candidate_id, {"action": "corrected", "reason": "ok",
                                      "corrected_values": {}}).status_code == 422
        assert client.post(path, json={"action": "accepted", "reason": "缺少版本"}).status_code == 422
        for epoch in (0, True, "1", 1.0):
            assert client.post(path, json={"action": "accepted", "reason": "非法版本",
                                          "candidate_epoch": epoch}).status_code == 422
        first_payload = {"action": "rejected", "reason": "不支持"}
        first = _decision(client, "item", candidate_id, first_payload)
        assert first.status_code == 201
        assert _decision(client, "item", candidate_id, first_payload).status_code == 409
        revised = _decision(client, "item", candidate_id, {"action": "corrected", "reason": "补充核验后修正",
                                                            "corrected_values": {"brand": "核对品牌"}})
        assert revised.status_code == 201
        history = client.get(f"/api/v1/review-queue/item/{candidate_id}/history").json()["events"]
        assert [event["action"] for event in history] == ["rejected", "corrected"]
        assert history[1]["before_values"]["brand"] is None
        assert history[1]["after_values"]["brand"] == "核对品牌"
        assert _decision(client, "item", 99999,
                         {"action": "accepted", "reason": "不存在"}).status_code == 404


def test_review_events_and_queue_are_isolated_by_dataset_header():
    with TestClient(app) as client:
        default_path = resolve_database("default")
        _seed(default_path, "默认库")
        item_id = client.get("/api/v1/review-queue", params={"candidate_type": "item"}).json()[
            "items"][0]["candidate_id"]
        created = client.post("/api/v1/datasets", json={"name": "复核隔离"})
        assert created.status_code == 201
        dataset_id = created.json()["id"]
        headers = {"X-Dataset-ID": dataset_id}
        _seed(resolve_database(dataset_id), "隔离库")
        assert client.get("/api/v1/review-queue", headers=headers).json()["total"] == 2
        assert _decision(client, "item", item_id,
                         {"action": "accepted", "reason": "默认库决定"}).status_code == 201
        assert client.get("/api/v1/review-queue", headers=headers,
                          params={"status": "processed"}).json()["total"] == 0
        assert client.get(f"/api/v1/review-queue/item/{item_id}/history",
                          headers=headers).json()["events"] == []
        assert client.get("/api/v1/review-queue", params={"status": "processed"}).json()["total"] == 1
        assert client.get("/api/v1/review-queue", headers={"X-Dataset-ID": "f" * 32}).status_code == 404


def test_replaced_import_with_reused_candidate_id_does_not_reuse_review_state():
    with TestClient(app) as client:
        path = resolve_database("default")
        _seed(path, "替换前项目", source_key="replaceable-notice")
        old_row = _rows(client, candidate_type="item")["items"][0]
        accepted = _decision(client, "item", old_row["candidate_id"], {
            "action": "accepted", "reason": "替换前已人工核验",
        })
        assert accepted.status_code == 201

        _seed(path, "替换后项目", source_key="replaceable-notice", replace_existing=True)
        replacement = _rows(client, candidate_type="item")["items"][0]
        assert replacement["candidate_id"] == old_row["candidate_id"]
        assert replacement["status"] == "pending"
        assert replacement["latest_review"] is None
        assert replacement["candidate_epoch"] == 2
        stale = _decision(client, "item", replacement["candidate_id"], {
            "action": "corrected", "reason": "旧页面提交的修正", "candidate_epoch": 1,
            "corrected_values": {"product_name": "错误写入新候选"},
        })
        assert stale.status_code == 409
        previous_history = client.get(
            f"/api/v1/review-queue/item/{replacement['candidate_id']}/history",
        ).json()["events"]
        assert [(event["candidate_epoch"], event["reason"]) for event in previous_history] == [
            (1, "替换前已人工核验"),
        ]

        second = _decision(client, "item", replacement["candidate_id"], {
            "action": "accepted", "reason": "替换后重新核验",
        })
        assert second.status_code == 201
        history = client.get(
            f"/api/v1/review-queue/item/{replacement['candidate_id']}/history",
        ).json()["events"]
        assert [(event["candidate_epoch"], event["reason"]) for event in history] == [
            (1, "替换前已人工核验"), (2, "替换后重新核验"),
        ]
        with connect(path) as connection:
            events = connection.execute(
                "SELECT candidate_epoch, reason FROM review_events "
                "WHERE candidate_type='item' AND candidate_id=? ORDER BY id",
                (replacement["candidate_id"],),
            ).fetchall()
        assert [(row["candidate_epoch"], row["reason"]) for row in events] == [
            (1, "替换前已人工核验"), (2, "替换后重新核验"),
        ]


def test_empty_queue_has_paging_shape_and_unknown_filters_fail_cleanly():
    with TestClient(app) as client:
        result = _rows(client)
        assert result == {"items": [], "total": 0, "status": "pending", "limit": 50, "offset": 0}
        assert client.get("/api/v1/review-queue", params={"candidate_type": "project"}).status_code == 422
        assert client.get("/api/v1/review-queue", params={"status": "open"}).status_code == 422


def test_queue_snapshot_cannot_mix_candidate_values_with_replaced_import_epoch(monkeypatch):
    with TestClient(app) as client:
        path = resolve_database("default")
        _seed(path, "读取时的旧项目", source_key="concurrent-notice")
        original_loader = review_queue._load_candidates
        blocked_replacement = []

        def attempt_delete_between_candidate_and_epoch_reads(connection):
            candidates = original_loader(connection)
            # A second importer cannot delete the snapshot before its epoch is read.
            with connect(path) as other:
                other.execute("PRAGMA busy_timeout = 0")
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    other.execute("DELETE FROM notices")
            blocked_replacement.append(True)
            return candidates

        monkeypatch.setattr(review_queue, "_load_candidates", attempt_delete_between_candidate_and_epoch_reads)
        old_row = _rows(client, candidate_type="item")["items"][0]
        assert blocked_replacement == [True]
        assert old_row["candidate_epoch"] == 1
        assert old_row["project_name"] == "读取时的旧项目"
        monkeypatch.setattr(review_queue, "_load_candidates", original_loader)

        _seed(path, "读取后的新项目", source_key="concurrent-notice", replace_existing=True)
        stale = _decision(client, "item", old_row["candidate_id"], {
            "candidate_epoch": old_row["candidate_epoch"],
            "action": "accepted", "reason": "旧快照决定",
        })
        assert stale.status_code == 409
        assert _rows(client, status="processed")["total"] == 0


def test_evidenced_explicit_omissions_do_not_create_missing_field_queue_items():
    with TestClient(app) as client:
        path = resolve_database("default")
        _seed(path, "明确未公示")
        statuses = {
            "product_name": "present", "category": "explicitly_not_published",
            "brand": "explicitly_not_published", "model": "explicitly_not_published",
            "quantity": "present", "quantity_unit": "explicitly_not_published",
            "unit_price": "present", "total_price": "present",
        }
        evidence = {field: {
            "source_file": "notice.html", "source_location": f"field:{field}",
            "source_evidence": f"原文确认 {field} 未公示",
        } for field in statuses}
        evidence.update({
            "product_name": {"source_file": "notice.html", "source_location": "row:1",
                             "source_evidence": "标的名称：示例"},
            "quantity": {"source_file": "notice.html", "source_location": "row:1",
                         "source_evidence": "数量：2"},
            "unit_price": {"source_file": "notice.html", "source_location": "row:1",
                           "source_evidence": "单价：10"},
            "total_price": {"source_file": "notice.html", "source_location": "row:1",
                            "source_evidence": "总价：25"},
        })
        with connect(path) as connection:
            connection.execute(
                "UPDATE procurement_items SET package_id=(SELECT id FROM packages WHERE package_code='P1'), "
                "total_price='20', field_status_json=?, field_evidence_json=?",
                (json.dumps(statuses), json.dumps(evidence)),
            )
            connection.execute(
                "UPDATE bid_participations SET source_evidence='投标方原文'",
            )
            candidate_id = connection.execute("SELECT id FROM procurement_items").fetchone()[0]

        assert _rows(client)["total"] == 0
        assert _decision(client, "item", candidate_id,
                         {"action": "accepted", "reason": "不满足任何队列规则"}).status_code == 409


def test_authenticated_reviewer_is_saved_as_operator(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_username", "reviewer")
    monkeypatch.setattr(settings, "auth_password", "a-test-only-password")
    monkeypatch.setattr(settings, "auth_secret_key", "a-test-only-secret-key-with-enough-entropy")
    with TestClient(app) as client:
        _seed(resolve_database("default"), "登录审核")
        assert client.get("/api/v1/review-queue").status_code == 401
        login = client.post("/api/v1/auth/login", json={
            "username": "reviewer", "password": "a-test-only-password",
        })
        assert login.status_code == 200
        row = client.get("/api/v1/review-queue", params={"candidate_type": "item"}).json()["items"][0]
        response = _decision(client, "item", row["candidate_id"], {
            "action": "accepted", "reason": "已登录后核验",
        })
        assert response.status_code == 201
        assert response.json()["actor"] == "reviewer"
