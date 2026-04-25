# Mithrandir startup script — runs tunnel + server in background
# Place a shortcut to this in shell:startup for auto-launch on login

$ErrorActionPreference = 'SilentlyContinue'

$root = $PSScriptRoot
$tunnelName = if ($env:MITHRANDIR_CLOUDFLARE_TUNNEL) { $env:MITHRANDIR_CLOUDFLARE_TUNNEL } else { 'mithrandir' }
$tunnelName = if ($env:MITHRANDIR_CLOUDFLARE_TUNNEL) { $env:MITHRANDIR_CLOUDFLARE_TUNNEL } else { 'enkidu' }
Start-Process -WindowStyle Minimized -FilePath "cloudflared" -ArgumentList "tunnel run $tunnelName"

Start-Sleep -Seconds 4

$serverPath = Join-Path $root "phase6-ui\server"
Start-Process -WindowStyle Minimized -FilePath "python" -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $serverPath

Write-Host "Mithrandir started. Tunnel '$tunnelName' + server running in background."
