# Launch in a separate interactive window without changing the caller's location.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $projectRoot '.venv\Scripts\mythread.exe'

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    Write-Host 'myThread is not installed in this worktree. Run these commands first:' -ForegroundColor Yellow
    Write-Host '  python -m venv .venv'
    Write-Host '  .\.venv\Scripts\python.exe -m pip install -e .'
    Write-Host '  .\.venv\Scripts\python.exe -m playwright install chromium'
    exit 1
}

function ConvertTo-PowerShellLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

$argumentLiterals = @($args | ForEach-Object { ConvertTo-PowerShellLiteral $_ })
$launchCommand = "Set-Location -LiteralPath $(ConvertTo-PowerShellLiteral $projectRoot)`r`n"
$launchCommand += "& $(ConvertTo-PowerShellLiteral $entryPoint) " + ($argumentLiterals -join ' ')
$encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($launchCommand))
$powerShell = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if (-not $powerShell) {
    $powerShell = Join-Path $PSHOME 'powershell.exe'
}

Start-Process -FilePath $powerShell -WorkingDirectory $projectRoot -WindowStyle Normal `
    -ArgumentList @('-NoProfile', '-NoExit', '-EncodedCommand', $encodedCommand) | Out-Null
