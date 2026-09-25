# 停止一键启动的本地服务（按端口停止，保留数据与日志）
$ErrorActionPreference = "SilentlyContinue"
foreach ($port in 8000, 5173) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $conn | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
        Write-Host "[OK] 已停止端口 $port 的进程" -ForegroundColor Green
    } else {
        Write-Host "[--] 端口 $port 无监听进程" -ForegroundColor DarkGray
    }
}
Write-Host "本地服务已停止（数据/日志保留在 backend/data、backend/models、.dev/）"
