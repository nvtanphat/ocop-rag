param(
    [switch]$BackendOnly,
    [switch]$Refresh,
    [string]$OcrDataset,
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not $BackendOnly) {
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) {
            npm ci
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}

if ($OcrDataset -or $Refresh) {
    $pipelineArguments = @('tools/cli.py', 'run', '--build-only', '--no-semantic-extract')
    if ($OcrDataset) { $pipelineArguments += @('--ocr-dataset', $OcrDataset) }
    if ($Refresh) { $pipelineArguments += '--refresh' }
    python @pipelineArguments
    if ($LASTEXITCODE -ne 0) { throw 'Corpus build failed; API was not started' }
}

Write-Host "OCOP GraphRAG: http://127.0.0.1:$Port"
python -m uvicorn backend.api.ocop_main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
