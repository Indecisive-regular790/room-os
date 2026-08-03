$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "No existe el entorno virtual de Room OS"
}

Push-Location $projectRoot
try {
    & $python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar PyInstaller" }
    & $python -m PyInstaller --noconfirm --clean RoomOS.spec
    if ($LASTEXITCODE -ne 0) { throw "La compilación de Room OS falló" }
    Write-Output "Compilación lista en: $projectRoot\dist\Room OS"
} finally {
    Pop-Location
}

