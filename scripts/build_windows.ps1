<#
.SYNOPSIS
  Builds a windowed GitTool.exe for Windows, using PyInstaller.
.EXAMPLE
  .\scripts\build_windows.ps1
.EXAMPLE
  .\scripts\build_windows.ps1 -Layout onefile
#>
param(
    [ValidateSet("onedir", "onefile")]
    [string] $Layout = "onedir"
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Die Windows-EXE muss unter Windows erstellt werden."
}

# The Python interpreter currently active in the venv is used.
& python -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Installation von GitTool fehlgeschlagen." }

& python -m pip install --upgrade pyinstaller pillow
if ($LASTEXITCODE -ne 0) { throw "Installation von PyInstaller/Pillow fehlgeschlagen." }

& python scripts/create_icons.py
if ($LASTEXITCODE -ne 0) { throw "Erstellung des Windows-Icons fehlgeschlagen." }

$options = @(
    "--noconfirm", "--clean",
    "--windowed",
    "--icon", "build\\icons\\GitTool.ico",
    "--name", "GitTool",
    "--paths", ".",
    "--collect-submodules", "gittyup",
    "--collect-data", "gittool"
)
if ($Layout -eq "onefile") {
    $options += "--onefile"
} else {
    $options += "--onedir"
}
$options += "gittool_launcher.py"

& python -m PyInstaller @options
if ($LASTEXITCODE -ne 0) { throw "PyInstaller-Build fehlgeschlagen." }

if ($Layout -eq "onefile") {
    Write-Host "Erstellt: dist\GitTool.exe"
} else {
    Write-Host "Erstellt: dist\GitTool\GitTool.exe"
    Write-Host "Den gesamten Ordner dist\GitTool weitergeben."
}

Write-Host "Hinweis: Git for Windows muss auf dem Zielrechner installiert und im PATH sein."
