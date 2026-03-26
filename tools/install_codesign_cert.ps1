# install_codesign_cert.ps1
# Run on each target machine (as Administrator) to trust the self-signed cert.
# After this, the signed EXE will not show a SmartScreen warning on that machine.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\install_codesign_cert.ps1

$PfxPath = "$PSScriptRoot\tsm_codesign.pfx"

if (-not (Test-Path $PfxPath)) {
    Write-Error "PFX not found at: $PfxPath"
    Write-Host "Run tools\create_codesign_cert.ps1 first on your dev machine, then copy the PFX here."
    exit 1
}

Write-Host "`n=== Installing code-signing certificate ===" -ForegroundColor Cyan

$password = Read-Host "Enter the PFX password" -AsSecureString

# Import into Personal store so signtool can use it
Import-PfxCertificate -FilePath $PfxPath `
    -CertStoreLocation "Cert:\LocalMachine\My" `
    -Password $password | Out-Null

# Also import the cert (public key only) into Trusted Root CA
# so Windows trusts binaries signed with it
$cert = Import-PfxCertificate -FilePath $PfxPath `
    -CertStoreLocation "Cert:\LocalMachine\Root" `
    -Password $password
Write-Host "Certificate installed: $($cert.Thumbprint)" -ForegroundColor Green

# Also add to TrustedPublisher store (removes UAC "Unknown publisher" prompt)
Import-PfxCertificate -FilePath $PfxPath `
    -CertStoreLocation "Cert:\LocalMachine\TrustedPublisher" `
    -Password $password | Out-Null
Write-Host "Added to TrustedPublisher store." -ForegroundColor Green

Write-Host "`n=== Done — signed EXEs from TireStorageManager will be trusted on this machine ===" -ForegroundColor Green
