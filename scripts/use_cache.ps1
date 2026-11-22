<#
  Switch the app's Redis between ElastiCache Valkey (in the VPC, Sydney) and Upstash (plan v2 phase D).

  Usage (from the repo root):
    .\scripts\cfn.ps1 plan cache ; .\scripts\cfn.ps1 apply cache    # once: create the Valkey cache (~10 min)
    .\scripts\use_cache.ps1 valkey     # point the app at Valkey, restart, check /api/ready
    .\scripts\use_cache.ps1 upstash    # back to Upstash (e.g. before deleting the cache stack)
    .\scripts\use_cache.ps1 status     # which one the running app uses

  How: the app reads REDIS_URL from SSM /paynest/demo/REDIS_URL at start. The first switch to
  Valkey copies the current (Upstash) value to /paynest/demo/REDIS_URL_UPSTASH so it can be put
  back. Values are never printed, and .env is not touched. Valkey has no password: it is reachable
  only from the app server's security group, with TLS (rediss://).
  Cost: cache.t4g.micro, roughly USD 0.02 an hour while the stack exists.
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("valkey", "upstash", "status")]
  [string]$Use = "status"
)

$ErrorActionPreference = "Stop"
$AwsProfile = "payce-fde"
$Account = "665651551863"
$Region = "ap-southeast-2"
$InstanceId = "i-038b0f4a1eee1c90e"
$Param = "/paynest/demo/REDIS_URL"
$Backup = "/paynest/demo/REDIS_URL_UPSTASH"
$KeyAlias = "alias/paynest-demo"
$Ready = "https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/api/ready"

function Get-Text([string[]]$Arguments) {
  $ErrorActionPreference = "Continue"
  $out = & aws @Arguments 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  return ($out -join "`n").Trim()
}
function Put-Secret([string]$Name, [string]$Value) {
  aws ssm put-parameter --region $Region --name $Name --type SecureString --key-id $KeyAlias `
    --value $Value --overwrite --no-cli-pager --output text --query "Version" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to store $Name" }
}
function Show-Ready {
  try {
    $r = Invoke-WebRequest -Uri $Ready -UseBasicParsing -TimeoutSec 15
    $redis = ($r.Content | ConvertFrom-Json).checks.redis
    Write-Host "redis: $($redis.detail)"
    return $redis.detail
  } catch { Write-Host "app not ready yet"; return "" }
}

Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
$env:AWS_PROFILE = $AwsProfile
$id = Get-Text @("sts", "get-caller-identity", "--query", "Account", "--output", "text")
if (-not $id) { aws login --profile $AwsProfile --remote; $id = Get-Text @("sts", "get-caller-identity", "--query", "Account", "--output", "text") }
if ($id -ne $Account) { throw "Signed in to account '$id', expected $Account. Stopping." }

if ($Use -eq "status") { $null = Show-Ready; exit 0 }

$current = Get-Text @("ssm", "get-parameter", "--region", $Region, "--name", $Param, "--with-decryption", "--query", "Parameter.Value", "--output", "text")
if ($Use -eq "valkey") {
  $url = Get-Text @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", "paynest-demo-cache",
    "--query", "Stacks[0].Outputs[?OutputKey=='RedisUrl'].OutputValue", "--output", "text")
  if (-not $url) { throw "Stack paynest-demo-cache not found. Run: .\scripts\cfn.ps1 plan cache, then apply cache." }
  if ($current -and $current -notmatch "cache\.amazonaws\.com") {
    $saved = Get-Text @("ssm", "get-parameter", "--region", $Region, "--name", $Backup, "--query", "Parameter.Name", "--output", "text")
    if (-not $saved) { Put-Secret $Backup $current; Write-Host "Saved the current Upstash URL to $Backup" }
  }
  Put-Secret $Param $url
  $want = "ElastiCache Valkey"
} else {
  $old = Get-Text @("ssm", "get-parameter", "--region", $Region, "--name", $Backup, "--with-decryption", "--query", "Parameter.Value", "--output", "text")
  if (-not $old) { throw "$Backup not found: nothing to restore. Run .\scripts\put_secrets.ps1 with REDIS_URL in .env instead." }
  Put-Secret $Param $old
  $want = "Upstash"
}
Write-Host "REDIS_URL now points at $want. Restarting the app..."
aws ssm send-command --region $Region --instance-ids $InstanceId --document-name AWS-RunShellScript `
  --parameters "commands=['systemctl restart paynest']" --no-cli-pager --output text --query "Command.CommandId" | Out-Null
$deadline = (Get-Date).AddMinutes(8)
do {
  Start-Sleep -Seconds 20
  $detail = Show-Ready
} while (($detail -notmatch [regex]::Escape($want)) -and (Get-Date) -lt $deadline)
if ($detail -match [regex]::Escape($want)) { Write-Host "PASS  cache_switch: app uses $want" -ForegroundColor Green; exit 0 }
Write-Host "FAIL  cache_switch: app does not report $want on /api/ready after 8 min" -ForegroundColor Red
exit 1
