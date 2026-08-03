# QuantMaster Pro - Reflex 서버 자동 재시작 스크립트
# 사용법: powershell -ExecutionPolicy Bypass -File restart_server.ps1

param(
    [int]$MaxRestarts = 99,
    [int]$WaitSeconds = 5,
    [switch]$Once  # 한 번만 실행 (재시작 루프 없음)
)

$ProjectDir = "c:\project\quant"
$LogFile = "$ProjectDir\reflex_restart.log"
$PYTHON = "C:\Users\Administrator\miniconda3\envs\quantmaster\python.exe"

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Kill-Reflex {
    Write-Log "기존 Python/Node 프로세스 정리..."
    cmd /c "taskkill /f /im python.exe 2>nul & taskkill /f /im node.exe 2>nul & exit 0" | Out-Null
    Start-Sleep -Seconds 2
}

function Check-Port {
    param([int]$Port)
    $conn = Test-NetConnection -ComputerName localhost -Port $Port -WarningAction SilentlyContinue -InformationLevel Quiet
    return $conn
}

Set-Location $ProjectDir

Write-Log "=== QuantMaster Pro 자동 재시작 관리자 시작 ==="
Write-Log "프로젝트 디렉토리: $ProjectDir"
Write-Log "최대 재시작 횟수: $MaxRestarts"

$restartCount = 0

while ($restartCount -lt $MaxRestarts) {
    $restartCount++
    Write-Log "--- 서버 시작 시도 #$restartCount ---"

    # 기존 프로세스 정리
    Kill-Reflex

    # 포트 확인
    if (Check-Port 3000) {
        Write-Log "포트 3000이 이미 사용 중. 10초 대기 후 재시도..."
        Start-Sleep -Seconds 10
        Kill-Reflex
    }

    # 분리 실행: 백엔드 + 프론트엔드 재시작 스크립트 호출
    Write-Log "Reflex 분리 실행 시작 중..."

    $proc = Start-Process -FilePath "powershell" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ProjectDir\start_split.ps1" `
        -WorkingDirectory $ProjectDir `
        -PassThru `
        -NoNewWindow

    Write-Log "PID: $($proc.Id)"

    # 프로세스가 종료될 때까지 대기
    $proc.WaitForExit()
    $exitCode = $proc.ExitCode

    Write-Log "서버 종료됨. 종료 코드: $exitCode"

    if ($Once) {
        Write-Log "Once 모드 - 재시작 없이 종료."
        break
    }

    if ($restartCount -ge $MaxRestarts) {
        Write-Log "최대 재시작 횟수($MaxRestarts) 도달. 중단."
        break
    }

    Write-Log "${WaitSeconds}초 후 재시작..."
    Start-Sleep -Seconds $WaitSeconds
}

Write-Log "=== 자동 재시작 관리자 종료 ==="
