$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in an Administrator PowerShell (same Windows account).'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$certScript = Join-Path $PSScriptRoot 'create_local_cert.py'
$toolsDir = Join-Path $projectRoot '.tools'
$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$hostsText = Get-Content -LiteralPath $hostsPath -Raw
$entries = $hostsText -split "`r?`n" | Where-Object { ($_ -split '#')[0] -match '(^|\s)threads-sample\.meta(\s|$)' }
foreach ($entry in $entries) {
    if ($entry -notmatch '^\s*127\.0\.0\.1\s') {
        throw 'threads-sample.meta already maps to another address. Resolve the hosts entry first.'
    }
}
if (-not $entries) {
    try {
        # Check write access before generating or trusting a certificate; do not modify the file.
        $hostsHandle = [System.IO.File]::Open($hostsPath, 'Open', 'Write', 'ReadWrite')
        $hostsHandle.Dispose()
    } catch {
        throw "Cannot write hosts: $hostsPath. Existing certificates were left unchanged. Check Windows/security software restrictions; do not disable protection. An administrator can add: 127.0.0.1 threads-sample.meta. Then rerun this script. Original error: $($_.Exception.Message)"
    }
}
$certPath = Join-Path $toolsDir 'callback-cert.cer'
$pemPath = Join-Path $toolsDir 'callback-cert.pem'
$keyPath = Join-Path $toolsDir 'callback-key.pem'
$reuseCertificate = $false
if ((Test-Path -LiteralPath $certPath) -and (Test-Path -LiteralPath $pemPath) -and (Test-Path -LiteralPath $keyPath)) {
    try {
        $existingCertificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certPath)
        $reuseCertificate = ($existingCertificate.Subject -eq 'CN=threads-sample.meta') -and ($existingCertificate.NotBefore -le (Get-Date)) -and ($existingCertificate.NotAfter -gt (Get-Date).AddDays(1))
        $existingCertificate.Dispose()
    } catch { $reuseCertificate = $false }
}
if ($reuseCertificate) {
    Write-Output 'Reusing existing local HTTPS certificate.'
} else {
    & $pythonExe $certScript
    if ($LASTEXITCODE -ne 0) { throw 'Certificate generation failed.' }
}
$keyPath = Join-Path $toolsDir 'callback-key.pem'
$keyAcl = Get-Acl -LiteralPath $keyPath
$keyAcl.SetAccessRuleProtection($true, $false)
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new($identity.Name, 'FullControl', 'Allow')
$keyAcl.AddAccessRule($rule)
Set-Acl -LiteralPath $keyPath -AclObject $keyAcl
Import-Certificate -FilePath $certPath -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
if (-not $entries) {
    Add-Content -LiteralPath $hostsPath -Value "`r`n127.0.0.1 threads-sample.meta # myThread local OAuth" -Encoding ASCII
}
Write-Output 'Configured localhost hostname and trusted leaf certificate (30 days, current Windows user only).'
Write-Output 'Meta callback URL: https://threads-sample.meta:8765/callback'
Write-Output 'Next: .\.venv\Scripts\mythread.exe login --local-https --search --discovery'
