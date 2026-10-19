# QuantMaster Reflex 시작 스크립트
# 포트를 여기서만 변경하면 rxconfig.py와 CLI 모두 동기화됩니다.

$BACKEND_PORT = 7600
$HOST_IP      = "192.168.0.84"
$FRONTEND_PORT = 3000

$env:BACKEND_PORT = "$BACKEND_PORT"
$env:HOST_IP      = "$HOST_IP"

Write-Host "QuantMaster 시작 (frontend=$FRONTEND_PORT, backend=$BACKEND_PORT, host=$HOST_IP)"

& "C:\Users\Administrator\miniconda3\envs\quantmaster\python.exe" `
    -m reflex run `
    --backend-port $BACKEND_PORT `
    --frontend-port $FRONTEND_PORT
