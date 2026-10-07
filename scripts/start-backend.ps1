param([string]$Config = 'config.toml', [switch]$Demo, [switch]$ExternalModel)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $backendArgs = @('-m', 'local_vision_solver', '--config', $Config, 'serve', '--open-browser')
    if ($Demo) { $backendArgs += '--demo' }
    if ($ExternalModel) { $backendArgs += '--external-model' }
    & .\.venv\Scripts\python.exe @backendArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
