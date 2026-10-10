# EV80 防重码扫码工具 - PyInstaller 便携构建
# 用法: powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 [-SkipInstall]

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ScriptDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $ScriptDir

$SourceWorkbook = Join-Path $ScriptDir "ev80 06(1).xls"
$DistDir = Join-Path $ScriptDir "dist\EV80CodeChecker"
$WorkDir = Join-Path $ScriptDir "build\EV80CodeChecker"
$ExePath = Join-Path $DistDir "EV80CodeChecker.exe"

Write-Host "=== EV80 防重码扫码工具 构建 ===" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $SourceWorkbook -PathType Leaf)) {
    throw "找不到总表文件：$SourceWorkbook"
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "未找到 Python，请先安装 Python 3.8+。"
}
Write-Host "Python: $(& python --version 2>&1)"

if (-not $SkipInstall) {
    Write-Host "安装 requirements.txt ..." -ForegroundColor Yellow
    & python -m pip install -r (Join-Path $ScriptDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "依赖安装失败，退出码：$LASTEXITCODE"
    }
} else {
    Write-Host "跳过依赖安装 (-SkipInstall)" -ForegroundColor Yellow
}

$pyinstallerVersion = & python -m PyInstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($SkipInstall) {
        throw "未找到 PyInstaller；请去掉 -SkipInstall，或先安装 requirements.txt。"
    }
    Write-Host "安装 PyInstaller ..." -ForegroundColor Yellow
    & python -m pip install "pyinstaller>=5.0.0,<7.0.0"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 安装失败，退出码：$LASTEXITCODE"
    }
    $pyinstallerVersion = & python -m PyInstaller --version 2>&1
}
Write-Host "PyInstaller: $pyinstallerVersion"

# 只清理本工具自己的构建输出，不触碰总表或其他项目文件。
if (Test-Path -LiteralPath $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}
if (Test-Path -LiteralPath $WorkDir) {
    Remove-Item -LiteralPath $WorkDir -Recurse -Force
}

Write-Host "构建便携目录 ..." -ForegroundColor Yellow
$pyinstallerArgs = @(
    "--name", "EV80CodeChecker",
    "--onedir",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--distpath", (Join-Path $ScriptDir "dist"),
    "--workpath", (Join-Path $ScriptDir "build\EV80CodeChecker"),
    "--specpath", (Join-Path $ScriptDir "build"),
    "--add-data", "$SourceWorkbook;.",
    "--hidden-import", "xlrd",
    "--hidden-import", "cv2",
    "--hidden-import", "zxingcpp",
    "ev80_code_checker.py"
)
& python -m PyInstaller @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "构建结束但没有找到 EXE：$ExePath"
}

$sizeMb = [math]::Round(((Get-Item -LiteralPath $ExePath).Length / 1MB), 1)
Write-Host "=== 构建成功 ===" -ForegroundColor Green
Write-Host "输出目录：$DistDir"
Write-Host "可执行文件：$ExePath"
Write-Host "EXE 大小：$sizeMb MB"
Write-Host "把整个 dist\EV80CodeChecker 目录复制到目标电脑即可运行。" -ForegroundColor Cyan
