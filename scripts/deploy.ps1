<#
  One-command release (plan v2 phase D): tag -> images built -> restart -> right version live -> all gates.

  Usage (from the repo root, after you have committed your changes):
    .\scripts\deploy.ps1 v0.8.0

  What it does, and when it stops:
    1. Refuses if you have uncommitted changes (the tag would not contain them) or the tag already
       points at another commit.
    2. Pushes the branch and the tag. GitHub Actions then runs CI and Images for the tag.
    3. Waits (up to 25 min) until BOTH images for that tag are in ECR (paynest-demo/app and /web).
       This is what used to go wrong: restarting before the build finished ran the old :latest.
    4. Runs scripts\run_checks.ps1 -Restart -ExpectVersion <tag>: starts EC2/RDS if stopped, restarts
       the app, waits until /api/health reports the new version, then runs every live gate and the
       local evals into checks_<time>.log.
  It changes no infrastructure (no CloudFormation). Exit code 0 only if every gate passes.
#>
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidatePattern('^v\d+\.\d+\.\d+$')]
  [string]$Version
)

$ErrorActionPreference = "Stop"
$AwsProfile = "payce-fde"
$Region = "ap-southeast-2"
$Repos = @("paynest-demo/app", "paynest-demo/web")

function Test-Aws([string[]]$Arguments) {
  # True if the aws command succeeds. Errors are expected while waiting, so never stop on them.
  $ErrorActionPreference = "Continue"
  $null = & aws @Arguments 2>$null
  return ($LASTEXITCODE -eq 0)
}

function Step($msg) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor Cyan }

# 1. Clean tree, sane tag.
$dirty = git status --porcelain
if ($dirty) {
  Write-Host "Uncommitted changes; commit them first so the release contains them:" -ForegroundColor Yellow
  $dirty | Select-Object -First 15 | ForEach-Object { Write-Host "  $_" }
  exit 1
}
$head = (git rev-parse HEAD).Trim()
$ErrorActionPreference = "Continue"
$existing = git rev-parse -q --verify "refs/tags/$Version^{commit}"
$ErrorActionPreference = "Stop"
if ($existing -and $existing.Trim() -ne $head) {
  Write-Host "Tag $Version already exists on another commit ($($existing.Trim().Substring(0,8))). Use a new version." -ForegroundColor Yellow
  exit 1
}

# 2. The CI checks locally, then the branch alone, and the tag only once CI is green on that commit.
#    A failed check used to burn the version tag (v0.9.3, v0.9.4); now nothing is tagged until CI passes.
& "$PSScriptRoot\precheck.ps1"
if ($LASTEXITCODE -ne 0) { exit 1 }
Step "Pushing $(git rev-parse --abbrev-ref HEAD) ($($head.Substring(0,8))); tag $Version waits for CI"
git push
if ($LASTEXITCODE -ne 0) { throw "git push failed" }
$slug = ((git remote get-url origin) -replace '\.git$', '' -split 'github.com[:/]')[1]
$checks = "https://api.github.com/repos/$slug/commits/$head/check-runs"
$deadline = (Get-Date).AddMinutes(20)
do {
  Start-Sleep -Seconds 30
  try { $runs = (Invoke-RestMethod -Uri $checks -Headers @{ "User-Agent" = "paynest-deploy" }).check_runs } catch { $runs = @() }
  $open = @($runs | Where-Object { $_.status -ne "completed" })
  if ($runs) { Step "  CI: $($runs.Count - $open.Count)/$($runs.Count) jobs done" } else { Step "  CI: waiting for the run to start" }
} while ((-not $runs -or $open) -and (Get-Date) -lt $deadline)
$bad = @($runs | Where-Object { $_.status -eq "completed" -and $_.conclusion -notin @("success", "skipped", "neutral") })
if (-not $runs -or $open -or $bad) {
  Write-Host "CI is not green on $($head.Substring(0,8)); $Version was NOT tagged. Fix, commit, and run deploy again with the same version." -ForegroundColor Red
  $bad | ForEach-Object { Write-Host "  $($_.name): $($_.conclusion)  $($_.html_url)" -ForegroundColor Red }
  exit 1
}
Step "CI green. Tagging $Version"
if (-not $existing) { git tag $Version }
git push origin $Version
if ($LASTEXITCODE -ne 0) { throw "git push of the tag failed" }

# 3. Wait for both images in ECR.
$env:AWS_PROFILE = $AwsProfile
if (-not (Test-Aws @("sts", "get-caller-identity"))) { aws login --profile $AwsProfile --remote }
Step "Waiting for the $Version images in ECR (CI tests run first; usually 4-8 min)..."
$deadline = (Get-Date).AddMinutes(25)
$missing = $Repos
while ($missing -and (Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 30
  $missing = @($Repos | Where-Object {
      -not (Test-Aws @("ecr", "describe-images", "--region", $Region, "--repository-name", $_, "--image-ids", "imageTag=$Version"))
    })
  if ($missing) { Step "  still building: $($missing -join ', ')" }
}
if ($missing) {
  Write-Host "Images for $Version not in ECR after 25 min. Check the Actions page (a failed test stops the build)." -ForegroundColor Red
  exit 1
}
Step "Images ready."

# 4. Restart, wait for the version, run every gate.
& "$PSScriptRoot\run_checks.ps1" -Restart -ExpectVersion $Version
$code = $LASTEXITCODE
if ($code -eq 0) { Step "RELEASE ${Version}: all gates PASS" } else { Write-Host "RELEASE ${Version}: some gates FAILED (see the log)" -ForegroundColor Red }
exit $code
