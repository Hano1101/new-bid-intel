param(
    [string]$DatabasePath = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '请先安装后端虚拟环境与依赖，再恢复官方数据集。'
}
if (-not $DatabasePath) {
    $DatabasePath = Join-Path (Split-Path $repoRoot -Parent) '08_任务三自助上传与下载\运行数据库\official.sqlite'
}
if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
    throw '未找到官方数据库；请用 -DatabasePath 指定提交包中的 official.sqlite。公开 Git 仓库不包含此数据。'
}
$sourcePath = (Resolve-Path -LiteralPath $DatabasePath).Path
$forceValue = if ($Force) { '1' } else { '0' }
$restoreCode = @'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

root, source, force = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == '1'
sys.path.insert(0, str(root / 'backend'))
from app.config import settings
from app.storage import initialize

target = settings.resolved_database_path.parent / 'datasets' / '6e032fb74bd345e29989e4f86e195920.sqlite'
if target.exists() and not force:
    print('Official dataset already exists; retained without overwriting.')
    raise SystemExit(0)
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
    if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('Official database integrity check failed.')
    if src.execute('SELECT count(*) FROM notices').fetchone()[0] != 1038:
        raise SystemExit('Expected 1038 official notices; refusing this snapshot.')
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix('.restoring')
    with closing(sqlite3.connect(pending)) as dst:
        src.backup(dst)
initialize(pending)
pending.replace(target)
print('Official dataset restored: 1038 notices. Select the official dataset in the web UI.')
'@
Push-Location (Join-Path $repoRoot 'backend')
try {
    & $pythonExe -c $restoreCode $repoRoot $sourcePath $forceValue
    if ($LASTEXITCODE -ne 0) { throw '恢复官方数据集失败。' }
} finally { Pop-Location }
