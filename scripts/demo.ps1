<#
  Start, stop or check the paid parts of the demo (EC2 + RDS), so they only run (and
  bill by the hour) while you are working or presenting.

  Usage (from the repo root):
    .\scripts\demo.ps1 status
    .\scripts\demo.ps1 start    # RDS first (about 5 to 10 min), then EC2; app is up a few minutes later
    .\scripts\demo.ps1 stop     # stops EC2, then RDS; storage and the Elastic IP still bill a little

  Notes:
  - AWS restarts a stopped RDS instance by itself after 7 days. Run "stop" again if that happens.
  - Starting does not change anything else: CloudFront, S3, SQS, KMS and secrets stay as they are.
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("status", "start", "stop")]
  [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$AwsProfile = "payce-fde"
$Account = "665651551863"
$Region = "ap-southeast-2"
$DbId = "paynest-demo-db"
$ServerName = "paynest-demo-server"

function Get-Text {
  param([string[]]$Arguments)
  $ErrorActionPreference = "Continue"
  $out = & aws @Arguments 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  return ($out -join "`n").Trim()
}

# Same sign-in and account check as cfn.ps1.
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN, Env:AWS_CREDENTIAL_EXPIRATION -ErrorAction SilentlyContinue
$env:AWS_PROFILE = $AwsProfile
$id = Get-Text @("sts", "get-caller-identity", "--query", "Account", "--output", "text")
if (-not $id) {
  aws login --profile $AwsProfile --remote
  $id = Get-Text @("sts", "get-caller-identity", "--query", "Account", "--output", "text")
}
if ($id -ne $Account) { throw "Signed in to account '$id', expected $Account. Stopping." }

$instanceId = Get-Text @("ec2", "describe-instances", "--region", $Region,
  "--filters", "Name=tag:Name,Values=$ServerName", "Name=instance-state-name,Values=pending,running,stopping,stopped",
  "--query", "Reservations[0].Instances[0].InstanceId", "--output", "text")
if ($instanceId -eq "None") { $instanceId = $null }

function Get-DbState { Get-Text @("rds", "describe-db-instances", "--region", $Region, "--db-instance-identifier", $DbId, "--query", "DBInstances[0].DBInstanceStatus", "--output", "text") }
function Get-Ec2State { if ($instanceId) { Get-Text @("ec2", "describe-instances", "--region", $Region, "--instance-ids", $instanceId, "--query", "Reservations[0].Instances[0].State.Name", "--output", "text") } }

function Show-Status {
  $db = Get-DbState; $ec2 = Get-Ec2State
  Write-Host ("RDS {0,-20} {1}" -f $DbId, $(if ($db) { $db } else { "not deployed" }))
  Write-Host ("EC2 {0,-20} {1}" -f $ServerName, $(if ($ec2) { "$ec2 ($instanceId)" } else { "not deployed" }))
}

switch ($Action) {
  "status" { Show-Status }

  "start" {
    if ((Get-DbState) -eq "stopped") {
      Write-Host "Starting RDS (about 5 to 10 minutes)..." -ForegroundColor Cyan
      aws rds start-db-instance --region $Region --db-instance-identifier $DbId --no-cli-pager | Out-Null
    }
    Write-Host "Waiting for RDS to be available..."
    aws rds wait db-instance-available --region $Region --db-instance-identifier $DbId
    if ($instanceId -and (Get-Ec2State) -eq "stopped") {
      Write-Host "Starting EC2..." -ForegroundColor Cyan
      aws ec2 start-instances --region $Region --instance-ids $instanceId --no-cli-pager | Out-Null
      aws ec2 wait instance-running --region $Region --instance-ids $instanceId
    }
    Show-Status
    Write-Host "The app comes up a few minutes after EC2 is running (the paynest service pulls images and starts compose)." -ForegroundColor Green
  }

  "stop" {
    if ($instanceId -and (Get-Ec2State) -eq "running") {
      Write-Host "Stopping EC2..." -ForegroundColor Cyan
      aws ec2 stop-instances --region $Region --instance-ids $instanceId --no-cli-pager | Out-Null
      aws ec2 wait instance-stopped --region $Region --instance-ids $instanceId
    }
    if ((Get-DbState) -eq "available") {
      Write-Host "Stopping RDS (it finishes in the background)..." -ForegroundColor Cyan
      aws rds stop-db-instance --region $Region --db-instance-identifier $DbId --no-cli-pager | Out-Null
    }
    Show-Status
    Write-Host "Stopped: EC2 and RDS no longer bill per hour (disk, storage and Elastic IP still do, a few cents a day)." -ForegroundColor Green
  }
}
