# MiniAI nightly self-check: quiet (nightly) suite on the production model.
# Writes logs/selfcheck_latest.json + one line to logs/selfcheck_history.log.
# Registered as a Scheduled Task (03:17 only, idle 10 min, don't wake, no catch-up).

# Native stderr noise must not abort the run.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

$model = $env:MINIAI_MODEL
if (-not $model) { $model = "Qwen3-30B-A3B-GGUF" }

# Hidden window: -WindowStyle Hidden on the scheduled action; CREATE_NO_WINDOW
# inside scripts/run_selfcheck.py for the eval child.
& $Python -m scripts.run_selfcheck --mode nightly --model $model
$rc = $LASTEXITCODE
exit $rc
