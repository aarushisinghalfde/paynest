<#
  One command for CloudFormation, so the AWS setup is never typed by hand.

  Usage (from the repo root; run ONE command at a time):
    .\scripts\cfn.ps1 validate network     # check the template
    .\scripts\cfn.ps1 plan network         # create a change set and show it (changes nothing)
    .\scripts\cfn.ps1 apply network        # run the change set you just reviewed
    .\scripts\cfn.ps1 output network       # show the stack outputs
    .\scripts\cfn.ps1 events network       # show recent failures, if a deploy failed
    .\scripts\cfn.ps1 delete network       # delete the stack (asks you to type its name)

  Stacks, in deploy order: network, security (more follow in phase 2).

  Stack "network" uses infra\cfn\network.yaml and is called paynest-demo-network.
  -Target india or uae uses the placeholder params; the templates refuse to deploy them.

  Every run: clears stale exported AWS_* keys, uses the payce-fde profile (signs in if
  the session expired) and refuses to continue unless the account is 665651551863.
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("validate", "plan", "apply", "output", "events", "delete")]
  [string]$Action = "plan",

  [Parameter(Position = 1)]
  [string]$Stack = "network",

  [ValidateSet("demo", "india", "uae")]
  [string]$Target = "demo"
)

$ErrorActionPreference = "Stop"
$AwsProfile = "payce-fde"     # not $Profile: that name is reserved by PowerShell
$Account = "665651551863"
$Project = "paynest"

