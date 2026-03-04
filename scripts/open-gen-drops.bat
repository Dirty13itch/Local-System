@echo off
REM Opens the gen-drops folder on VAULT in File Explorer
REM Drop folders of photos here — the auto-gen scanner will process them

start explorer "\\192.168.1.203\data\gen-drops"

echo.
echo If this failed, the "data" SMB share may not be enabled on Unraid.
echo Go to http://192.168.1.203 - Settings - SMB to enable it.
echo.
echo Alternative: Use SCP to copy directly to DEV:
echo   scp -r "C:\Photos\person-name" shaun@192.168.1.189:/mnt/vault/data/gen-drops/
echo.
pause
