$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "dist\Room OS"
$installRoot = Join-Path $env:LOCALAPPDATA "Programs\Room OS"
$executable = Join-Path $installRoot "Room OS.exe"

if (-not (Test-Path -LiteralPath (Join-Path $source "Room OS.exe"))) {
    throw "Primero ejecuta scripts\build_windows.ps1"
}

New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
Copy-Item -Path (Join-Path $source "*") -Destination $installRoot -Recurse -Force

$shell = New-Object -ComObject WScript.Shell
$desktopShortcut = $shell.CreateShortcut(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Room OS.lnk")
)
$desktopShortcut.TargetPath = $executable
$desktopShortcut.WorkingDirectory = $installRoot
$desktopShortcut.Description = "Iniciar Room OS"
$desktopShortcut.IconLocation = "$executable,0"
$desktopShortcut.Save()

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$menuShortcut = $shell.CreateShortcut((Join-Path $startMenu "Room OS.lnk"))
$menuShortcut.TargetPath = $executable
$menuShortcut.WorkingDirectory = $installRoot
$menuShortcut.Description = "Iniciar Room OS"
$menuShortcut.IconLocation = "$executable,0"
$menuShortcut.Save()

Write-Output "Room OS instalado en $installRoot"
