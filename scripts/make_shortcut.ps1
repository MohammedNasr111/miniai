# Create a Desktop shortcut "MiniAI" that launches the app with no console.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    $Pythonw = Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path $Pythonw)) {
    throw "venv python not found at $Pythonw - create .venv first"
}

$IconDir = Join-Path $Root "app\design"
$IconPath = Join-Path $IconDir "miniai.ico"
New-Item -ItemType Directory -Force -Path $IconDir | Out-Null

$gen = Join-Path $Root "scripts\_gen_miniai_ico.py"
& (Join-Path $Root ".venv\Scripts\python.exe") $gen $IconPath
if (-not (Test-Path $IconPath)) { throw "icon not created: $IconPath" }

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
Write-Host "Created $LnkPath"
Write-Host "Target: $Pythonw -m app"
Write-Host "cwd: $Root"
Write-Host "icon: $IconPath"
