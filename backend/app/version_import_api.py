"""Import supplied structured snapshots locally, without re-extraction or model calls."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.datasets import DatabasePath
from app.schemas import ImportResult
from app.storage import save_import

router = APIRouter(prefix="/api/v1/notice-version-imports", tags=["notice version import"])
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    official_notice_id: ShortText | None = None
    source_unique_id: ShortText | None = None
    namespace: ShortText = "local-import"


class SourceFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file: ShortText
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    byte_size: int = Field(ge=0, strict=True)


class SnapshotPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_code: ShortText
    package_name: ShortText | None = None
    package_budget: Decimal | None = None
    package_award_total: Decimal | None = None
    source_file: ShortText | None = None
    source_location: ShortText | None = None
    source_evidence: ShortText | None = None


class StructuredImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: ImportResult
    identity: Identity = Field(default_factory=Identity)
    sources: list[SourceFingerprint] = Field(min_length=1, max_length=2000)
    reason: ShortText = "user_supplied_structured_snapshot"
    # Plain extracted text is optional; HTML/file bytes are never persisted.
    body_texts: dict[ShortText, Annotated[str, StringConstraints(max_length=2_000_000)]] = Field(
        default_factory=dict,
    )
    packages: list[SnapshotPackage] | None = Field(default=None, max_length=2000)


@router.post("", response_model=ImportResult)
def import_snapshot(payload: StructuredImport, database_path: DatabasePath):
    sources = {source.source_file for source in payload.sources}
    referenced = set(payload.snapshot.source_files) | {
        row.source_file for row in [*payload.snapshot.items, *payload.snapshot.participants]
    } | {evidence["source_file"] for evidence in payload.snapshot.metadata_evidence.values()
         if evidence.get("source_file")} | set(payload.body_texts)
    referenced.update(evidence["source_file"] for row in payload.snapshot.items
                      for evidence in row.field_evidence.values() if evidence.get("source_file"))
    referenced.update(package.source_file for package in payload.packages or [] if package.source_file)
    if not referenced <= sources:
        raise HTTPException(status_code=422, detail="所有快照来源必须提供文件指纹")
    if payload.packages is not None:
        package_codes = [package.package_code for package in payload.packages]
        if len(package_codes) != len(set(package_codes)):
            raise HTTPException(status_code=422, detail="快照采购包号不能重复")
        if not {row.package_code for row in [*payload.snapshot.items, *payload.snapshot.participants]} <= set(package_codes):
            raise HTTPException(status_code=422, detail="候选采购包必须包含在快照采购包中")
    result = payload.snapshot.model_copy(update={"notice_id": 0})
    return save_import(
        database_path, result,
        source_hashes=[(source.source_file, source.sha256, source.byte_size)
                       for source in payload.sources],
        version_identity=payload.identity.model_dump(exclude_none=True),
        version_reason=payload.reason,
        source_texts=payload.body_texts,
        version_packages=[package.model_dump(mode="json") for package in payload.packages]
        if payload.packages is not None else None,
    )
