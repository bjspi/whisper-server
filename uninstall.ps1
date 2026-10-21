# Removes the autostart entry and stops Whisper Server (tray and server). Models and settings stay.
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "WhisperServer" -ErrorAction SilentlyContinue
$procs = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match '-m whisperserver(\.server)?(\s|$)' }
foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; "stopped PID $($p.ProcessId)" } catch { "ERR: $($_.Exception.Message)" }
}
Write-Host "Autostart removed. Delete the folder (and %LOCALAPPDATA%\WhisperServer) to uninstall completely."
