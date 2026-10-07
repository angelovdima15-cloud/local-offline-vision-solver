param([switch]$DownloadAssets)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
    }
    & .\.venv\Scripts\python.exe -m pip install --cache-dir .cache\pip -c requirements.lock.txt -e '.[test]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if ($DownloadAssets) {
        & .\.venv\Scripts\python.exe scripts\install_assets.py --data-dir (Split-Path -Parent $PSScriptRoot)
        if ($LASTEXITCODE -ne 0) { throw 'Model/runtime installation failed.' }
    }
    Write-Output 'Setup finished. Run scripts\start-backend.ps1 for the LAN MVP, or scripts\start-model.ps1 for CLI inference.'
} finally {
    Pop-Location
}
