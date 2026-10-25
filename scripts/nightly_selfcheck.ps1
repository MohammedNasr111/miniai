# MiniAI nightly self-check: quick suite on the production model.
# Writes logs/selfcheck_latest.json. Registered as a Scheduled Task (03:17,
# idle 10 min, don't wake PC, current user, no elevation).

# Native stderr noise (e.g. ctypes "Exception ignored") must not abort the run.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$OutJson = Join-Path $Root "logs\selfcheck_latest.json"
$OutLog = Join-Path $Logs ("selfcheck_" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

$started = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$model = $env:MINIAI_MODEL
if (-not $model) { $model = "Qwen3-30B-A3B-GGUF" }

# Run eval; capture exit code even if stderr writes native warnings.
cmd /c "`"$Python`" -m eval.run --suite quick --model $model > `"$OutLog`" 2>&1"
$rc = $LASTEXITCODE
Get-Content -Path $OutLog -ErrorAction SilentlyContinue | Write-Host

# Parse newest eval_*.json written by eval.run
$evalFiles = Get-ChildItem -Path $Logs -Filter "eval_*.json" | Sort-Object LastWriteTime -Descending
$passed = 0
$total = 0
$failed = 0
$safety = "unknown"
$evalPath = $null
if ($evalFiles) {
  $evalPath = $evalFiles[0].FullName
  try {
    $data = Get-Content -Raw -Path $evalPath | ConvertFrom-Json
    $results = @()
    if ($data.results) { $results = $data.results }
    elseif ($data.tasks) { $results = $data.tasks }
    $total = @($results).Count
    $passed = @($results | Where-Object { $_.pass -eq $true }).Count
    $failed = @($results | Where-Object { $_.pass -eq $false }).Count
    if ($data.safety) { $safety = [string]$data.safety }
    elseif ($data.safety_headline) { $safety = [string]$data.safety_headline }
  } catch {
    # leave zeros
  }
}

$payload = [ordered]@{
  date      = (Get-Date -Format "yyyy-MM-dd")
  started   = $started
  finished  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
  model     = $model
  passed    = $passed
  failed    = $failed
  total     = $total
  safety    = $safety
  exit_code = $rc
  eval_json = $evalPath
  log       = $OutLog
}
($payload | ConvertTo-Json -Depth 4) | Set-Content -Path $OutJson -Encoding UTF8

# Rotate logs after the run
& $Python -c "from config.log_rotation import rotate_logs; print(rotate_logs())" *>> $OutLog

exit $rc
