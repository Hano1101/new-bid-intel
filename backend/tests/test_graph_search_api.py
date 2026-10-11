from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.storage import connect, initialize


def _organization(db, name: str, key: str | None = None) -> int:
    normalized = key or name.casefold()
    return db.execute(
        "INSERT INTO organizations(canonical_name,normalized_name) VALUES (?,?)",
        (name, normalized),
    ).lastrowid


def _project(db, name: str, buyer_id: int | None = None, number: str | None = None) -> int:
    notice_id = db.execute(
        "INSERT INTO notices(project_name,source_files_json,warnings_json) VALUES (?, '[]', '[]')",
        (name,),
    ).lastrowid
    return db.execute(
        "INSERT INTO projects(notice_id,project_name,project_number,buyer_organization_id) "
        "VALUES (?,?,?,?)",
        (notice_id, name, number, buyer_id),
    ).lastrowid


def _client():
    return TestClient(app)


def test_search_reaches_older_full_dataset_rows_and_returns_direct_hop_only():
    path = settings.resolved_database_path
    initialize(path)
    with _client() as client, connect(path) as db:
        buyer = _organization(db, "全量检索采购单位")
        supplier = _organization(db, "全量检索供应商")
        old_project = _project(db, "全量检索旧项目", buyer, "OLD-001")
        package = db.execute(
            "INSERT INTO packages(project_id,package_code) VALUES (?, 'A')", (old_project,)
        ).lastrowid
        db.execute(
            "INSERT INTO bid_participations(package_id,organization_id,raw_name,outcome) "
            "VALUES (?,?,?,'winner')",
            (package, supplier, "全量检索供应商"),
        )
        recent = _project(db, "最近项目")
        db.commit()

        preview = client.get("/api/v1/graph", params={"limit": 1}).json()
        assert f"project:{old_project}" not in {node["id"] for node in preview["nodes"]}

        search = client.get("/api/v1/graph", params={"query": "全量检索", "type": "buyer"})
        assert search.status_code == 200
        assert search.json()["total_result_count"] == 1
        assert search.json()["results"][0]["id"] == f"organization:{buyer}"
        assert search.json()["results"][0]["roles"] == ["buyer"]

        graph = client.get(
            "/api/v1/graph",
            params={
                "entity_type": "organization",
                "entity_id": buyer,
            },
        ).json()
        assert graph["view"] == "entity" and graph["hop_count"] == 1
        assert {node["id"] for node in graph["nodes"]} == {
            f"organization:{buyer}",
            f"project:{old_project}",
        }
        assert [edge["relation"] for edge in graph["links"]] == ["PURCHASES"]
        assert f"project:{recent}" not in {node["id"] for node in graph["nodes"]}


def test_relation_filter_is_applied_in_sql_and_supplier_edges_are_direct():
    path = settings.resolved_database_path
    initialize(path)
    with _client() as client, connect(path) as db:
        buyer = _organization(db, "筛选采购方")
        supplier = _organization(db, "筛选供应方")
        project = _project(db, "筛选项目", buyer)
        package = db.execute(
            "INSERT INTO packages(project_id,package_code) VALUES (?, 'A')", (project,)
        ).lastrowid
        db.execute(
            "INSERT INTO bid_participations(package_id,organization_id,raw_name,outcome) "
            "VALUES (?,?,?,'winner')",
            (package, supplier, "筛选供应方"),
        )
        db.execute(
            "INSERT INTO awards(package_id,organization_id,raw_name,award_amount) VALUES (?,?,?,'10')",
            (package, supplier, "筛选供应方"),
        )
        db.commit()

        result = client.get(
            "/api/v1/graph",
            params={
                "entity_type": "organization",
                "entity_id": supplier,
                "relation_type": "BID_IN",
            },
        )
        assert result.status_code == 200
        graph = result.json()
        assert [edge["relation"] for edge in graph["links"]] == ["BID_IN"]
        assert {node["id"] for node in graph["nodes"]} == {
            f"organization:{supplier}",
            f"package:{package}",
        }
        assert graph["edge_count"] == 1


