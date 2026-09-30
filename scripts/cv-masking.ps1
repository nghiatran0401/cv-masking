# Windows launcher. macOS uses scripts/cv-masking.command instead.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Python environment missing. In PowerShell, from the project folder: powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1"
}

Set-Location $Root
& $Python -m cv_masking --desktop
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
