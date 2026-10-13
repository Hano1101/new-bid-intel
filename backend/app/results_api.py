"""Export task-three processing results in the official three-sheet workbook format."""
from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.datasets import DatabasePath
from app.result_workbook import build_result_workbook
from app.storage import connect

router = APIRouter(prefix="/api/v1/notices", tags=["result exports"])


class ResultExportRequest(BaseModel):
    notice_ids: list[int] = Field(min_length=1, max_length=10000)


@router.post("/export-results")
def export_notice_results(payload: ResultExportRequest, database: DatabasePath):
    notice_ids = list(dict.fromkeys(payload.notice_ids))
    with connect(database) as connection:
        placeholders = ",".join("?" for _ in notice_ids)
        rows = connection.execute(
            f"SELECT id FROM notices WHERE id IN ({placeholders})", notice_ids
        ).fetchall()
        found = {row["id"] for row in rows}
        missing = [notice_id for notice_id in notice_ids if notice_id not in found]
        if missing:
            raise HTTPException(status_code=404, detail=f"公告不存在或不属于当前数据集：{missing[:20]}")
        workbook = build_result_workbook(connection, notice_ids)
    return StreamingResponse(
        BytesIO(workbook),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="task3-results.xlsx"'},
    )
