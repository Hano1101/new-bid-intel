"""Bounded, dataset-scoped SQLite endpoints for the relationship graph UI."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.datasets import DatabasePath
from app.storage import connect

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

RELATION_TYPES = ("PURCHASES", "HAS_PACKAGE", "BID_IN", "AWARDED_TO", "HAS_ITEM")
CATEGORY_LABELS = {
    "organization": "organization",
    "project": "project",
    "package": "package",
    "item": "item",
}
MAX_SEARCH_RESULTS = 20
MAX_SEARCH_OFFSET = 1_000_000
MAX_GRAPH_NODES = 100
MAX_GRAPH_EDGES = 200
MAX_PREVIEW_PROJECTS = 50
MAX_QUERY_LENGTH = 100

SearchType = Literal["all", "buyer", "supplier", "project"]
EntityType = Literal["organization", "project"]
RelationType = Literal["PURCHASES", "HAS_PACKAGE", "BID_IN", "AWARDED_TO", "HAS_ITEM"]

# Every fragment is static SQL. Only whitelisted relationship fragments are
# assembled, and all user-provided values are bound parameters.
_EDGE_SQL = {
    "PURCHASES": """
        SELECT 'organization' AS source_kind, o.id AS source_id,
               'project' AS target_kind, p.id AS target_id,
               'PURCHASES' AS relation, p.id AS edge_id, p.id AS project_id
        FROM projects p JOIN organizations o ON o.id = p.buyer_organization_id
        WHERE {where}
    """,
    "HAS_PACKAGE": """
        SELECT 'project' AS source_kind, p.id AS source_id,
               'package' AS target_kind, k.id AS target_id,
               'HAS_PACKAGE' AS relation, k.id AS edge_id, p.id AS project_id
        FROM packages k JOIN projects p ON p.id = k.project_id
        WHERE {where}
    """,
    "BID_IN": """
        SELECT 'organization' AS source_kind, o.id AS source_id,
               'package' AS target_kind, k.id AS target_id,
               'BID_IN' AS relation, b.id AS edge_id, k.project_id AS project_id
        FROM bid_participations b
        JOIN organizations o ON o.id = b.organization_id
        JOIN packages k ON k.id = b.package_id
        WHERE {where}
    """,
    "AWARDED_TO": """
        SELECT 'package' AS source_kind, k.id AS source_id,
               'organization' AS target_kind, o.id AS target_id,
               'AWARDED_TO' AS relation, a.id AS edge_id, k.project_id AS project_id
        FROM awards a JOIN packages k ON k.id = a.package_id
        JOIN organizations o ON o.id = a.organization_id
        WHERE {where}
    """,
    "HAS_ITEM": """
        SELECT 'package' AS source_kind, k.id AS source_id,
               'item' AS target_kind, i.id AS target_id,
               'HAS_ITEM' AS relation, i.id AS edge_id, k.project_id AS project_id
        FROM procurement_items i JOIN packages k ON k.id = i.package_id
        WHERE {where}
    """,
}


def _search_query(search_type: SearchType, query: str) -> tuple[str, list[Any]]:
    sql = """
        WITH candidates AS (
            SELECT 'organization' AS entity_type, o.id AS entity_id,
                   o.canonical_name AS name, NULL AS project_number,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM projects p WHERE p.buyer_organization_id = o.id
                   ) THEN 1 ELSE 0 END AS is_buyer,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM bid_participations b WHERE b.organization_id = o.id
                       UNION ALL
                       SELECT 1 FROM awards a WHERE a.organization_id = o.id
                   ) THEN 1 ELSE 0 END AS is_supplier
            FROM organizations o
            WHERE instr(lower(o.canonical_name), lower(?)) > 0
            UNION ALL
            SELECT 'project' AS entity_type, p.id AS entity_id,
                   COALESCE(NULLIF(p.project_name, ''), NULLIF(p.project_number, ''),
                            '项目 ' || p.id) AS name,
                   p.project_number AS project_number,
                   CASE WHEN p.buyer_organization_id IS NULL THEN 0 ELSE 1 END AS is_buyer,
                   0 AS is_supplier
            FROM projects p
            WHERE instr(lower(COALESCE(p.project_name, '')), lower(?)) > 0
               OR instr(lower(COALESCE(p.project_number, '')), lower(?)) > 0
        )
        SELECT entity_type, entity_id, name, project_number, is_buyer, is_supplier
        FROM candidates
        WHERE (entity_type = 'organization' AND
              ((? = 'all' AND (is_buyer = 1 OR is_supplier = 1)) OR
               (? = 'buyer' AND is_buyer = 1) OR
               (? = 'supplier' AND is_supplier = 1)))
           OR (entity_type = 'project' AND ? IN ('all', 'project'))
        ORDER BY name COLLATE NOCASE, entity_type, entity_id
    """
    return sql, [query, query, query, search_type, search_type, search_type, search_type]


def _node_uid(kind: str, entity_id: int) -> str:
    return f"{kind}:{entity_id}"


def _name(kind: str, row: dict[str, Any]) -> str:
    if kind == "organization":
        return row["canonical_name"]
    if kind == "project":
        return row.get("project_name") or row.get("project_number") or f"项目 {row['id']}"
    if kind == "package":
        return row.get("package_name") or row.get("package_code") or f"包 {row['id']}"
    return row.get("product_name") or f"标的 {row['id']}"


def _node(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    properties = {key: value for key, value in row.items() if value is not None}
    properties["name"] = _name(kind, row)
    return {
        "id": _node_uid(kind, row["id"]),
        "name": properties["name"],
        "category": CATEGORY_LABELS[kind],
        "properties": properties,
    }


def _edge_conditions(
    mode: Literal["preview", "organization", "project"],
    anchor_id: int | None,
    project_ids: list[int],
) -> dict[str, tuple[str, list[Any]]]:
    if mode == "preview":
        if not project_ids:
            return {}
        placeholders = ",".join("?" for _ in project_ids)
        return {
            "PURCHASES": (f"p.id IN ({placeholders})", project_ids),
            "HAS_PACKAGE": (f"p.id IN ({placeholders})", project_ids),
            "BID_IN": (f"k.project_id IN ({placeholders})", project_ids),
            "AWARDED_TO": (f"k.project_id IN ({placeholders})", project_ids),
            "HAS_ITEM": (f"k.project_id IN ({placeholders})", project_ids),
        }
    if mode == "organization":
        return {
            "PURCHASES": ("o.id = ?", [anchor_id]),
            "BID_IN": ("b.organization_id = ?", [anchor_id]),
            "AWARDED_TO": ("a.organization_id = ?", [anchor_id]),
        }
    return {
        "PURCHASES": ("p.id = ?", [anchor_id]),
        "HAS_PACKAGE": ("p.id = ?", [anchor_id]),
    }


def _edge_rows(
    db: Any,
    *,
    mode: Literal["preview", "organization", "project"],
    anchor_id: int | None,
    project_ids: list[int],
    relation_type: RelationType | None,
    edge_limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    conditions = _edge_conditions(mode, anchor_id, project_ids)
    if relation_type is not None:
        conditions = {key: value for key, value in conditions.items() if key == relation_type}
    if not conditions:
        return [], False
    fragments = []
    parameters: list[Any] = []
    for kind, (where, values) in conditions.items():
        fragments.append(_EDGE_SQL[kind].format(where=where))
        parameters.extend(values)
    statement = (
        "WITH candidates AS (" + " UNION ALL ".join(fragments) + ") "
        "SELECT source_kind,source_id,target_kind,target_id,relation,edge_id "
        "FROM candidates ORDER BY project_id DESC, relation, edge_id LIMIT ?"
    )
    rows = [dict(row) for row in db.execute(statement, [*parameters, edge_limit + 1])]
    return rows[:edge_limit], len(rows) > edge_limit


def _load_nodes(
    db: Any,
    edges: list[dict[str, Any]],
    seed_project_rows: list[dict[str, Any]],
    anchor: tuple[str, int] | None,
    node_limit: int,
) -> tuple[list[dict[str, Any]], set[str], bool]:
    kinds_by_id: dict[str, set[int]] = defaultdict(set)
    for edge in edges:
        kinds_by_id[edge["source_kind"]].add(edge["source_id"])
        kinds_by_id[edge["target_kind"]].add(edge["target_id"])
    if anchor is not None:
        kinds_by_id[anchor[0]].add(anchor[1])
    if seed_project_rows:
        kinds_by_id["project"].update(row["id"] for row in seed_project_rows)

    table_by_kind = {
        "organization": "organizations",
        "project": "projects",
        "package": "packages",
        "item": "procurement_items",
    }
    rows_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for kind, ids in kinds_by_id.items():
        if not ids:
            continue
        ids_ordered = sorted(ids)
        placeholders = ",".join("?" for _ in ids_ordered)
        rows = db.execute(
            f"SELECT * FROM {table_by_kind[kind]} WHERE id IN ({placeholders})",
            ids_ordered,
        )
        rows_by_key.update({(kind, row["id"]): dict(row) for row in rows})

    ordered_keys: list[tuple[str, int]] = []
    if anchor is not None:
        ordered_keys.append(anchor)
    ordered_keys.extend(("project", row["id"]) for row in seed_project_rows)
    for edge in edges:
        ordered_keys.extend(
            ((edge["source_kind"], edge["source_id"]), (edge["target_kind"], edge["target_id"]))
        )
    ordered_keys = list(dict.fromkeys(key for key in ordered_keys if key in rows_by_key))
    selected = ordered_keys[:node_limit]
    selected_keys = set(selected)
    return (
        [_node(kind, rows_by_key[(kind, entity_id)]) for kind, entity_id in selected],
        selected_keys,
        len(ordered_keys) > len(selected),
    )


def _graph_payload(
    db: Any,
    *,
    path: Path,
    mode: Literal["preview", "organization", "project"],
    relation_type: RelationType | None,
    node_limit: int,
    edge_limit: int,
    anchor: tuple[str, int] | None = None,
    project_rows: list[dict[str, Any]] | None = None,
    project_count_truncated: bool = False,
) -> dict[str, Any]:
    project_rows = project_rows or []
    project_ids = [row["id"] for row in project_rows]
    total_projects = int(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
    edge_candidates, edge_truncated = _edge_rows(
        db,
        mode=mode,
        anchor_id=anchor[1] if anchor else None,
        project_ids=project_ids,
        relation_type=relation_type,
        edge_limit=edge_limit,
    )
    nodes, selected_keys, node_truncated = _load_nodes(
        db,
        edge_candidates,
        project_rows if mode == "preview" else [],
        anchor,
        node_limit,
    )
    kept_edges = [
        row
        for row in edge_candidates
        if (row["source_kind"], row["source_id"]) in selected_keys
        and (row["target_kind"], row["target_id"]) in selected_keys
    ]
    if len(kept_edges) < len(edge_candidates):
        node_truncated = True

    property_table = {"BID_IN": "bid_participations", "AWARDED_TO": "awards"}
    property_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for relation, table in property_table.items():
        ids = sorted({row["edge_id"] for row in kept_edges if row["relation"] == relation})
        if not ids:
            continue
        placeholders = ",".join("?" for _ in ids)
        property_rows.update(
            {
                (relation, row["id"]): {
                    key: value for key, value in dict(row).items() if value is not None
                }
                for row in db.execute(f"SELECT * FROM {table} WHERE id IN ({placeholders})", ids)
            }
        )
    links = [
        {
            "id": f"{_node_uid(row['source_kind'], row['source_id'])}:{row['relation']}:{_node_uid(row['target_kind'], row['target_id'])}",
            "source": _node_uid(row["source_kind"], row["source_id"]),
            "target": _node_uid(row["target_kind"], row["target_id"]),
            "relation": row["relation"],
            "properties": property_rows.get((row["relation"], row["edge_id"]), {}),
        }
        for row in kept_edges
    ]
    project_count = sum(1 for node in nodes if node["category"] == "project")
    truncated = edge_truncated or node_truncated or project_count_truncated
    hints = []
    if edge_truncated:
        hints.append(f"关系达到 {edge_limit} 条上限")
    if node_truncated:
        hints.append(f"节点达到 {node_limit} 个上限")
    if project_count_truncated:
        hints.append(f"最近项目预览最多取 {MAX_PREVIEW_PROJECTS} 个项目")
    return {
        "backend": "sqlite",
        "dataset": path.name,
        "nodes": nodes,
        "links": links,
        "categories": list(CATEGORY_LABELS.values()),
        "project_count": project_count,
        "total_project_count": total_projects,
        "node_count": len(nodes),
        "edge_count": len(links),
        "truncated": truncated,
        "truncation_hint": "；".join(hints) if hints else None,
        "limits": {"nodes": node_limit, "edges": edge_limit},
        "view": "preview" if mode == "preview" else "entity",
        "entity": ({"type": anchor[0], "id": anchor[1]} if anchor else None),
        "hop_count": 1 if anchor else 0,
    }


def _search(
    path: Path, query: str, search_type: SearchType, limit: int, offset: int,
) -> dict[str, Any]:
    normalized = query.strip()
    if (
        not normalized
        or len(normalized) > MAX_QUERY_LENGTH
        or any(ord(char) < 32 for char in normalized)
    ):
        raise HTTPException(status_code=422, detail="搜索词须为 1 至 100 个可见字符")
    statement, parameters = _search_query(search_type, normalized)
    with connect(path) as db:
        db.execute("BEGIN")
        total = int(db.execute(f"SELECT COUNT(*) FROM ({statement})", parameters).fetchone()[0])
        rows = [dict(row) for row in db.execute(
            f"{statement} LIMIT ? OFFSET ?", [*parameters, limit + 1, offset],
        )]
    page = rows[:limit]
    has_more = total > offset + len(page)
    results = []
    for row in page:
        result = {
            "id": _node_uid(row["entity_type"], row["entity_id"]),
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "category": CATEGORY_LABELS[row["entity_type"]],
            "name": row["name"],
            "context": (f"项目编号：{row['project_number']}" if row["project_number"] else None),
        }
        if row["entity_type"] == "organization":
            result["roles"] = [
                role
                for role, present in (
                    ("buyer", row["is_buyer"]),
                    ("supplier", row["is_supplier"]),
                )
                if present
            ]
        results.append(result)
    return {
        "view": "search",
        "query": normalized,
        "search_type": search_type,
        "results": results,
        "result_count": len(results),
        "total_result_count": total,
        "offset": offset,
        "next_offset": offset + len(results) if has_more else None,
        "has_more": has_more,
        "truncated": has_more,
        "truncation_hint": f"匹配结果超过 {limit} 条，仅显示前 {limit} 条" if has_more else None,
        "limits": {"results": limit},
    }


@router.get("")
def get_graph(
    database_path: DatabasePath,
    limit: int = Query(default=50, ge=1, le=200),
    query: str | None = Query(default=None, min_length=1, max_length=MAX_QUERY_LENGTH),
    search_type: SearchType = Query(default="all", alias="type"),  # noqa: B008
    entity_type: EntityType | None = None,
    entity_id: int | None = Query(default=None, ge=1),
    hop: int = Query(default=1, ge=1, le=1),
    relation_type: RelationType | None = None,
    search_limit: int = Query(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS),
    search_offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    node_limit: int = Query(default=MAX_GRAPH_NODES, ge=1, le=MAX_GRAPH_NODES),
    edge_limit: int = Query(default=MAX_GRAPH_EDGES, ge=1, le=MAX_GRAPH_EDGES),
) -> dict[str, Any]:
    """Search the selected SQLite dataset or return a bounded graph snapshot."""
    if query is not None:
        if entity_id is not None or entity_type is not None:
            raise HTTPException(status_code=422, detail="搜索与实体关系图参数不能同时使用")
        return _search(database_path, query, search_type, search_limit, search_offset)
    if (entity_id is None) != (entity_type is None):
        raise HTTPException(status_code=422, detail="entity_type 与 entity_id 必须同时提供")

    with connect(database_path) as db:
        db.execute("BEGIN")
        if entity_id is not None and entity_type is not None:
            table = "organizations" if entity_type == "organization" else "projects"
            row = db.execute(f"SELECT id FROM {table} WHERE id = ?", (entity_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="所选主体或项目不存在")
            return _graph_payload(
                db,
                path=database_path,
                mode=entity_type,
                anchor=(entity_type, entity_id),
                relation_type=relation_type,
                node_limit=node_limit,
                edge_limit=edge_limit,
            )

        total = int(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
        selected_limit = min(limit, MAX_PREVIEW_PROJECTS)
        project_rows = [
            dict(row)
            for row in db.execute(
                "SELECT id FROM projects ORDER BY id DESC LIMIT ?", (selected_limit,)
            )
        ]
        payload = _graph_payload(
            db,
            path=database_path,
            mode="preview",
            project_rows=project_rows,
            relation_type=relation_type,
            node_limit=node_limit,
            edge_limit=edge_limit,
            project_count_truncated=(limit > MAX_PREVIEW_PROJECTS or total > len(project_rows)),
        )
        return payload
