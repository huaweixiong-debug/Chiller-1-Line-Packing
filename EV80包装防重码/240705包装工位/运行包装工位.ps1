param([switch]$Silent)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$sourceApp = Join-Path $projectRoot "python_app"
$runtimeRoot = Join-Path $env:LOCALAPPDATA "PackagingStation\runtime"
$runtimeApp = Join-Path $runtimeRoot "python_app"
$pythonPrefix = @()
$python = $null
$pythonCandidates = @(
    "C:\Python312\python.exe",
    "C:\Python313\python.exe",
    "C:\Python314\python.exe",
    (Join-Path $env:ProgramFiles "Python312\python.exe"),
    (Join-Path $env:ProgramFiles "Python313\python.exe"),
    (Join-Path $env:ProgramFiles "Python314\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe")
)
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $python = $pyLauncher.Source
        $pythonPrefix = @("-3.12")
    }
}
if (-not $python) {
    throw "Real Python 3.12+ x64 was not found. Install Python and run this script again."
}

function Write-Step($message) {
    if (-not $Silent) { Write-Host $message -ForegroundColor DarkGray }
}

Write-Step "Using Python: $python"

# Single instance guard: exit quietly when the station is already running.
$existing = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*python_app*' }
if ($existing) {
    if ($Silent) { exit 0 }
    Write-Host "Packaging station is already running (PID $($existing.ProcessId -join ', '))." -ForegroundColor Yellow
    exit 0
}

New-Item -ItemType Directory -Path $runtimeApp -Force | Out-Null
Get-ChildItem -LiteralPath $sourceApp -File | ForEach-Object {
    $targetFile = Join-Path $runtimeApp $_.Name
    $needsCopy = -not (Test-Path -LiteralPath $targetFile)
    if (-not $needsCopy) {
        $existingFile = Get-Item -LiteralPath $targetFile
        $needsCopy = $_.Length -ne $existingFile.Length -or $_.LastWriteTimeUtc -ne $existingFile.LastWriteTimeUtc
    }
    if ($needsCopy) {
        Copy-Item -LiteralPath $_.FullName -Destination $targetFile -Force
    }
}

Push-Location $runtimeRoot
try {
    $ErrorActionPreference = "Continue"
    & $python @pythonPrefix -c "from PySide6.QtWidgets import QApplication; import pymysql; import serial" 2>$null
    if ($LASTEXITCODE -ne 0) {
        if (-not $Silent) { Write-Host "Installing required Python packages..." -ForegroundColor Cyan }
        $runtimePackages = @("PySide6-Essentials>=6.8,<7", "PyMySQL>=1.1,<2", "pyserial>=3.5,<4")
        & $python @pythonPrefix -m pip install @runtimePackages
        if ($LASTEXITCODE -ne 0) {
            throw "Python package installation failed"
        }
    }
    if ($Silent) {
        $pythonDir = Split-Path $python -Parent
        $launcherName = [System.IO.Path]::GetFileNameWithoutExtension($python)
        $pythonw = Join-Path $pythonDir ($launcherName + "w.exe")
        if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $python }
        $arguments = @() + $pythonPrefix + @("-m", "python_app")
        Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $runtimeRoot -WindowStyle Hidden
    }
    else {
        & $python @pythonPrefix -m python_app
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

exit 0
