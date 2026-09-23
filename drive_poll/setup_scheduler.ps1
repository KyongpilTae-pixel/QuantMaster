# Windows 작업 스케줄러 등록 (schtasks.exe 방식 — PS 5.1 호환)
# 실행: PowerShell -ExecutionPolicy Bypass -File setup_scheduler.ps1

$TaskName   = "QuantMaster-DrivePoll"
$PythonExe  = "C:\Users\Administrator\miniconda3\envs\quantmaster\python.exe"
$ScriptPath = "C:\project\quant\drive_poll\poll_daemon.py"

# 기존 태스크 제거 (없으면 무시)
schtasks /Delete /TN $TaskName /F 2>$null

# XML 방식으로 태스크 등록 (1시간 반복, SYSTEM 계정, 로그인 불필요)
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>QuantMaster Google Drive _comms/ 자율 폴링 (cloud 메시지 감지)</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT30M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$PythonExe</Command>
      <Arguments>$ScriptPath --once</Arguments>
      <WorkingDirectory>C:\project\quant\drive_poll</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$xmlPath = "$env:TEMP\quantmaster_poll_task.xml"
$xml | Out-File -FilePath $xmlPath -Encoding Unicode

schtasks /Create /TN $TaskName /XML $xmlPath /F

Remove-Item $xmlPath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "태스크 등록 완료: $TaskName"
Write-Host "실행 주기: 30분"
Write-Host "로그 파일: C:\project\quant\drive_poll\poll_daemon.log"
Write-Host ""
Write-Host "즉시 테스트 실행:"
Write-Host "  schtasks /Run /TN '$TaskName'"
Write-Host ""
Write-Host "태스크 상태 확인:"
Write-Host "  schtasks /Query /TN '$TaskName' /FO LIST"
