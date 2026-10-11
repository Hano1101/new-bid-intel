"""Dataset-scoped, read-only version history and frozen evidence endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.datasets import DatabasePath
from app.notice_version_diff import compare_snapshots
from app.notice_versions import get_version, list_versions, version_evidence

router = APIRouter(prefix="/api/v1/notice-versions", tags=["notice versions"])
VersionID = Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")]


def _version(database_path, version_id):
    if len(version_id) != 32 or any(char not in "0123456789abcdef" for char in version_id):
        raise HTTPException(status_code=422, detail="版本 ID 格式无效")
    version = get_version(database_path, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="当前数据集内不存在该版本")
    return version


@router.get("/notices/{notice_id}")
def history(database_path: DatabasePath, notice_id: int):
    if notice_id <= 0:
        raise HTTPException(status_code=422, detail="公告 ID 必须为正整数")
    return list_versions(database_path, notice_id)


@router.get("/notices/{notice_id}/latest")
def latest(database_path: DatabasePath, notice_id: int):
    result = history(database_path, notice_id)
    if not result["latest_version_id"]:
        raise HTTPException(status_code=404, detail="尚未保存版本；历史数据不会自动补造快照")
    return _version(database_path, result["latest_version_id"])


@router.get("/versions/{version_id}")
def detail(database_path: DatabasePath, version_id: str):
    return _version(database_path, version_id)


@router.get("/versions/{version_id}/evidence")
def evidence(database_path: DatabasePath, version_id: str):
    return version_evidence(_version(database_path, version_id))


def _compare(database_path, before_version_id, after_version_id, include_unchanged=False):
    before = _version(database_path, before_version_id)
    after = _version(database_path, after_version_id)
    try:
        return compare_snapshots(before, after, include_unchanged=include_unchanged)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/compare")
def compare(database_path: DatabasePath, before_version_id: VersionID,
            after_version_id: VersionID, include_unchanged: bool = False):
    return _compare(database_path, before_version_id, after_version_id, include_unchanged)


@router.get("/summary")
def summary(database_path: DatabasePath, before_version_id: VersionID,
            after_version_id: VersionID):
    result = _compare(database_path, before_version_id, after_version_id)
    return {"before_version_id": before_version_id, "after_version_id": after_version_id,
            "summary": result["summary"]}
