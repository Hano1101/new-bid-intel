import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from filelock import FileLock
from pydantic import BaseModel

from app.datasets import DatabasePath
from app.jobs import (
    JobQueueFull,
    create_job,
    job_path,
    job_state_lock,
    jobs_root,
    launch,
    queue_job,
    read_json,
    read_notice_progress,
    snapshot,
    write_json,
)

router = APIRouter(prefix='/api/v1/jobs', tags=['batch jobs'])


class JobCreate(BaseModel):
    source_directory: str | None = None
    directory_id: str | None = None
    preflight_fingerprint: str | None = None
    mode: Literal['rules', 'hybrid', 'model'] = 'hybrid'
    ocr: bool = True


_ARCHIVE_SUFFIXES = ('.zip', '.rar', '.7z')
_MAX_PREVIEW_NOTICES = 200


def intake_root() -> Path:
    """Return the configured intake root; never invent a browsing root."""
    from app.config import settings

    if not settings.intake_root or not settings.intake_root.strip():
        raise HTTPException(
            status_code=503,
            detail='后台尚未配置 INTAKE_ROOT，暂时不能浏览或选择服务器材料目录。',
        )
    try:
        root = Path(settings.intake_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail='配置的 INTAKE_ROOT 不存在或不可访问。') from exc
    if not root.is_dir():
        raise HTTPException(status_code=503, detail='配置的 INTAKE_ROOT 不是目录。')
    return root


def resolve_directory_id(root: Path, directory_id: str) -> Path:
    """Resolve a root-relative browser id and reject traversal and symlink escapes."""
    if not isinstance(directory_id, str):
        raise TypeError('目录标识格式无效')
    if directory_id == '':
        return root
    if ('\\' in directory_id or ':' in directory_id or directory_id.startswith('/')
            or any(part in {'', '.', '..'} for part in directory_id.split('/'))):
        raise ValueError('目录标识必须是 INTAKE_ROOT 内的相对目录')
    try:
        source = root.joinpath(*directory_id.split('/')).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError('目录不存在或不可访问') from exc
    if not source.is_relative_to(root):
        raise ValueError('目录必须位于配置的 INTAKE_ROOT 内')
    if not source.is_dir():
        raise ValueError('所选路径不是目录')
    return source


def resolve_source_directory(root: Path, payload: JobCreate) -> Path:
    if payload.directory_id is not None and payload.source_directory is not None:
        raise ValueError('只能提交目录标识或服务器目录路径其中一项')
    if payload.directory_id is not None:
        return resolve_directory_id(root, payload.directory_id)
    if payload.source_directory is None:
        raise ValueError('请先选择服务器材料目录')
    try:
        source = Path(payload.source_directory).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError('数据目录不存在或不可访问') from exc
    if not source.is_relative_to(root):
        raise ValueError('数据目录必须位于配置的 INTAKE_ROOT 内')
    if not source.is_dir():
        raise ValueError('所选路径不是目录')
    return source


def _directory_id(root: Path, source: Path) -> str:
    relative = source.relative_to(root)
    return '' if relative == Path('.') else relative.as_posix()


def _linked_metadata(info: os.stat_result) -> bool:
    # Windows junctions and other reparse points are not always reported as symlinks.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _is_linked(path: Path) -> bool:
    try:
        return _linked_metadata(path.lstat())
    except FileNotFoundError:
        return False


def _directory_bytes(root: Path, source: Path) -> tuple[int, int, int, str]:
    """Count regular-file bytes and fingerprint directory metadata without following links."""
    total_bytes = 0
    file_count = 0
    skipped_symlinks = 0
    fingerprint = hashlib.sha256()
    pending = [source]
    while pending:
        current = pending.pop()
        try:
            if _is_linked(current):
                skipped_symlinks += 1
                continue
            resolved = current.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError('目录必须位于配置的 INTAKE_ROOT 内')
            with os.scandir(resolved) as directory_entries:
                entries = sorted(directory_entries, key=lambda entry: (entry.name.casefold(), entry.name))
                child_directories = []
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                        relative = Path(entry.path).relative_to(root).as_posix()
                        fingerprint.update(json.dumps(
                            [relative, info.st_mode, info.st_size, info.st_mtime_ns,
                             info.st_ino, info.st_dev,
                             getattr(info, 'st_file_attributes', 0)],
                            ensure_ascii=False, separators=(',', ':'),
                        ).encode('utf-8'))
                        fingerprint.update(b'\n')
                        if _linked_metadata(info):
                            skipped_symlinks += 1
                        elif stat.S_ISDIR(info.st_mode):
                            child_directories.append(Path(entry.path))
                        elif stat.S_ISREG(info.st_mode):
                            total_bytes += info.st_size
                            file_count += 1
                    except OSError as exc:
                        raise ValueError('读取目录文件信息失败') from exc
                pending.extend(reversed(child_directories))
        except OSError as exc:
            raise ValueError('读取目录内容失败') from exc
    return total_bytes, file_count, skipped_symlinks, fingerprint.hexdigest()


