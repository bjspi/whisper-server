# Installs Whisper Server: venv (.venv, Python 3.12 via uv), dependencies, autostart (HKCU Run), then starts the tray.
param([switch]$NoAutostart, [switch]$NoStart)

$root = $PSScriptRoot
Set-Location $root
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Error "uv not found - install it first (pip install uv)."; exit 1 }

if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    uv venv .venv --python 3.12
}
uv pip install --python "$root\.venv\Scripts\python.exe" -e "$root"
if ($LASTEXITCODE -ne 0) { Write-Error "Installing the dependencies failed."; exit 1 }

New-Item -ItemType Directory -Force "$root\models" | Out-Null
if (-not (Test-Path "$root\models\.nobackup")) {
    "Downloaded Whisper models - backup tools may skip this folder." | Set-Content "$root\models\.nobackup" -Encoding utf8
}

$pythonw = "$root\.venv\Scripts\pythonw.exe"
if (-not $NoAutostart) {
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "WhisperServer" `
        -Value "`"$pythonw`" -m whisperserver"
    Write-Host "Autostart enabled."
}
if (-not $NoStart) {
    Start-Process -FilePath $pythonw -ArgumentList "-m", "whisperserver" -WorkingDirectory $root
    Write-Host "Whisper Server started - tray icon; endpoint http://127.0.0.1:9017/v1/audio/transcriptions"
}
