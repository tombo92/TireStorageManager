# create_codesign_cert.ps1
# Run ONCE on your dev machine (as Administrator) to create the self-signed
# code-signing certificate and export it as a PFX file.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1
#
# Output:
#   tools\tsm_codesign.pfx   ← add as GitHub secret CODE_SIGN_PFX_BASE64
#
# To install the cert on target machines (removes SmartScreen warning):
#   tools\install_codesign_cert.ps1

$Subject     = "CN=TireStorageManager, O=Tom Brandherm"
$PfxPath     = "$PSScriptRoot\tsm_codesign.pfx"
$StoreTarget = "Cert:\CurrentUser\My"

Write-Host "`n=== Creating self-signed code-signing certificate ===" -ForegroundColor Cyan

# Create cert in personal store
$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -CertStoreLocation $StoreTarget `
    -NotAfter (Get-Date).AddYears(10) `
    -HashAlgorithm SHA256

Write-Host "Certificate created: $($cert.Thumbprint)" -ForegroundColor Green

# Prompt for PFX password
$password = Read-Host "Enter a password for the PFX export" -AsSecureString

# Export to PFX
Export-PfxCertificate -Cert $cert -FilePath $PfxPath -Password $password | Out-Null
Write-Host "PFX saved to: $PfxPath" -ForegroundColor Green

# Print base64 for GitHub secret
Write-Host "`n=== GitHub Secret (CODE_SIGN_PFX_BASE64) ===" -ForegroundColor Cyan
Write-Host "Copy the line below and add it as a GitHub Actions secret named CODE_SIGN_PFX_BASE64:" -ForegroundColor Yellow
[Convert]::ToBase64String([IO.File]::ReadAllBytes($PfxPath)) | Write-Host

Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "Also add your PFX password as GitHub secret: CODE_SIGN_PASSWORD" -ForegroundColor Yellow
Write-Host "To distribute trust, run: tools\install_codesign_cert.ps1" -ForegroundColor Yellow
