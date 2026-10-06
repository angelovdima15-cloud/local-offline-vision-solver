param(
    [string]$Config = 'config.toml',
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$Images
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
# Resolve image paths BEFORE switching directory so callers can use their own cwd.
$resolvedImages = @($Images | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })
$resolvedConfig = if (Test-Path -LiteralPath $Config) { (Resolve-Path -LiteralPath $Config).Path } else { Join-Path $projectRoot $Config }
Push-Location -LiteralPath $projectRoot
try {
    & .\.venv\Scripts\python.exe -m local_vision_solver --config $resolvedConfig solve @resolvedImages
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

