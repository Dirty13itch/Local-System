# Setup Gen-Drops convenience access on Windows
# Run this once to map the VAULT gen-drops folder to a local drive letter.
#
# PREREQUISITES:
#   - VAULT (192.168.1.203) must have the "data" SMB share enabled in Unraid settings
#   - Go to: http://192.168.1.203 → Settings → SMB → User Shares → "data" → Export: Yes
#   - If the share isn't visible, you may need to enable it in Unraid's web UI
#
# ALTERNATIVE: Use the NFS mount path on DEV instead:
#   ssh shaun@192.168.1.189 "ls /mnt/vault/data/gen-drops/"
#   ssh shaun@192.168.1.189 "cp -r /path/to/photos /mnt/vault/data/gen-drops/person-name/"

$VaultIP = "192.168.1.203"
$ShareName = "data"
$SubPath = "gen-drops"
$DriveLetter = "G:"

Write-Host "=== Local-System Gen-Drops Setup ===" -ForegroundColor Cyan
Write-Host ""

# Check if already mapped
if (Test-Path "$DriveLetter\") {
    Write-Host "Drive $DriveLetter already mapped." -ForegroundColor Yellow
    Write-Host "Current mapping:"
    net use $DriveLetter
    Write-Host ""
    Write-Host "To remove: net use $DriveLetter /delete"
    exit 0
}

# Try to connect
Write-Host "Mapping \\$VaultIP\$ShareName\$SubPath to $DriveLetter ..."
Write-Host ""

try {
    # Try without credentials first (guest/public)
    net use $DriveLetter "\\$VaultIP\$ShareName\$SubPath" /persistent:yes 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "SUCCESS: Mapped to $DriveLetter" -ForegroundColor Green
    } else {
        # Try with credentials
        Write-Host "Public access failed. Enter VAULT credentials:"
        $user = Read-Host "Username"
        $pass = Read-Host "Password" -AsSecureString
        $plainPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass))
        net use $DriveLetter "\\$VaultIP\$ShareName\$SubPath" /user:$user $plainPass /persistent:yes
        if ($LASTEXITCODE -eq 0) {
            Write-Host "SUCCESS: Mapped to $DriveLetter" -ForegroundColor Green
        } else {
            Write-Host "FAILED: Could not map drive." -ForegroundColor Red
            Write-Host ""
            Write-Host "Troubleshooting:" -ForegroundColor Yellow
            Write-Host "  1. Open Unraid web UI: http://$VaultIP"
            Write-Host "  2. Go to Settings > SMB > SMB Extras"
            Write-Host "  3. Ensure the 'data' share is set to Export: Yes"
            Write-Host "  4. Check security settings allow your user"
            Write-Host ""
            Write-Host "Alternative: Access via File Explorer directly:"
            Write-Host "  \\$VaultIP\$ShareName\$SubPath"
            exit 1
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Usage ===" -ForegroundColor Cyan
Write-Host "Drop folders of photos into: $DriveLetter\"
Write-Host "Example: Copy 'C:\Photos\jane-doe\' to '$DriveLetter\jane-doe\'"
Write-Host ""
Write-Host "The auto-gen scanner will pick them up within 30 seconds."
Write-Host "Check progress at: http://192.168.1.189:3001/generate (Drops tab)"
