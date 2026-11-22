<#
  Copies secrets from .env into AWS SSM Parameter Store as encrypted SecureStrings,
  so the EC2 can read them at start-up and no secret is ever typed, pasted or committed.

  Usage (from the repo root):
    .\scripts\put_secrets.ps1

  Writes (encrypted with alias/paynest-demo, overwriting older values):
    /paynest/demo/REDIS_URL
    /paynest/demo/OPENROUTER_API_KEY
    /paynest/demo/PII_HMAC_KEY
    /paynest/demo/ADMIN_TOKEN
    /paynest/demo/LEAD_TOKEN      (optional: read-only console for the support lead)
  Values are never printed. Re-run it whenever you change a value in .env.
#>
param(
  [ValidateSet("demo")]
  [string]$Target = "demo"
)

$ErrorActionPreference = "Stop"
$AwsProfile = "payce-fde"
$Account = "665651551863"
$Region = "ap-southeast-2"
$KeyAlias = "alias/paynest-$Target"
$Names = @("REDIS_URL", "OPENROUTER_API_KEY", "PII_HMAC_KEY", "ADMIN_TOKEN", "LEAD_TOKEN")

# Same sign-in and account check as cfn.ps1.
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN, Env:AWS_CREDENTIAL_EXPIRATION -ErrorAction SilentlyContinue
$env:AWS_PROFILE = $AwsProfile
$ErrorActionPreference = "Continue"
$id = aws sts get-caller-identity --query Account --output text 2>$null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) {
  aws login --profile $AwsProfile --remote
  $id = aws sts get-caller-identity --query Account --output text
}
if ($id -ne $Account) { throw "Signed in to account '$id', expected $Account. Stopping." }

# Read .env: KEY=VALUE lines, ignoring comments and blank lines.
$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) { throw ".env not found at $envFile" }
$values = @{}
foreach ($line in Get-Content $envFile) {
  if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
    $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
  }
}

foreach ($name in $Names) {
  $value = $values[$name]
  if ([string]::IsNullOrWhiteSpace($value)) {
    Write-Host "SKIP  $name (empty in .env)" -ForegroundColor Yellow
    continue
  }
  $param = "/paynest/$Target/$name"
  aws ssm put-parameter --region $Region --name $param --type SecureString `
    --key-id $KeyAlias --value $value --overwrite --no-cli-pager --output text --query "Version" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to store $param" }
  Write-Host "OK    $param (encrypted with $KeyAlias)" -ForegroundColor Green
}
