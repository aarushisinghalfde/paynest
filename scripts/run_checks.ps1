<#
  Bring the demo up and run every live gate in one go, saving the output to a log file.

  Usage (from the repo root):
    .\scripts\run_checks.ps1            # start EC2 + RDS if stopped, wait for health, run all checks
    .\scripts\run_checks.ps1 -Restart   # also restart the app first (pulls the newest :latest image)

  It reads ADMIN_TOKEN from .env (never writes it) and writes checks_<date-time>.log in the repo root.
  Paste that log back to Claude.
#>
param([switch]$Restart)

$ErrorActionPreference = "Continue"
$AwsProfile = "payce-fde"
$Region = "ap-southeast-2"
$InstanceId = "i-038b0f4a1eee1c90e"
$Health = "https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/api/health"
$Log = "checks_{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmm")

function Say($msg) { $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg; Write-Host $line -ForegroundColor Cyan; Add-Content $Log $line }

function Wait-Healthy([int]$Minutes) {
  $deadline = (Get-Date).AddMinutes($Minutes)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 10
      if ($r.StatusCode -eq 200 -and $r.Content.TrimStart().StartsWith("{")) { Say "Health OK: $($r.Content)"; return $true }
    } catch { }
    Start-Sleep -Seconds 20
  }
  return $false
}

# 1. Start EC2 + RDS (no-op if already running).
Say "Starting the demo (RDS then EC2) if stopped..."
& "$PSScriptRoot\demo.ps1" start *>&1 | Tee-Object -FilePath $Log -Append
$env:AWS_PROFILE = $AwsProfile

# 2. Optional restart so the server pulls the newest image.
if ($Restart) {
  Say "Restarting the app on $InstanceId ..."
  aws ssm send-command --region $Region --instance-ids $InstanceId --document-name AWS-RunShellScript `
    --parameters "commands=['systemctl restart paynest']" --query "Command.CommandId" --output text *>&1 | Tee-Object -FilePath $Log -Append
  Start-Sleep -Seconds 60
}

# 3. Wait for the app.
Say "Waiting for health (up to 15 min)..."
if (-not (Wait-Healthy 15)) { Say "FAIL: app never became healthy. Stopping here."; exit 1 }

# 4. ADMIN_TOKEN from .env (read only).
$tokenLine = Get-Content ".env" -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
if ($tokenLine) { $env:ADMIN_TOKEN = ($tokenLine -split '=', 2)[1].Trim().Trim('"') } else { Say "WARN: ADMIN_TOKEN not found in .env" }

# 5. All live gates.
foreach ($check in "check_phase4.py", "check_chat.py", "check_dashboard.py", "check_knowledge.py") {
  Say "=== $check ==="
  python "scripts\$check" *>&1 | Tee-Object -FilePath $Log -Append
  Say "exit code $LASTEXITCODE"
}
Say "Done. Log: $Log"