def preflight_directory(root: Path, source: Path) -> dict:
    """Summarize the same top-level notice/attachment pairs consumed by create_job."""
    html_paths = sorted([*source.glob('*.html'), *source.glob('*.htm')])
    invalid_materials = 0
    symlink_materials = 0
    notices = []
    paired_archives: set[Path] = set()
    for html in html_paths:
        if _is_linked(html):
            invalid_materials += 1
            symlink_materials += 1
            continue
        if not html.is_file():
            invalid_materials += 1
            continue
        attachments = []
        for suffix in _ARCHIVE_SUFFIXES:
            archive = html.with_suffix(suffix)
            if _is_linked(archive):
                invalid_materials += 1
                symlink_materials += 1
            elif archive.is_file():
                attachments.append(archive.name)
                paired_archives.add(archive)
        notices.append({'html': html.name, 'attachments': attachments})

    archive_paths = []
    for entry in source.iterdir():
        if os.path.normcase(entry.suffix) not in _ARCHIVE_SUFFIXES:
            continue
        if _is_linked(entry):
            # The scanner only follows a symlink when it is a matching attachment.
            continue
        if entry.is_file():
            archive_paths.append(entry)
    unpaired = sorted(path.name for path in archive_paths if path not in paired_archives)
    total_bytes, total_files, skipped_symlinks, fingerprint = _directory_bytes(root, source)
    preview_notices = notices[:_MAX_PREVIEW_NOTICES]
    return {
        'directory_id': _directory_id(root, source),
        'directory_name': source.name or '材料根目录',
        'html_count': len(html_paths),
        'paired_archive_count': sum(len(row['attachments']) for row in notices),
        'notices_with_attachments': sum(bool(row['attachments']) for row in notices),
        'unpaired_material_count': len(unpaired),
        'unpaired_materials': unpaired[:_MAX_PREVIEW_NOTICES],
        'unpaired_materials_truncated': len(unpaired) > _MAX_PREVIEW_NOTICES,
        'notices': preview_notices,
        'notices_truncated': len(notices) > _MAX_PREVIEW_NOTICES,
        'directory_bytes': total_bytes,
        'directory_file_count': total_files,
        'preflight_fingerprint': fingerprint,
        'skipped_symlink_count': skipped_symlinks,
        'invalid_material_count': invalid_materials,
        'symlink_material_count': symlink_materials,
        'can_start': bool(notices) and invalid_materials == 0,
        'top_level_scan_only': True,
        'scan_note': '任务只扫描当前目录顶层的 .html/.htm 公告及同名 .zip/.rar/.7z；不会递归处理子目录。目录总字节数递归统计常规文件，符号链接和 Windows junction/reparse point 不计入。',
    }


def reject_symlink_materials(source: Path) -> None:
    """Do not let the existing manifest scanner read linked source files."""
    html_paths = sorted([*source.glob('*.html'), *source.glob('*.htm')])
    for html in html_paths:
        if _is_linked(html):
            raise ValueError(f'公告材料不能是符号链接：{html.name}')
        if not html.is_file():
            raise ValueError(f'公告材料不是常规文件：{html.name}')
        for suffix in _ARCHIVE_SUFFIXES:
            archive = html.with_suffix(suffix)
            if _is_linked(archive):
                raise ValueError(f'配对附件不能是符号链接：{archive.name}')


def checked_job(job_id: str, database: Path) -> Path:
    try:
        root = job_path(job_id)
        if Path(read_json(root / 'job.json')['database']).resolve() != database.resolve():
            raise ValueError('当前数据集下没有此任务')
        return root
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get('')
def list_jobs(database: DatabasePath):
    result = []
    for path in sorted(jobs_root().glob('*/job.json')):
        try:
            if Path(read_json(path)['database']).resolve() == database.resolve():
                result.append(snapshot(path.parent))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


