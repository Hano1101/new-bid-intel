"""Build Excel result tables matching the competition's three-sheet template."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO
from math import ceil
from pathlib import PurePosixPath
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.bidder_result_details import (
    merge_bidder_details,
    normalize_bidder_name,
)

SHEETS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "总表",
        ("序号", "URL", "UUID", "标段/合同包", "项目名称", "采购单位", "中标供应商", "中标金额"),
        (
            "该字段无实际含义，仅用于区分填写说明和填写示例",
            "选填字段，当前通知明确不作为标准字段要求",
            "公告唯一标识：与源文件（HTML/附件）前缀一致，由任务给定，不得自行编造。",
            '公告划分的标段/合同包名称；未分包的填写"未分包"，多标段逐行列出。',
            "采购项目全称，保留公告原文，不得缩写。",
            "采购人（招标人）全称。",
            "中标（成交）供应商全称。",
            "中标金额：统一金额单位为（万元），保留两位小数，四舍五入。",
        ),
    ),
    (
        "标的表",
        ("序号", "UUID", "标段/合同包", "产品服务名称", "品目", "品牌", "规格型号", "数量", "单价", "总价", "类别"),
        (
            "该字段无实际含义，仅用于区分填写说明和填写示例",
            "公告唯一标识：与源文件（HTML/附件）前缀一致，由任务给定，不得自行编造。",
            '公告划分的标段/合同包名称；未分包的填写"未分包"，多标段逐行列出。',
            '标的物名称，保留原文（含"核心产品"等标注）；一条标的一行。',
            "按政府采购品目分类目录划分的采购项目类别，原文未给出则留空。",
            "品牌名，原文未给出则留空。",
            "规格/型号，原文未给出则留空。",
            "数量：正整数，照录原文。原文未给出则留空。",
            "单价：单位(万元)。原文未给出则留空。",
            "总价：单价×数量，或按原文填写，单位（万元）。原文未给出则留空。",
            '记录的类别，属于结果公示提取的，记为需求，属于招标类提取的，记为中标。',
        ),
    ),
    (
        "投标人表",
        ("序号", "UUID", "标段/合同包", "名称", "类别", "通过审查", "报价（万元）", "得分", "未中标原因"),
        (
            "该字段无实际含义，仅用于区分填写说明和填写示例",
            "公告唯一标识：与源文件（HTML/附件）前缀一致，由任务给定，不得自行编造。",
            '公告划分的标段/合同包名称；未分包的填写"未分包"，多标段逐行列出。',
            "参与投标/响应的供应商全称。",
            '中标人 / 参与人（中标公示中的中标方填"中标人"，其余填"参与人"，未通过审查的填写"其他"）。',
            "资格审查/符合性审查结果：通过 / 未通过，未通过需注明原因。",
            "投标报价，统一单位为（万元），保留两位小数点。原文未披露则留空。",
            "综合得分，保留两位小数，原文未披露则留空。",
            "建议仅非中标人填写：照录原文，原文无则留空。",
        ),
    ),
)

_UUID_RE = re.compile(r"(?<![A-Za-z0-9])(t\d{8}_\d+)(?!\d)", re.IGNORECASE)
_BLUE = PatternFill("solid", fgColor="FF1F4E79")
_GRAY = PatternFill("solid", fgColor="FFD9D9D9")
_LIGHT = PatternFill("solid", fgColor="FFF2F2F2")
_THIN_GRAY = Side(style="thin", color="D9E0E8")
_CURRENCY_FORMAT = "0.00"
_COLUMN_WIDTHS = {
    "总表": (12, 36, 28, 24, 56, 38, 48, 18),
    "标的表": (12, 28, 24, 44, 28, 24, 36, 14, 18, 18, 18),
    "投标人表": (12, 28, 24, 48, 18, 30, 22, 18, 36),
}


def _wrapped_lines(value: Any, column_width: float) -> int:
    text = "" if value is None else str(value)
    available = max(1, column_width - 2)
    return sum(
        max(1, ceil(sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
                        for char in line) / available))
        for line in text.split("\n")
    )


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _yuan_to_wanyuan(value: Any) -> float | None:
    amount = _number(value)
    if amount is None:
        return None
    return float((amount / Decimal(10000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _quantity(value: Any) -> Any:
    amount = _number(value)
    if amount is None:
        return _as_text(value) or None
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _score(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return float(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _bidder_details(connection: sqlite3.Connection, notice_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    # Older datasets remain exportable before their additive migration runs.
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bidder_result_details'"
    ).fetchone():
        return {}
    placeholders = ",".join("?" for _ in notice_ids)
    raw_rows = connection.execute(
        f"SELECT * FROM bidder_result_details WHERE notice_id IN ({placeholders}) ORDER BY id",
        notice_ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for raw_row in raw_rows:
        record = dict(raw_row)
        try:
            record["field_evidence"] = json.loads(record.pop("field_evidence_json", "{}"))
        except (TypeError, json.JSONDecodeError):
            record["field_evidence"] = {}
        grouped.setdefault(record["notice_id"], []).append(record)
    return {notice_id: merge_bidder_details(records) for notice_id, records in grouped.items()}


def _bidder_cells(detail: dict[str, Any] | None, *, winner: bool) -> tuple[Any, ...]:
    detail = detail or {}
    review = _as_text(detail.get("review_status"))
    reason = _as_text(detail.get("unsuccessful_reason"))
    if not review and re.search(r"(?:资格|符合性).*(?:不通过|未通过|不合格|不符合)", reason):
        review = "未通过"
    category = "其他" if review == "未通过" else ("中标人" if winner else "参与人")
    return (
        category, review, _yuan_to_wanyuan(detail.get("bid_amount")),
        _score(detail.get("evaluation_score")), "" if winner else reason,
    )


def _notice_uuid(source_files_json: str | None) -> str:
    """Use only a source-provided official filename prefix; never use the DB row id."""
    try:
        source_files = json.loads(source_files_json or "[]")
    except (TypeError, json.JSONDecodeError):
        source_files = []
    for source in source_files if isinstance(source_files, list) else []:
        if not isinstance(source, str):
            continue
        # Archive member paths contain !/; the official top-level source is preferred.
        candidates = [source.split("!/", 1)[0], source]
        for candidate in candidates:
            match = _UUID_RE.search(PurePosixPath(candidate.replace("\\", "/")).name)
            if match:
                return match.group(1)
    return ""


def _package_label(package_code: Any, package_name: Any) -> str:
    name = _as_text(package_name)
    if name:
        return name
    code = _as_text(package_code)
    # `default` is an internal fallback, not evidence that the notice was unbundled.
    return "" if not code or code.casefold() == "default" else code


def _selected_ids(connection: sqlite3.Connection, notice_ids: list[int] | None) -> list[int]:
    if notice_ids is None:
        return [row[0] for row in connection.execute("SELECT id FROM notices ORDER BY id")]
    return list(dict.fromkeys(int(value) for value in notice_ids))


def build_result_workbook(connection: sqlite3.Connection, notice_ids: list[int] | None = None) -> bytes:
    """Return an XLSX with total, item and bidder rows for the selected notices."""
    ids = _selected_ids(connection, notice_ids)
    workbook = Workbook()
    workbook.remove(workbook.active)
    worksheets = {}

    for sheet_name, headers, descriptions in SHEETS:
        sheet = workbook.create_sheet(sheet_name)
        worksheets[sheet_name] = sheet
        sheet.append(headers)
        sheet.append(descriptions)
        sheet.freeze_panes = "A3"
        sheet.sheet_view.showGridLines = False
        sheet.row_dimensions[1].height = 28
        for column, header in enumerate(headers, start=1):
            cell = sheet.cell(1, column)
            optional = (
                (sheet_name == "总表" and header == "URL")
                or header in {"序号", "得分", "未中标原因"}
                or (sheet_name == "标的表" and header == "类别")
            )
            cell.fill = _GRAY if optional else _BLUE
            cell.font = Font(name="微软雅黑", size=10, bold=True,
                             color="404040" if optional else "FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            note = sheet.cell(2, column)
            note.fill = _LIGHT
            note.font = Font(name="微软雅黑", size=9, color="404040")
            note.alignment = Alignment(vertical="top", wrap_text=True)
            sheet.column_dimensions[get_column_letter(column)].width = _COLUMN_WIDTHS[sheet_name][column - 1]
        sheet.row_dimensions[2].height = max(
            _wrapped_lines(note, width) * 14 + 6
            for note, width in zip(descriptions, _COLUMN_WIDTHS[sheet_name], strict=True)
        )

    if ids:
        placeholders = ",".join("?" for _ in ids)
        id_order = {notice_id: index for index, notice_id in enumerate(ids)}
        notices = connection.execute(
            f"""SELECT n.id, n.project_name, n.procurement_unit, n.source_files_json,
                       pr.id AS project_id, pr.announced_total_award
                FROM notices n LEFT JOIN projects pr ON pr.notice_id=n.id
                WHERE n.id IN ({placeholders})""",
            ids,
        ).fetchall()
        notices.sort(key=lambda row: id_order[row["id"]])
        found_ids = {row["id"] for row in notices}
        notice_context = {
            row["id"]: {
                "uuid": _notice_uuid(row["source_files_json"]),
                "project_name": _as_text(row["project_name"]),
                "buyer": _as_text(row["procurement_unit"]),
                "project_id": row["project_id"],
                "announced_total_award": row["announced_total_award"],
            }
            for row in notices
        }

        if found_ids:
            ordered_ids = [notice_id for notice_id in ids if notice_id in found_ids]
            placeholders = ",".join("?" for _ in ordered_ids)
            package_rows = connection.execute(
                f"""SELECT pr.notice_id, pk.id AS package_id, pk.package_code, pk.package_name,
                           pk.package_award_total, a.id AS award_id, a.raw_name AS awardee,
                           a.award_amount
                    FROM projects pr JOIN packages pk ON pk.project_id=pr.id
                    LEFT JOIN awards a ON a.package_id=pk.id
                    WHERE pr.notice_id IN ({placeholders})
                    ORDER BY pr.notice_id, pk.id, a.id""",
                ordered_ids,
            ).fetchall()
            package_groups: dict[int, dict[int, dict[str, Any]]] = {}
            award_rows: dict[int, list[Any]] = {notice_id: [] for notice_id in ordered_ids}
            for row in package_rows:
                notice_id = row["notice_id"]
                package_groups.setdefault(notice_id, {}).setdefault(
                    row["package_id"],
                    {
                        "package_code": row["package_code"],
                        "package_name": row["package_name"],
                        "package_award_total": row["package_award_total"],
                        "awards": [],
                    },
                )
                if row["award_id"] is not None:
                    award = {
                        "package_id": row["package_id"],
                        "package_code": row["package_code"],
                        "package_name": row["package_name"],
                        "awardee": row["awardee"],
                        "amount": row["award_amount"],
                    }
                    package_groups[notice_id][row["package_id"]]["awards"].append(award)
                    award_rows[notice_id].append(award)

            total_sheet = worksheets["总表"]
            for notice in notices:
                notice_id = notice["id"]
                context = notice_context[notice_id]
                packages = package_groups.get(notice_id, {})
                for package in packages.values():
                    package_label = _package_label(package["package_code"], package["package_name"])
                    for award in package["awards"]:
                        total_sheet.append((
                            total_sheet.max_row - 1, None, context["uuid"], package_label,
                            context["project_name"], context["buyer"], _as_text(award["awardee"]),
                            _yuan_to_wanyuan(award["amount"]),
                        ))
                    if not package["awards"]:
                        # Retain every known package even when supplier/amount was not extracted.
                        amount = package["package_award_total"]
                        if amount in (None, "") and len(packages) == 1:
                            amount = context["announced_total_award"]
                        total_sheet.append((
                            total_sheet.max_row - 1, None, context["uuid"], package_label,
                            context["project_name"], context["buyer"], "",
                            _yuan_to_wanyuan(amount),
                        ))
                if not packages:
                    total_sheet.append((
                        total_sheet.max_row - 1, None, context["uuid"], "",
                        context["project_name"], context["buyer"], "",
                        _yuan_to_wanyuan(context["announced_total_award"]),
                    ))

            item_rows = connection.execute(
                f"""SELECT i.notice_id, p.package_code, p.package_name, i.product_name,
                           i.category, i.brand, i.model, i.quantity, i.unit_price, i.total_price
                    FROM procurement_items i
                    LEFT JOIN packages p ON p.id=i.package_id
                    WHERE i.notice_id IN ({placeholders}) ORDER BY i.notice_id, i.id""",
                ordered_ids,
            ).fetchall()
            item_sheet = worksheets["标的表"]
            for row in item_rows:
                item_sheet.append((
                    item_sheet.max_row - 1,
                    notice_context[row["notice_id"]]["uuid"],
                    _package_label(row["package_code"], row["package_name"]),
                    _as_text(row["product_name"]), _as_text(row["category"]),
                    _as_text(row["brand"]), _as_text(row["model"]), _quantity(row["quantity"]),
                    _yuan_to_wanyuan(row["unit_price"]), _yuan_to_wanyuan(row["total_price"]), "",
                ))

            participant_rows = connection.execute(
                f"""SELECT pr.notice_id, pk.id AS package_id, pk.package_code, pk.package_name,
                           bp.raw_name, bp.outcome
                    FROM bid_participations bp
                    JOIN packages pk ON pk.id=bp.package_id
                    JOIN projects pr ON pr.id=pk.project_id
                    WHERE pr.notice_id IN ({placeholders}) ORDER BY pr.notice_id, pk.id, bp.id""",
                ordered_ids,
            ).fetchall()
            bidder_sheet = worksheets["投标人表"]
            details = _bidder_details(connection, ordered_ids)
            name_packages: dict[tuple[int, str], set[str]] = {}
            for row in participant_rows:
                name_packages.setdefault(
                    (row["notice_id"], normalize_bidder_name(row["raw_name"])), set(),
                ).add(_as_text(row["package_code"]) or "default")
            for notice_id, rows in award_rows.items():
                for award in rows:
                    name_packages.setdefault(
                        (notice_id, normalize_bidder_name(award["awardee"])), set(),
                    ).add(_as_text(award["package_code"]) or "default")
            used_details: set[tuple[int, str, str]] = set()

            def matching_detail(notice_id: int, package_code: Any, name: str) -> dict[str, Any] | None:
                normalized_name = normalize_bidder_name(name)
                code = _as_text(package_code) or "default"
                candidates = [record for record in details.get(notice_id, [])
                              if normalize_bidder_name(record["raw_name"]) == normalized_name]
                explicit_codes = {record["package_code"] for record in candidates
                                  if record["package_code"] != "default"}
                matching = [record for record in candidates if record["package_code"] == code]
                # An unlabelled review table may supplement a supplier only when
                # its package is unique in both participation and source data.
                if (code != "default"
                        and len(name_packages.get((notice_id, normalized_name), set())) == 1
                        and explicit_codes <= {code}):
                    matching.extend(record for record in candidates
                                    if record["package_code"] == "default")
                for record in matching:
                    used_details.add((notice_id, record["package_code"], normalized_name))
                merged = merge_bidder_details([
                    {**record, "package_code": code} for record in matching
                ])
                return merged[0] if len(merged) == 1 else None

            participant_keys: set[tuple[int, int, str]] = set()
            for row in participant_rows:
                name = _as_text(row["raw_name"])
                participant_keys.add((row["notice_id"], row["package_id"], name.casefold()))
                detail = matching_detail(row["notice_id"], row["package_code"], name)
                bidder_sheet.append((
                    bidder_sheet.max_row - 1,
                    notice_context[row["notice_id"]]["uuid"],
                    _package_label(row["package_code"], row["package_name"]),
                    name,
                    *_bidder_cells(detail, winner=row["outcome"] == "winner"),
                ))
            for notice_id, rows in award_rows.items():
                for award in rows:
                    name = _as_text(award["awardee"])
                    key = (notice_id, award["package_id"], name.casefold())
                    if not name or key in participant_keys:
                        continue
                    detail = matching_detail(notice_id, award["package_code"], name)
                    bidder_sheet.append((
                        bidder_sheet.max_row - 1, notice_context[notice_id]["uuid"],
                        _package_label(award["package_code"], award["package_name"]),
                        name, *_bidder_cells(detail, winner=True),
                    ))
            # Preserve explicit review-table suppliers that the legacy
            # participation projection did not include, without guessing winners.
            for notice_id, records in details.items():
                for record in records:
                    name = _as_text(record["raw_name"])
                    normalized_name = normalize_bidder_name(name)
                    code = record["package_code"]
                    if (notice_id, code, normalized_name) in used_details:
                        continue
                    if code == "default" and (notice_id, normalized_name) in name_packages:
                        # The supplier is known in multiple packages; this source
                        # has no safe package assignment and must not duplicate it.
                        continue
                    package = next((package for package in package_groups.get(notice_id, {}).values()
                                    if package["package_code"] == code), None)
                    package_label = _package_label(code, package["package_name"] if package else None)
                    bidder_sheet.append((
                        bidder_sheet.max_row - 1, notice_context[notice_id]["uuid"],
                        package_label, name, *_bidder_cells(record, winner=False),
                    ))

    for sheet in worksheets.values():
        for row in sheet.iter_rows(min_row=3):
            for cell in row:
                # Source text must stay text even when it starts with an Excel formula marker.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.font = Font(name="微软雅黑", size=10, color="202124")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(bottom=_THIN_GRAY)
                if sheet.title == "总表" and cell.column == 2:
                    cell.fill = _LIGHT
            sheet.row_dimensions[row[0].row].height = min(409, max(
                20,
                max(_wrapped_lines(cell.value, width) * 16 + 4
                    for cell, width in zip(row, _COLUMN_WIDTHS[sheet.title], strict=True)),
            ))
        sheet.auto_filter.ref = f"A1:{get_column_letter(sheet.max_column)}{max(sheet.max_row, 1)}"
        # Explicit numeric formats for amounts and quantities in their respective sheets.
        amount_columns = {
            "总表": {8},
            "标的表": {9, 10},
            "投标人表": {7, 8},
        }[sheet.title]
        for column in amount_columns:
            for row_index in range(3, sheet.max_row + 1):
                sheet.cell(row_index, column).number_format = _CURRENCY_FORMAT
        if sheet.title == "标的表":
            for row_index in range(3, sheet.max_row + 1):
                sheet.cell(row_index, 8).number_format = "General"

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
