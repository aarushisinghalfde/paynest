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
# The server is found by its Name tag, so a replaced instance (new id) needs no script change.
$InstanceId = (aws ec2 describe-instances --region ap-southeast-2 --profile payce-fde `
  --filters "Name=tag:Name,Values=paynest-demo-server" "Name=instance-state-name,Values=pending,running,stopping,stopped" `
  --query "Reservations[0].Instances[0].InstanceId" --output text)
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
  # Pull and recreate the containers directly. "systemctl restart" alone could leave the old
  # container running: the containers restart themselves (unless-stopped), so when the unit was
  # already failed, a failing pull went unnoticed and the old version kept answering.
  Say "Pulling the new images and restarting the app on $InstanceId ..."
  $script = 'set -e; cd /opt/paynest; set -a; . ./settings; set +a; ./fetch-env.sh; ' +
    'aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"; ' +
    'docker compose pull; docker compose up -d --remove-orphans; systemctl reset-failed paynest || true; ' +
    'docker compose images; docker compose ps'
  $paramFile = Join-Path $env:TEMP "paynest-restart.json"
  [IO.File]::WriteAllText($paramFile, (@{ commands = @($script) } | ConvertTo-Json -Compress))
  $cmdId = aws ssm send-command --region $Region --instance-ids $InstanceId --document-name AWS-RunShellScript `
    --parameters "file://$paramFile" --query "Command.CommandId" --output text
  $ErrorActionPreference = "Continue"
  $until = (Get-Date).AddMinutes(15)
  do {  # the pull can take a few minutes; "aws ssm wait" gives up after ~100 s
    Start-Sleep -Seconds 10
    $inv = aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --output json 2>$null | ConvertFrom-Json
  } while ((-not $inv -or $inv.Status -in @("Pending", "InProgress", "Delayed")) -and (Get-Date) -lt $until)
  $ErrorActionPreference = "Stop"
  $inv.StandardOutputContent | Tee-Object -FilePath $Log -Append
  if ($inv.Status -ne "Success") {
    Say "FAIL: restart on the server ended '$($inv.Status)':"
    $inv.StandardErrorContent | Tee-Object -FilePath $Log -Append
    exit 1
  }
  Start-Sleep -Seconds 20
}

# The few packages the check scripts and the evals need on the laptop (the app's own list is
# requirements.txt, inside the Docker image). Quick when already installed.
python -m pip install -q --disable-pip-version-check "boto3[crt]" pyyaml python-dotenv scikit-learn *>&1 | Tee-Object -FilePath $Log -Append

# 3. Wait for the app.
Say "Waiting for health (up to 15 min)..."
if (-not (Wait-Healthy 15)) { Say "FAIL: app never became healthy. Stopping here."; exit 1 }

# 4. ADMIN_TOKEN from .env (read only).
$tokenLine = Get-Content ".env" -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
if ($tokenLine) { $env:ADMIN_TOKEN = ($tokenLine -split '=', 2)[1].Trim().Trim('"') } else { Say "WARN: ADMIN_TOKEN not found in .env" }
$leadLine = Get-Content ".env" -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*LEAD_TOKEN\s*=' } | Select-Object -First 1
if ($leadLine) { $env:LEAD_TOKEN = ($leadLine -split '=', 2)[1].Trim().Trim('"') }

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
# 7. Phase D/E checks, when their infrastructure exists (skipped, not failed, before the stacks are applied).
$ErrorActionPreference = "Continue"
$null = aws cloudformation describe-stacks --region $Region --stack-name paynest-demo-agentcore 2>$null
if ($LASTEXITCODE -eq 0) {
  Say "=== check_agentcore.py ==="
  python "scripts\check_agentcore.py" *>&1 | Tee-Object -FilePath $Log -Append
  $summary += "{0,-22} {1}" -f "check_agentcore.py", $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" })
} else { $summary += "{0,-22} {1}" -f "check_agentcore.py", "skipped (stack not applied)" }
Say "=== check_traces.py ==="
python "scripts\check_traces.py" *>&1 | Tee-Object -FilePath $Log -Append
$summary += "{0,-22} {1}" -f "check_traces.py", $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (needs the iam + ec2 updates)" })

# 8. Evidence: the latest result of every gate into docs/PROJECT_STATE.md.
python "scripts\evidence.py" *>&1 | Tee-Object -FilePath $Log -Append
Say "Summary:"
$summary | ForEach-Object { Say "  $_" }
Say "Done. Log: $Log"
if ($summary | Where-Object { $_ -match "FAIL$" }) { exit 1 }
exit 0