@router.get('/directories')
def browse_directories(database: DatabasePath, directory_id: str = Query(default='')):
    del database  # Require the same valid dataset context as the batch-job panel.
    root = intake_root()
    try:
        source = resolve_directory_id(root, directory_id)
        directories = []
        for entry in source.iterdir():
            try:
                if _is_linked(entry) or not entry.is_dir():
                    continue
                resolved = entry.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    continue
                directories.append({
                    'name': entry.name,
                    'directory_id': _directory_id(root, resolved),
                })
            except (OSError, RuntimeError):
                continue
        directories.sort(key=lambda row: (row['name'].casefold(), row['name']))
        current_id = _directory_id(root, source)
        parent_id = None if not current_id else (
            '' if '/' not in current_id else current_id.rsplit('/', 1)[0]
        )
        return {
            'directory_id': current_id,
            'directory_name': source.name or '材料根目录',
            'parent_directory_id': parent_id,
            'directories': directories,
        }
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail='无法读取所选目录，请检查后端服务账户的目录权限。',
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/preflight')
def get_preflight(database: DatabasePath, directory_id: str = Query(default='')):
    del database
    root = intake_root()
    try:
        source = resolve_directory_id(root, directory_id)
        return preflight_directory(root, source)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail='无法读取所选目录，请检查后端服务账户的目录权限。',
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('', status_code=202)
def start_job(payload: JobCreate, database: DatabasePath):
    from app.config import settings
    # Browser selections are root-relative ids. Legacy absolute paths remain
    # accepted only when they resolve inside the explicitly configured root.
    allowed = intake_root()
    try:
        source = resolve_source_directory(allowed, payload)
        reject_symlink_materials(source)
        if payload.directory_id is not None:
            current_preflight = preflight_directory(allowed, source)
            if not current_preflight['can_start']:
                raise ValueError('所选目录没有可处理的有效 HTML 公告')
            if not payload.preflight_fingerprint:
                raise HTTPException(status_code=422, detail='请先完成目录预检，再确认创建任务。')
            current_fingerprint = current_preflight['preflight_fingerprint']
            if current_fingerprint != payload.preflight_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail='预检后目录内容或属性已变化，请重新预检并确认后再创建任务。',
                )
        dataset_id = 'default' if database.resolve() == settings.resolved_database_path.resolve() else database.stem
        job = create_job(source, database, dataset_id, mode=payload.mode, ocr=payload.ocr)
        launch(job_path(job['id']))
        return job
    except (ValueError, OSError) as exc:
        if isinstance(exc, JobQueueFull):
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/{job_id}')
def get_job(job_id: str, database: DatabasePath):
    return snapshot(checked_job(job_id, database))


@router.get('/{job_id}/report')
def get_report(job_id: str, database: DatabasePath):
    root = checked_job(job_id, database)
    return {'job': snapshot(root), 'notices': read_notice_progress(root)}


@router.post('/{job_id}/pause', status_code=202)
def pause_job(job_id: str, database: DatabasePath):
    root = checked_job(job_id, database)
    with FileLock(str(jobs_root() / 'admission.lock'), timeout=300), job_state_lock(root):
        (root / 'stop').touch()
        job = read_json(root / 'job.json')
        if job.get('status') == 'queued':
            job.update(status='paused', finished_at=time.time())
            write_json(root / 'job.json', job)
    return {'message': '已请求暂停，将在当前文件处理后保存进度'}


@router.post('/{job_id}/stop', status_code=202)
def stop_job(job_id: str, database: DatabasePath):
    """Gracefully stop scheduling and retain checkpoints for an explicit resume."""
    root = checked_job(job_id, database)
    with FileLock(str(jobs_root() / 'admission.lock'), timeout=300), job_state_lock(root):
        (root / 'stop').touch()
        (root / 'cancel').touch()
        job = read_json(root / 'job.json')
        if job.get('status') in {'queued', 'paused', 'interrupted'}:
            job.update(status='stopped', finished_at=time.time())
            write_json(root / 'job.json', job)
    return {'message': '已请求停止排队；在途请求结束后保留已完成公告和检查点'}


@router.post('/{job_id}/resume', status_code=202)
def resume_job(job_id: str, database: DatabasePath, retry_failed: bool = False):
    root = checked_job(job_id, database)
    try:
        job = queue_job(root, retry_failed=retry_failed)
    except JobQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if job.get('status') == 'queued':
        launch(root)
    return {'message': '已提交续跑；完成的公告不会重复入库', 'status': job.get('status')}
