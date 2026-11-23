<#
  The CI checks, on your laptop, before anything is pushed (deploy.ps1 runs this first).
    .\scripts\precheck.ps1          # ruff, pytest, web build
  Same commands as .github/workflows/CI.yml. Tests whose packages are missing locally are skipped
  by pytest; the list is printed so you know CI will run them. The first run installs what the tests
  need from requirements.txt, except the heavy PII models (Presidio, spaCy) and the web server.
  Exit code 0 only if every check that could run passed.
#>
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
$failed = @()
function Step($msg) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor Cyan }

# Use the repo's .venv when there is one (that is where the packages are), else the active python.
$py = if (Test-Path ".venv\Scripts\python.exe") { (Resolve-Path ".venv\Scripts\python.exe").Path } else { "python" }
Step "Python: $py"
& $py -c "import pytest, fastapi, httpx, sklearn, langgraph, yaml, opentelemetry.sdk, ruff" *> $null
if ($LASTEXITCODE -ne 0) {
  Step "Installing the test packages (once)"
  $req = Join-Path $env:TEMP "paynest-precheck-req.txt"
  Get-Content requirements.txt | Where-Object { $_ -notmatch '^\s*(presidio|spacy|en_core_web_sm|uvicorn)' } | Set-Content $req
  & $py -m pip install -q --disable-pip-version-check -r $req
  if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed (see above)." -ForegroundColor Red; exit 1 }
}

Step "ruff check ."
& $py -m ruff check .
if ($LASTEXITCODE -ne 0) { $failed += "ruff" }

Step "pytest"
& $py -m pytest -q -rfEs --no-header -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { $failed += "pytest" }

if (Test-Path "web\node_modules") {
  Step "web build"
  Push-Location web; npm run build --silent; if ($LASTEXITCODE -ne 0) { $failed += "web build" }; Pop-Location
} else { Step "web build skipped (run 'npm install' in web\ once to include it)" }

if ($failed) { Write-Host "PRECHECK FAILED: $($failed -join ', '). Nothing was pushed." -ForegroundColor Red; exit 1 }
Write-Host "PRECHECK PASS (skipped tests above run in CI)" -ForegroundColor Green
exit 0
