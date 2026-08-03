# QuantMaster Pro - 백엔드/프론트엔드 분리 실행 스크립트
# 프론트엔드가 죽어도 백엔드는 살아 있고, 프론트엔드만 자동 재시작
#
# 사용법: powershell -ExecutionPolicy Bypass -File start_split.ps1

param(
    [int]$FrontendWaitSeconds = 3,
    [int]$BackendPort = 7600,
    [int]$FrontendPort = 3000
)

$ProjectDir = "c:\project\quant"
$WebDir = "$ProjectDir\.web"
$LogFile = "$ProjectDir\reflex_split.log"
$PYTHON = "C:\Users\Administrator\miniconda3\envs\quantmaster\python.exe"
$NPM = "C:\Program Files\nodejs\npm.cmd"

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Kill-All {
    Write-Log "기존 Python/Node 프로세스 정리..."
    cmd /c "taskkill /f /im python.exe 2>nul & taskkill /f /im node.exe 2>nul & exit 0" | Out-Null
    Start-Sleep -Seconds 2
}

Set-Location $ProjectDir

Write-Log "=== QuantMaster Pro 분리 실행 모드 ==="
Write-Log "백엔드 포트: $BackendPort / 프론트엔드 포트: $FrontendPort"

# 기존 프로세스 정리
Kill-All

# ─── 백엔드 시작 (별도 창) ───────────────────────────────────────────────
Write-Log "[백엔드] reflex run --backend-only 시작..."
$backendProc = Start-Process -FilePath $PYTHON `
    -ArgumentList "-m", "reflex", "run", "--backend-only", "--backend-port", $BackendPort `
    -WorkingDirectory $ProjectDir `
    -PassThru `
    -WindowStyle Normal

Write-Log "[백엔드] PID: $($backendProc.Id)"

# 백엔드 초기화 대기
Write-Log "[백엔드] 초기화 대기 (10초)..."
Start-Sleep -Seconds 10

# .web 디렉토리 확인
if (-not (Test-Path $WebDir)) {
    Write-Log "[오류] .web 디렉토리가 없습니다. 먼저 'reflex run'을 한 번 실행하세요."
    exit 1
}

# ─── 프론트엔드 자동 재시작 루프 ─────────────────────────────────────────
Write-Log "[프론트엔드] 자동 재시작 루프 시작..."
$frontendRestarts = 0

while ($true) {
    # 백엔드가 죽었으면 루프 종료
    if ($backendProc.HasExited) {
        Write-Log "[백엔드] 종료됨 (코드: $($backendProc.ExitCode)). 프론트엔드 루프도 종료."
        break
    }

    $frontendRestarts++
    Write-Log "[프론트엔드] 시작 시도 #$frontendRestarts (http://localhost:$FrontendPort)"

    # Node 프론트엔드 시작 (PORT=3000 env var 설정)
    $frontEnv = [System.Environment]::GetEnvironmentVariables()
    $frontEnv["PORT"] = $FrontendPort
    $frontProc = Start-Process -FilePath "cmd" `
        -ArgumentList "/c", "set PORT=$FrontendPort && `"$NPM`" run dev" `
        -WorkingDirectory $WebDir `
        -PassThru `
        -NoNewWindow

    Write-Log "[프론트엔드] PID: $($frontProc.Id)"

    # 프론트엔드 종료 대기
    $frontProc.WaitForExit()
    $exitCode = $frontProc.ExitCode

    Write-Log "[프론트엔드] 종료됨 (코드: $exitCode). ${FrontendWaitSeconds}초 후 재시작..."
    Start-Sleep -Seconds $FrontendWaitSeconds
}

Write-Log "=== 분리 실행 종료 ==="
