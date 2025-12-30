# --- 配置区域 ---
$ScriptFileName = "main.py"  # 你的 Python 脚本文件名
$ExeName = "ThriftCCSwitch"  # 生成的 exe 名字
# 如果你有图标文件(.ico)，请把下一行的 $null 改为 "icon.ico"
$IconFile = $null

# --- 脚本开始 ---
Write-Host "正在准备打包 $ExeName ..." -ForegroundColor Cyan

# 1. 检查 PyInstaller 是否存在
if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "错误: 未检测到 PyInstaller。" -ForegroundColor Red
    Write-Host "请先运行: pip install pyinstaller" -ForegroundColor Yellow
    Pause
    Exit
}

# 2. 构建命令参数
# -F : 打包成单个文件
# -w : 窗口模式（不显示控制台黑框）
# --clean : 清理缓存
# --noconfirm : 不询问覆盖
$Params = @("-F", "-w", "--clean", "--noconfirm", "--name", "$ExeName")

if ($IconFile -and (Test-Path $IconFile)) {
    $Params += ("--icon", "$IconFile")
}

$Params += $ScriptFileName

Write-Host "执行命令: pyinstaller $Params" -ForegroundColor Gray

# 3. 执行打包
Start-Process "pyinstaller" -ArgumentList $Params -NoNewWindow -Wait

# 4. 检查结果
$DistPath = Join-Path $PSScriptRoot "dist\$ExeName.exe"
if (Test-Path $DistPath) {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "打包成功！" -ForegroundColor Green
    Write-Host "文件位置: $DistPath" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Green

    # 可选：完成后自动打开文件夹
    Invoke-Item (Join-Path $PSScriptRoot "dist")
} else {
    Write-Host "`n打包失败，请检查上方的错误信息。" -ForegroundColor Red
}

Write-Host "按任意键退出..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")