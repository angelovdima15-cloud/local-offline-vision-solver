param([string]$Config = 'config.toml')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    & .\.venv\Scripts\python.exe -m local_vision_solver --config $Config start-model
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