def test_same_name_projects_remain_distinct_and_empty_search_is_clean():
    path = settings.resolved_database_path
    initialize(path)
    with _client() as client, connect(path) as db:
        first_buyer = _organization(db, "同名采购主体", "same-buyer-one")
        second_buyer = _organization(db, "同名采购主体", "same-buyer-two")
        _project(db, "同名主体甲的项目", first_buyer)
        _project(db, "同名主体乙的项目", second_buyer)
        first = _project(db, "同名项目")
        second = _project(db, "同名项目")
        db.commit()

        buyer_results = client.get(
            "/api/v1/graph",
            params={
                "query": "同名采购主体",
                "type": "buyer",
            },
        ).json()
        assert {row["id"] for row in buyer_results["results"]} == {
            f"organization:{first_buyer}",
            f"organization:{second_buyer}",
        }

        response = client.get("/api/v1/graph", params={"query": "同名项目", "type": "project"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_result_count"] == 2
        assert {row["id"] for row in payload["results"]} == {
            f"project:{first}",
            f"project:{second}",
        }

        empty = client.get("/api/v1/graph", params={"query": "完全不存在", "type": "all"})
        assert empty.status_code == 200
        assert empty.json()["results"] == []
        assert empty.json()["result_count"] == 0
        assert empty.json()["total_result_count"] == 0
        assert empty.json()["truncated"] is False

        quoted = client.get("/api/v1/graph", params={"query": "' OR 1=1 --", "type": "all"})
        assert quoted.status_code == 200
        assert quoted.json()["results"] == []


def test_search_and_graph_results_are_bounded_with_truncation_metadata():
    path = settings.resolved_database_path
    initialize(path)
    with _client() as client, connect(path) as db:
        supplier = _organization(db, "高连接度供应商")
        project = _project(db, "大量关系项目")
        qualification_package = db.execute(
            "INSERT INTO packages(project_id,package_code) VALUES (?, 'QUALIFY')", (project,)
        ).lastrowid
        for index in range(25):
            result_supplier = _organization(db, f"结果上限供应商{index:02d}", f"result-{index}")
            db.execute(
                "INSERT INTO bid_participations(package_id,organization_id,raw_name) VALUES (?,?,?)",
                (qualification_package, result_supplier, f"结果上限供应商{index:02d}"),
            )
        for index in range(205):
            package = db.execute(
                "INSERT INTO packages(project_id,package_code) VALUES (?,?)",
                (project, f"P{index}"),
            ).lastrowid
            db.execute(
                "INSERT INTO bid_participations(package_id,organization_id,raw_name) VALUES (?,?,?)",
                (package, supplier, "高连接度供应商"),
            )
        db.commit()

        matches = client.get(
            "/api/v1/graph",
            params={
                "query": "结果上限供应商",
                "type": "supplier",
            },
        ).json()
        assert matches["result_count"] == 20
        assert matches["total_result_count"] == 25
        assert matches["offset"] == 0
        assert matches["next_offset"] == 20
        assert matches["has_more"] is True
        assert matches["truncated"] is True
        assert matches["truncation_hint"]

        second_page = client.get(
            "/api/v1/graph",
            params={
                "query": "结果上限供应商",
                "type": "supplier",
                "search_offset": matches["next_offset"],
            },
        ).json()
        assert second_page["offset"] == 20
        assert second_page["result_count"] == 5
        assert second_page["total_result_count"] == 25
        assert second_page["next_offset"] is None
        assert second_page["has_more"] is False
        assert second_page["truncated"] is False
        assert {row["id"] for row in matches["results"]}.isdisjoint(
            row["id"] for row in second_page["results"]
        )

        graph = client.get(
            "/api/v1/graph",
            params={
                "entity_type": "organization",
                "entity_id": supplier,
                "node_limit": 30,
                "edge_limit": 40,
            },
        ).json()
        assert graph["node_count"] <= 30
        assert graph["edge_count"] <= 40
        assert graph["edge_count"] == 29
        assert graph["truncated"] is True
        assert "节点达到 30 个上限" in graph["truncation_hint"]

        capped_by_edges = client.get(
            "/api/v1/graph",
            params={
                "entity_type": "organization",
                "entity_id": supplier,
                "node_limit": 100,
                "edge_limit": 40,
            },
        ).json()
        assert capped_by_edges["edge_count"] == 40
        assert "关系达到 40 条上限" in capped_by_edges["truncation_hint"]


def test_dataset_header_keeps_graph_search_and_drill_isolated():
    path = settings.resolved_database_path
    initialize(path)
    with _client() as client:
        default_id = _organization_in_database(path, "隔离采购单位")
        created = client.post("/api/v1/datasets", json={"name": "graph isolation"})
        assert created.status_code == 201
        dataset_id = created.json()["id"]
        dataset_path = settings.resolved_database_path.parent / "datasets" / f"{dataset_id}.sqlite"
        scoped_id = _organization_in_database(dataset_path, "隔离采购单位")
        headers = {"X-Dataset-ID": dataset_id}

        default = client.get("/api/v1/graph", params={"query": "隔离采购单位", "type": "buyer"})
        scoped = client.get(
            "/api/v1/graph",
            params={
                "query": "隔离采购单位",
                "type": "buyer",
            },
            headers=headers,
        )
        assert default.json()["results"][0]["id"] == f"organization:{default_id}"
        assert scoped.json()["results"][0]["id"] == f"organization:{scoped_id}"

        other_dataset = "f" * 32
        assert (
            client.get("/api/v1/graph", headers={"X-Dataset-ID": other_dataset}).status_code == 404
        )
        assert client.get("/api/v1/graph", headers={"X-Dataset-ID": "../escape"}).status_code == 422


def _organization_in_database(path: Path, name: str) -> int:
    initialize(path)
    with connect(path) as db:
        org_id = _organization(db, name)
        _project(db, f"{name} 项目", org_id)
    return org_id


@pytest.mark.parametrize(
    "params",
    [
        {"query": "   "},
        {"query": "name", "type": "unknown"},
        {"query": "name", "type": "buyer' OR 1=1 --"},
        {"entity_type": "organization"},
        {"entity_type": "organization", "entity_id": "not-an-id"},
        {"entity_type": "organization", "entity_id": 1, "hop": 2},
        {"entity_type": "organization", "entity_id": 1, "relation_type": "MATCH (n)"},
        {"entity_type": "project", "entity_id": 1, "node_limit": 101},
        {"entity_type": "project", "entity_id": 1, "edge_limit": 201},
        {"query": "name", "search_limit": 21},
        {"query": "name", "search_offset": 1_000_001},
    ],
)
def test_invalid_graph_inputs_are_rejected(params):
    with _client() as client:
        response = client.get("/api/v1/graph", params=params)
    assert response.status_code == 422
