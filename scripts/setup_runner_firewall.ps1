#Requires -Version 5.1
<#
.SYNOPSIS
  Create or remove the MiniAI code-runner outbound firewall rule.

.DESCRIPTION
  Run this script yourself as Administrator (Cursor will not elevate it).
  Creates ONE outbound block rule for the runner-venv python.exe only.

.PARAMETER Remove
  Remove the rule instead of creating it.
#>
param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$RuleName = "MiniAI code runner - block internet"
# Dedicated copy used by MiniAI (not the Windows venv launcher stub).
$Python = Join-Path $env:LOCALAPPDATA "MiniAI\runner-venv\runner-bin\python.exe"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Host "ERROR: Run this script from an elevated PowerShell (Run as administrator)."
    exit 1
}

if ($Remove) {
    $existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "No rule named '$RuleName' found. Nothing to remove."
        exit 0
    }
    Write-Host "Will REMOVE firewall rule:"
    Write-Host "  DisplayName: $RuleName"
    $answer = Read-Host "Remove this rule? (yes/no)"
    if ($answer -ne "yes") {
        Write-Host "Cancelled."
        exit 0
    }
    Remove-NetFirewallRule -DisplayName $RuleName
    Write-Host "Removed."
    exit 0
}

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "ERROR: Runner Python not found at:"
    Write-Host "  $Python"
    Write-Host "Create the venv first: python -m venv `%LOCALAPPDATA%\MiniAI\runner-venv"
    exit 1
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Rule already exists: $RuleName"
    Get-NetFirewallRule -DisplayName $RuleName | Format-List DisplayName, Enabled, Direction, Action
    exit 0
}

Write-Host "Exact rule to create:"
Write-Host "  DisplayName : $RuleName"
Write-Host "  Direction   : Outbound"
Write-Host "  Action      : Block"
Write-Host "  Program     : $Python"
Write-Host ""
$answer = Read-Host "Create this rule? (yes/no)"
if ($answer -ne "yes") {
    Write-Host "Cancelled. No rule created."
    exit 0
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Outbound `
    -Action Block `
    -Program $Python `
    -Enabled True | Out-Null

Write-Host "Created rule '$RuleName'."
Get-NetFirewallRule -DisplayName $RuleName | Format-List DisplayName, Enabled, Direction, Action
