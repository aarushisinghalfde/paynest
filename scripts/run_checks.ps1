<#
  Bring the demo up and run every live gate in one go, saving the output to a log file.

  Usage (from the repo root):
    .\scripts\run_checks.ps1            # start EC2 + RDS if stopped, wait for health, run all checks
    .\scripts\run_checks.ps1 -Restart   # also restart the app first (pulls the newest :latest image)
    .\scripts\run_checks.ps1 -Restart -ExpectVersion v0.8.0   # wait until the server reports that version
                                                              (scripts\deploy.ps1 calls it this way)

  It reads ADMIN_TOKEN from .env (never writes it) and writes checks_<date-time>.log in the repo root.
  Paste that log back to Claude.
#>
param([switch]$Restart, [string]$ExpectVersion = "")

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
      if ($r.StatusCode -eq 200 -and $r.Content.TrimStart().StartsWith("{")) {
        $running = ($r.Content | ConvertFrom-Json).version
        if ($ExpectVersion -and $running -ne $ExpectVersion) {
          Say "Server is up but runs '$running'; waiting for $ExpectVersion ..."
          Start-Sleep -Seconds 20
          continue
        }
        Say "Health OK: $($r.Content)"
        $tag = (git describe --tags --abbrev=0 2>$null)
        if (-not $ExpectVersion -and $tag -and $running -ne $tag) { Say "WARN: server runs '$running' but your latest tag is '$tag'. Is the Images run for $tag green? If so, run again with -Restart." }
        return $true
      }
    } catch { }
    Start-Sleep -Seconds 20
  }
  return $false
}

# 1. Start EC2 + RDS (no-op if already running).
Say "Starting the demo (RDS then EC2) if stopped..."
& "$PSScriptRoot\demo.ps1" start *>&1 | Tee-Object -FilePath $Log -Append
$env:AWS_PROFILE = $AwsProfile
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"   # Arabic/Hindi replies print on a cp1252 console

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
$summary = @()
foreach ($check in "check_phase4.py", "check_chat.py", "check_dashboard.py", "check_knowledge.py", "check_agent_live.py") {
  Say "=== $check ==="
  python "scripts\$check" *>&1 | Tee-Object -FilePath $Log -Append
  Say "exit code $LASTEXITCODE"
  $summary += "{0,-22} {1}" -f $check, $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" })
}

# 6. Phase C evals: local, on your copy of the data room (no AWS, no model).
Say "=== run_evals.py (local) ==="
python "scripts\run_evals.py" --record *>&1 | Tee-Object -FilePath $Log -Append
$summary += "{0,-22} {1}" -f "run_evals.py", $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" })
Say "Summary:"
$summary | ForEach-Object { Say "  $_" }
Say "Done. Log: $Log"
if ($summary | Where-Object { $_ -match "FAIL$" }) { exit 1 }
exit 0
