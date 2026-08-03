param(
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonWindowed = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$mainScript = Join-Path $projectRoot "main.py"
$requirements = Join-Path $projectRoot "requirements.txt"
$dataDirectory = Join-Path $projectRoot "data"
$launcherLog = Join-Path $dataDirectory "launcher.log"
$stdoutLog = Join-Path $dataDirectory "ui_stdout.log"
$stderrLog = Join-Path $dataDirectory "ui_stderr.log"

function Write-LauncherLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $launcherLog -Value "$timestamp | $Message" -Encoding UTF8
}

function Show-LaunchError {
    param([string]$Message)
    Write-LauncherLog "ERROR | $Message"
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "$Message`n`nRegistro: $launcherLog",
        "Room OS no pudo iniciar",
        "OK",
        "Error"
    ) | Out-Null
}

try {
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    Write-LauncherLog "Verificando instalación"

    if (-not (Test-Path -LiteralPath $python)) {
        throw "No existe el entorno virtual en $python"
    }
    if (-not (Test-Path -LiteralPath $pythonWindowed)) {
        throw "No existe el ejecutable gráfico del entorno virtual"
    }
    if (-not (Test-Path -LiteralPath $mainScript)) {
        throw "No se encontró main.py en $projectRoot"
    }

    & $python -c "import cv2, mediapipe, PySide6, google.genai" 2>> $launcherLog
    if ($LASTEXITCODE -ne 0) {
        Write-LauncherLog "Faltan dependencias; intentando repararlas"
        & $python -m pip install -r $requirements >> $launcherLog 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudieron instalar las dependencias de Room OS"
        }
    }

    $userGeminiKey = [Environment]::GetEnvironmentVariable(
        "GEMINI_API_KEY",
        "User"
    )
    if ($userGeminiKey) {
        $env:GEMINI_API_KEY = $userGeminiKey
        Write-LauncherLog "Configuración de Gemini cargada desde el usuario"
    } else {
        Write-LauncherLog "ADVERTENCIA | GEMINI_API_KEY no está configurada"
    }

    if ($VerifyOnly) {
        Write-LauncherLog "Verificación completada correctamente"
        Write-Output "Room OS listo para iniciar"
        exit 0
    }

    $normalizedRoot = $projectRoot.ToLowerInvariant()
    $running = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine.ToLowerInvariant().Contains($normalizedRoot) -and
        $_.CommandLine.ToLowerInvariant().Contains("main.py")
    } | Select-Object -First 1

    if ($running) {
        Write-LauncherLog "Room OS ya estaba abierto (PID $($running.ProcessId))"
        exit 0
    }

    $startArguments = @{
        FilePath = $pythonWindowed
        ArgumentList = "main.py"
        WorkingDirectory = $projectRoot
        RedirectStandardOutput = $stdoutLog
        RedirectStandardError = $stderrLog
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $process = Start-Process @startArguments

    Start-Sleep -Seconds 5
    if ($process.HasExited) {
        $detail = ""
        if (Test-Path -LiteralPath $stderrLog) {
            $detail = (Get-Content -LiteralPath $stderrLog -Tail 8) -join " "
        }
        throw "El proceso terminó durante el arranque. $detail"
    }

    Write-LauncherLog "Room OS iniciado correctamente (PID $($process.Id))"
} catch {
    Show-LaunchError $_.Exception.Message
    exit 1
}
