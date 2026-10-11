"""Synthetic-only API contracts. No model transport or evaluation artifacts."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ImportResult, ItemCandidate, NoticeMetadata
from app.storage import connect, save_import


def payload(title="办公采购", buyer="采购中心", body="公告正文"):
    result = ImportResult(
        notice_id=0, source_files=["notice.html"], items_found=1,
        metadata=NoticeMetadata(project_name=title, project_number="TEST-1",
                                procurement_unit=buyer, project_budget=100),
        items=[ItemCandidate(product_name="打印机", quantity=1, unit_price=100, total_price=100,
                             source_file="notice.html", source_location="table:1/row:2",
                             source_evidence=f"{title} 打印机 100元")],
    )
    return {"snapshot": result.model_dump(mode="json"),
            "identity": {"official_notice_id": "NOTICE-1", "namespace": "synthetic"},
            "sources": [{"source_file": "notice.html",
                         "sha256": hashlib.sha256(body.encode()).hexdigest(),
                         "byte_size": len(body.encode())}],
            "body_texts": {"notice.html": body}}


def post(client, body, headers=None):
    response = client.post("/api/v1/notice-version-imports", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_version_history_detail_latest_compare_summary_and_frozen_evidence(monkeypatch):
    from app import model_adapter

    def forbidden(*args, **kwargs):
        pytest.fail("version imports must not call a model")

    monkeypatch.setattr(model_adapter, "extract_unstructured_items", forbidden)
    with TestClient(app) as client:
        old = post(client, payload())
        new = post(client, payload("更新办公采购", "第二采购中心", "更正正文"))
        assert new["version_status"] == "new_version"
        assert old["notice_id"] != new["notice_id"]
        for notice in (old, new):
            history = client.get(f'/api/v1/notice-versions/notices/{notice["notice_id"]}').json()
            assert len(history["versions"]) == 2
            assert history["latest_version_id"] == new["version_id"]
            assert [row["is_latest"] for row in history["versions"]] == [True, False]
        detail = client.get(f'/api/v1/notice-versions/versions/{old["version_id"]}').json()
        assert detail["snapshot"]["metadata"]["project_name"] == "办公采购"
        latest = client.get(f'/api/v1/notice-versions/notices/{old["notice_id"]}/latest').json()
        assert latest["version_id"] == new["version_id"]
        params = {"before_version_id": old["version_id"], "after_version_id": new["version_id"]}
        response = client.get("/api/v1/notice-versions/compare", params=params)
        assert response.status_code == 200
        diff = response.json()
        assert {row["field"] for row in diff["changes"]} >= {"project_name", "procurement_unit", "text"}
        item_change = next(row for row in diff["changes"] if row["entity_type"] == "item")
        for side, imported in (("before", old), ("after", new)):
            source = item_change[f"{side}_source"]
            assert source["notice_id"] == imported["notice_id"]
            frozen = client.get(f'/api/v1/notice-versions/versions/{source["version_id"]}/evidence')
            assert frozen.status_code == 200
            evidence = frozen.json()
            assert evidence["notice_id"] == source["notice_id"]
            assert source["candidate_id"] in {row["id"] for row in evidence["items"]}
        summary = client.get("/api/v1/notice-versions/summary", params=params).json()
        assert summary["summary"] == diff["summary"]
        identical = post(client, payload())
        assert identical["version_status"] == "duplicate_snapshot"
        assert identical["version_id"] == old["version_id"]
        assert client.get("/api/v1/health").json()["notices_imported"] == 2


def test_regular_upload_creates_versions_and_html_whitespace_is_only_format():
    with TestClient(app) as client:
        def upload(html):
            response = client.post("/api/v1/notices/import", files=[
                ("files", ("notice.html", html.encode(), "text/html")),
            ])
            assert response.status_code == 200, response.text
            return response.json()

        html = '<html><p class="notice" id="p">项目名称：办公采购</p><p>项目编号：TEST-1</p><p>采购单位：采购中心</p></html>'
        old = upload(html)
        new = upload(html.replace('class="notice" id="p"', 'id="p" class="notice"').replace("</p>", "</p>\n  "))
        assert old["version_id"] != new["version_id"]
        params = {"before_version_id": old["version_id"], "after_version_id": new["version_id"]}
        diff = client.get("/api/v1/notice-versions/compare", params=params).json()
        assert diff["summary"]["semantic"] == 0
        assert diff["summary"]["format_only"] >= 1
        duplicate = upload(html)
        assert duplicate["version_id"] == old["version_id"]
        assert duplicate["notice_id"] == old["notice_id"]


def test_dataset_scope_opaque_ids_different_groups_and_read_only_routes():
    with TestClient(app) as client:
        old = post(client, payload())
        dataset = client.post("/api/v1/datasets", json={"name": "版本测试集"}).json()["id"]
        headers = {"X-Dataset-ID": dataset}
        other = post(client, payload(), headers)
        assert other["version_id"] != old["version_id"]
        path = f'/api/v1/notice-versions/versions/{old["version_id"]}'
        assert client.get(path, headers=headers).status_code == 404
        assert client.get(path, headers={"X-Dataset-ID": "../outside"}).status_code == 422
        changed = payload()
        changed["identity"]["official_notice_id"] = "NOTICE-2"
        second = post(client, changed)
        params = {"before_version_id": old["version_id"], "after_version_id": second["version_id"]}
        assert client.get("/api/v1/notice-versions/compare", params=params).status_code == 409
        params["after_version_id"] = "'; DROP TABLE notices; --"
        assert client.get("/api/v1/notice-versions/compare", params=params).status_code == 422
        assert client.get("/api/v1/notice-versions/versions/outside.sqlite").status_code == 422
        for method in (client.post, client.put, client.patch, client.delete):
            assert method(path).status_code == 405
        unchanged = client.get(path, params={"sql": "DELETE FROM notices", "path": "../outside"})
        assert unchanged.status_code == 200
        assert client.get("/api/v1/health").json()["notices_imported"] == 2


def test_import_validation_rejects_sql_path_bytes_and_unfingerprinted_sources():
    with TestClient(app) as client:
        for extra in ("sql", "database_path", "raw_bytes", "manual_group_id"):
            body = payload()
            body[extra] = "arbitrary"
            assert client.post("/api/v1/notice-version-imports", json=body).status_code == 422
        body = payload()
        body["sources"][0]["byte_size"] = -1
        assert client.post("/api/v1/notice-version-imports", json=body).status_code == 422
        body = payload()
        body["snapshot"]["source_files"].append("missing.pdf")
        assert client.post("/api/v1/notice-version-imports", json=body).status_code == 422
        assert client.get("/api/v1/health").json()["notices_imported"] == 0


def test_untracked_legacy_notice_has_empty_history_without_backfill(tmp_path):
    from app.config import settings

    result = ImportResult.model_validate(payload()["snapshot"])
    saved = save_import(settings.resolved_database_path, result)
    with connect(settings.resolved_database_path) as connection:
        # Synthetic legacy notice after clearing links only; immutable versions
        # must not be manufactured by an evidence/history read.
        connection.execute("DELETE FROM notice_version_links WHERE notice_id=?", (saved.notice_id,))
    with TestClient(app) as client:
        path = f"/api/v1/notice-versions/notices/{saved.notice_id}"
        history = client.get(path).json()
        assert history["versions"] == [] and history["identity_status"] == "not_tracked"
        assert client.get(path + "/latest").status_code == 404


def test_replaced_projection_evidence_remains_frozen(tmp_path):
    from app.config import settings

    database = settings.resolved_database_path
    old = save_import(database, ImportResult.model_validate(payload()["snapshot"]), source_key="job:0",
                      source_documents=[("notice.html", b"old source")],
                      version_identity={"official_notice_id": "notice-1"})
    new = save_import(database, ImportResult.model_validate(payload("新版")["snapshot"]),
                      source_key="job:0", replace_existing=True,
                      source_documents=[("notice.html", b"new source")],
                      version_identity={"official_notice_id": "notice-1"})
    assert new.notice_id != old.notice_id
    with TestClient(app) as client:
        assert client.get(f"/api/v1/notices/{old.notice_id}").status_code == 404
        frozen = client.get(f"/api/v1/notice-versions/versions/{old.version_id}/evidence").json()
        assert frozen["metadata"]["project_name"] == "办公采购"
        assert frozen["items"][0]["source_evidence"] == "办公采购 打印机 100元"
        assert frozen["items"][0]["source_sha256"] == hashlib.sha256(b"old source").hexdigest()
        assert frozen["items"][0]["field_status"]["product_name"] == "unverified"
        assert client.get(f"/api/v1/notice-versions/notices/{old.notice_id}").json()["latest_version_id"] == new.version_id


def test_structured_package_name_change_does_not_modify_existing_projection_semantics():
    with TestClient(app) as client:
        body = payload()
        body["packages"] = [{"package_code": "default", "package_name": "办公设备包"}]
        old = post(client, body)
        body["packages"][0]["package_name"] = "更正设备包"
        new = post(client, body)
        params = {"before_version_id": old["version_id"], "after_version_id": new["version_id"]}
        changes = client.get("/api/v1/notice-versions/compare", params=params).json()["changes"]
        assert any(row["entity_type"] == "package" and row["field"] == "package_name"
                   and row["before"] == "办公设备包" and row["after"] == "更正设备包"
                   for row in changes)
        assert client.get(f'/api/v1/notices/{new["notice_id"]}').json()["packages"][0]["package_name"] is None
        body["packages"].append({"package_code": "default"})
        assert client.post("/api/v1/notice-version-imports", json=body).status_code == 422


def test_deleted_projection_notice_id_is_never_reassigned_to_another_history():
    from app.config import settings
    from app.notice_versions import list_versions

    database = settings.resolved_database_path
    first = save_import(database, ImportResult.model_validate(payload()["snapshot"]), source_key="job")
    second = save_import(database, ImportResult.model_validate(payload("新版")["snapshot"]),
                         source_key="job", replace_existing=True)
    restored = save_import(database, ImportResult.model_validate(payload()["snapshot"]),
                           source_key="job", replace_existing=True)
    assert restored.version_id == first.version_id
    unrelated_payload = payload("无关公告")
    unrelated_payload["snapshot"]["metadata"]["project_number"] = "TEST-OTHER"
    unrelated = save_import(database, ImportResult.model_validate(unrelated_payload["snapshot"]))
    assert unrelated.notice_id > second.notice_id
    assert list_versions(database, second.notice_id)["group_id"] == first.version_group_id


def test_legacy_projection_without_frozen_version_cannot_be_silently_replaced():
    from app.config import settings
    from app.storage import initialize

    database = settings.resolved_database_path
    initialize(database)
    with connect(database) as connection:
        connection.execute("INSERT INTO notices(id, project_name, source_files_json, warnings_json) VALUES (7, 'legacy', '[]', '[]')")
        connection.execute("INSERT INTO import_receipts VALUES ('legacy-job', 7)")
    with pytest.raises(ValueError, match="禁止覆盖"):
        save_import(database, ImportResult.model_validate(payload()["snapshot"]),
                    source_key="legacy-job", replace_existing=True)
    with connect(database) as connection:
        assert connection.execute("SELECT project_name FROM notices WHERE id=7").fetchone()[0] == "legacy"
        assert connection.execute("SELECT COUNT(*) FROM notice_versions").fetchone()[0] == 0