function Invoke-Native {
  # Run a command and stop if it fails (PowerShell does not stop on native errors by itself).
  param([string]$Exe, [string[]]$Arguments)
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function Get-Text {
  # Run an aws command and return its text output; $null if it fails.
  param([string[]]$Arguments)
  $ErrorActionPreference = "Continue"
  $out = & aws @Arguments 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  return ($out -join "`n").Trim()
}

# --- Files and names ---------------------------------------------------------------
$cfnDir = Join-Path $PSScriptRoot "..\infra\cfn"
$template = (Resolve-Path (Join-Path $cfnDir "$Stack.yaml")).Path
$config = Get-Content (Join-Path $cfnDir "params\$Target.json") -Raw | ConvertFrom-Json
$region = $config.region
$stackName = "$Project-$Target-$Stack"
$common = @("--stack-name", $stackName, "--region", $region)

# --- AWS sign-in and account check ---------------------------------------------------
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN, Env:AWS_CREDENTIAL_EXPIRATION -ErrorAction SilentlyContinue
$env:AWS_PROFILE = $AwsProfile
$id = Get-Text @("sts", "get-caller-identity", "--query", "Account", "--output", "text")
if (-not $id) {
  Write-Host "AWS session expired; signing in..." -ForegroundColor Yellow
  Invoke-Native aws @("login", "--profile", $AwsProfile, "--remote")
  $id = Get-Text @("sts", "get-caller-identity", "--query", "Account", "--output", "text")
}
if ($id -ne $Account) { throw "Signed in to account '$id', expected $Account. Stopping." }
Write-Host "AWS account $id | stack $stackName | region $region" -ForegroundColor Green

function Get-PendingChangeSet {
  $name = Get-Text (@("cloudformation", "list-change-sets") + $common + @(
      "--query", "reverse(sort_by(Summaries[?ExecutionStatus=='AVAILABLE'], &CreationTime))[0].ChangeSetName",
      "--output", "text"))
  if (-not $name -or $name -eq "None") { return $null }
  return $name
}

function Resolve-ParamValue {
  # "auto:..." values are looked up in AWS, so the params files hold no IDs that differ by region.
  param([string]$Value)
  if ($Value -eq "auto:cloudfront") {
    $id = Get-Text @("ec2", "describe-managed-prefix-lists", "--region", $region,
      "--filters", "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing",
      "--query", "PrefixLists[0].PrefixListId", "--output", "text")
    if (-not $id -or $id -eq "None") { throw "Could not find the CloudFront prefix list in $region." }
    Write-Host "CloudFront origin-facing prefix list in ${region}: $id" -ForegroundColor DarkGray
    return $id
  }
  return $Value
}

function Get-StackStatus {
  return Get-Text (@("cloudformation", "describe-stacks") + $common + @("--query", "Stacks[0].StackStatus", "--output", "text"))
}

function Show-Failures {
  Invoke-Native aws (@("cloudformation", "describe-stack-events") + $common + @(
      "--query", "StackEvents[?contains(ResourceStatus, 'FAILED')] | [0:15].{Time:Timestamp,Resource:LogicalResourceId,Status:ResourceStatus,Reason:ResourceStatusReason}",
      "--output", "table", "--no-cli-pager"))
}

switch ($Action) {
  "validate" {
    $lint = Join-Path $PSScriptRoot "..\.venv\Scripts\cfn-lint.exe"
    if (Test-Path $lint) {
      Invoke-Native $lint @($template)
      Write-Host "cfn-lint: no problems found." -ForegroundColor Green
    }
    else {
      Write-Host "(cfn-lint not installed; using AWS's basic check)" -ForegroundColor Yellow
      Invoke-Native aws @("cloudformation", "validate-template", "--template-body", "file://$template",
        "--region", $region, "--query", "Description", "--output", "text", "--no-cli-pager")
    }
  }

  "plan" {
    # Pass only the parameters this template declares, plus Env from -Target.
    $declared = (Get-Text @("cloudformation", "validate-template", "--template-body", "file://$template",
        "--region", $region, "--query", "Parameters[].ParameterKey", "--output", "text")) -split "\s+"
    $overrides = @()
    if ($declared -contains "Env") { $overrides += "Env=$Target" }
    foreach ($p in $config.parameters.PSObject.Properties) {
      if ($declared -contains $p.Name) { $overrides += "$($p.Name)=$(Resolve-ParamValue $p.Value)" }
    }

    $deployArgs = @("cloudformation", "deploy", "--template-file", $template) + $common + @(
      "--tags", "Project=$Project", "Env=$Target", "ManagedBy=cloudformation",
      "--capabilities", "CAPABILITY_NAMED_IAM",
      "--no-execute-changeset", "--no-fail-on-empty-changeset")
    if ($overrides.Count -gt 0) { $deployArgs += @("--parameter-overrides") + $overrides }
    Invoke-Native aws $deployArgs

    $cs = Get-PendingChangeSet
    if (-not $cs) { Write-Host "No changes: the stack already matches the template." -ForegroundColor Green; break }
    Write-Host "`nChange set $cs (nothing has changed yet):" -ForegroundColor Cyan
    Invoke-Native aws (@("cloudformation", "describe-change-set", "--change-set-name", $cs) + $common + @(
        "--query", "Changes[].ResourceChange.{Action:Action,Resource:LogicalResourceId,Type:ResourceType,Replace:Replacement}",
        "--output", "table", "--no-cli-pager"))
    Write-Host "Review it, then run: .\scripts\cfn.ps1 apply $Stack" -ForegroundColor Cyan
  }

  "apply" {
    $cs = Get-PendingChangeSet
    if (-not $cs) { throw "No change set to apply. Run: .\scripts\cfn.ps1 plan $Stack" }
    Invoke-Native aws (@("cloudformation", "execute-change-set", "--change-set-name", $cs) + $common)
    Write-Host "Applying $cs ..." -ForegroundColor Cyan
    do {
      Start-Sleep -Seconds 5
      $status = Get-StackStatus
      Write-Host "  $status"
    } while ($status -like "*_IN_PROGRESS")
    if ($status -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE")) {
      Show-Failures
      throw "Stack ended in $status. CloudFormation rolled back; the table above shows why."
    }
    Write-Host "Done: $status" -ForegroundColor Green
    Invoke-Native aws (@("cloudformation", "describe-stacks") + $common + @(
        "--query", "Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}", "--output", "table", "--no-cli-pager"))
  }

  "output" {
    Invoke-Native aws (@("cloudformation", "describe-stacks") + $common + @(
        "--query", "Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}", "--output", "table", "--no-cli-pager"))
  }

  "events" { Show-Failures }

  "delete" {
    $answer = Read-Host "Type the stack name ($stackName) to delete it"
    if ($answer -ne $stackName) { Write-Host "Not deleted." -ForegroundColor Yellow; break }
    Invoke-Native aws (@("cloudformation", "delete-stack") + $common)
    Write-Host "Deleting $stackName ..." -ForegroundColor Cyan
    Invoke-Native aws (@("cloudformation", "wait", "stack-delete-complete") + $common)
    Write-Host "Deleted." -ForegroundColor Green
  }
}
