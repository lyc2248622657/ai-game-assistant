# 一键本地启动（Docker 不可用时的等价路径：后端 uvicorn + 前端 vite）
# 用法：右键"使用 PowerShell 运行"，或 powershell -ExecutionPolicy Bypass -File start-dev.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== AI 游戏助手智能体平台：一键启动 ===" -ForegroundColor Cyan

# 1. 检查环境
if (-not (Test-Path "$Root\backend\.env")) {
    Write-Host "[ERR] backend\.env 不存在，请先复制 .env.example 并填入 DEEPSEEK_API_KEY" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "$Root\backend\.venv\Scripts\python.exe")) {
    Write-Host "[ERR] backend\.venv 不存在，请先: cd backend; python -m venv .venv; pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

# 2. 停旧进程（若端口被占）
foreach ($port in 8000, 5173) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $conn | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Write-Host "[OK] 释放端口 $port" -ForegroundColor Yellow
    }
}
Start-Sleep -Seconds 1

# 3. 启动后端（后台，日志落盘）
New-Item -ItemType Directory -Force -Path "$Root\.dev" | Out-Null
$back = Start-Process -FilePath "$Root\backend\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory "$Root\backend" `
    -RedirectStandardOutput "$Root\.dev\backend.log" `
    -RedirectStandardError "$Root\.dev\backend.err.log" `
    -PassThru -WindowStyle Hidden
Write-Host "[OK] 后端已启动 (PID $($back.Id)) -> http://127.0.0.1:8000/api/health" -ForegroundColor Green

# 4. 启动前端（后台，日志落盘）
$front = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" `
    -WorkingDirectory "$Root\frontend" `
    -RedirectStandardOutput "$Root\.dev\frontend.log" `
    -RedirectStandardError "$Root\.dev\frontend.err.log" `
    -PassThru -WindowStyle Hidden
Write-Host "[OK] 前端已启动 (PID $($front.Id)) -> http://localhost:5173" -ForegroundColor Green

# 5. 健康检查
$backOk = $false; $frontOk = $false
foreach ($i in 1..20) {
    Start-Sleep -Seconds 2
    try { if ((Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200) { $backOk = $true } } catch {}
    try { if ((Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200) { $frontOk = $true } } catch {}
    if ($backOk -and $frontOk) { break }
}
if ($backOk -and $frontOk) {
    Write-Host "`n=== 启动成功 ===" -ForegroundColor Cyan
    Write-Host "  前端: http://localhost:5173"
    Write-Host "  后端: http://127.0.0.1:8000/api/health"
    Write-Host "  日志: $Root\.dev\*.log   停止: stop-dev.ps1" -ForegroundColor DarkGray
} else {
    Write-Host "`n[WARN] 健康检查未完全通过（后端=$backOk 前端=$frontOk），请查看 .dev\*.log" -ForegroundColor Yellow
}
