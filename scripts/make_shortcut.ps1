# Create a Desktop shortcut "MiniAI" that launches the app with no console.
# Prefers scripts/make_shortcut.py (sets AppUserModel.ID). Fallback: WScript only.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $Py) {
    & $Py -m scripts.make_shortcut
    if ($LASTEXITCODE -eq 0) { exit 0 }
}
# Fallback without pywin32 property store
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) { $Pythonw = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Pythonw)) { throw "venv python not found" }
& $Py (Join-Path $Root "scripts\gen_miniai_assets.py")
$IconPath = Join-Path $Root "app\assets\miniai.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$LnkPath = Join-Path $Desktop "MiniAI.lnk"
$Wsh = New-Object -ComObject WScript.Shell
$Sc = $Wsh.CreateShortcut($LnkPath)
$Sc.TargetPath = $Pythonw
$Sc.Arguments = "-m app"
$Sc.WorkingDirectory = $Root
$Sc.WindowStyle = 1
$Sc.IconLocation = "$IconPath,0"
$Sc.Description = "MiniAI local assistant"
$Sc.Save()
Write-Host "Created $LnkPath (no AppUserModel.ID — install pywin32 for full support)"
