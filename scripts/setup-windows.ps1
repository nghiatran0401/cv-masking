# First-time setup on Windows. macOS uses `make setup` instead.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "$Name is not installed."
    }
}

Require-Command "uv"
Require-Command "node"
Require-Command "npm"

Set-Location (Join-Path $Root "backend")
uv python install 3.12
uv venv --python 3.12 --managed-python --allow-existing .venv
uv sync --locked --python 3.12 --managed-python

Set-Location (Join-Path $Root "frontend")
npm ci
npm run build

$Static = Join-Path $Root "backend\src\cv_masking\static"
$Dist = Join-Path $Root "frontend\dist"
if (Test-Path -LiteralPath $Static) {
    Remove-Item -LiteralPath $Static -Recurse -Force
}
New-Item -ItemType Directory -Path $Static | Out-Null
Copy-Item -Path (Join-Path $Dist "*") -Destination $Static -Recurse -Force

Write-Host "Setup finished. Start the app with scripts\cv-masking.bat"
