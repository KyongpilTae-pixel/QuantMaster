# 매일 저녁 7시 자동 git add/commit/push
# Task Scheduler에서 실행: PowerShell -ExecutionPolicy Bypass -File auto_git_push.ps1

$RepoPath = "C:\project\quant"
$LogFile  = "$RepoPath\auto_push.log"
$GitExe   = "C:\Program Files\Git\bin\git.exe"

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ssZ")
    "$ts $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

Set-Location $RepoPath
Log "=== 자동 push 시작 ==="

# 스테이징: 소스 파일만 (JSON/HTML/log 제외)
$addResult = & $GitExe add "*.py" "*.ps1" "quantletter/*.csv" "drive_poll/*.py" "drive_poll/*.ps1" 2>&1
Log "git add: $addResult"

# 변경 여부 확인
$diffStat = & $GitExe diff --cached --stat 2>&1
if (-not $diffStat) {
    Log "변경 없음 — 커밋 스킵"
} else {
    $date = (Get-Date).ToString("yyyy-MM-dd")
    $commitMsg = "chore: 자동 백업 $date`n`nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    $commitResult = & $GitExe commit -m $commitMsg 2>&1
    Log "git commit: $commitResult"
}

# push
$pushResult = & $GitExe push origin main 2>&1
Log "git push: $pushResult"
Log "=== 완료 ==="
