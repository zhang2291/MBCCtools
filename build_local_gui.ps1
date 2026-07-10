#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseDir,

    [string]$OutDir,

    [string]$Version = "v1.4.3",

    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $RepoRoot "install"

function Resolve-FullPath {
    param([string]$PathValue)
    return [System.IO.Path]::GetFullPath($PathValue)
}

$BaseDir = Resolve-FullPath $BaseDir
if (-not $OutDir) {
    $OutDir = "$BaseDir-local"
}
$OutDir = Resolve-FullPath $OutDir

if (-not (Test-Path $BaseDir -PathType Container)) {
    throw "Base GUI directory not found: $BaseDir"
}

if (-not $SkipInstall) {
    Write-Host "Generating install directory..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        python .\install.py $Version
        if ($LASTEXITCODE -ne 0) {
            throw "install.py 执行失败，退出码: $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path $InstallDir -PathType Container)) {
    throw "Install directory not found: $InstallDir"
}

Write-Host "Checking base GUI directory..." -ForegroundColor Cyan
$requiredBaseEntries = @(
    "MFAAvalonia.exe",
    "libloader.dll",
    "libs",
    "runtimes"
)

foreach ($entry in $requiredBaseEntries) {
    $entryPath = Join-Path $BaseDir $entry
    if (-not (Test-Path $entryPath)) {
        throw "Base GUI directory is missing required entry: $entryPath"
    }
}

if (Test-Path $OutDir) {
    Write-Host "Removing old output directory: $OutDir" -ForegroundColor Yellow
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}

Write-Host "Copying base GUI directory..." -ForegroundColor Cyan
Copy-Item -LiteralPath $BaseDir -Destination $OutDir -Recurse

Write-Host "Overlaying install artifacts..." -ForegroundColor Cyan
Get-ChildItem -LiteralPath $InstallDir -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $OutDir -Recurse -Force
}

Write-Host ""
Write-Host "Packaging completed." -ForegroundColor Green
Write-Host "Output directory: $OutDir" -ForegroundColor Green
$exePath = Join-Path $OutDir "MFAAvalonia.exe"
Write-Host "Executable: $exePath" -ForegroundColor Green
