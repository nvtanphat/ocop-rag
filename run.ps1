# OCOP GraphRAG: single corpus-to-answer launcher + React development UI
param([switch]$BackendOnly, [switch]$Refresh)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
$argsPipeline = @('tools/cli.py', 'run')
if ($Refresh) { $argsPipeline += '--refresh' }
Write-Host 'Starting OCOP end-to-end pipeline (PDF to API): http://127.0.0.1:8000'
if ($BackendOnly) {
    python @argsPipeline
} else {
    $pipelineCommand = 'python tools/cli.py run'
    if ($Refresh) { $pipelineCommand += ' --refresh' }
    Start-Process powershell -ArgumentList '-NoExit', '-Command', $pipelineCommand -WorkingDirectory $projectRoot
    Set-Location (Join-Path $projectRoot 'frontend')
    if (-not (Test-Path (Join-Path (Get-Location) 'node_modules'))) {
        Write-Host 'Installing frontend packages with npm ci (first run)...'
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed; check Node 22 and network access' }
    }
    npm run dev
}
