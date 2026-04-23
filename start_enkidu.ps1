# Enkidu startup script — runs tunnel + server in background
# Place a shortcut to this in shell:startup for auto-launch on login

$ErrorActionPreference = 'SilentlyContinue'

# Start Cloudflare tunnel
Start-Process -WindowStyle Minimized -FilePath "cloudflared" -ArgumentList "tunnel run enkidu"

# Wait for tunnel to register
Start-Sleep -Seconds 4

# Start Enkidu server
$serverPath = "C:\Users\benpa\OneDrive\Desktop\Enkidu\phase6-ui\server"
Start-Process -WindowStyle Minimized -FilePath "python" -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $serverPath

Write-Host "Enkidu started. Tunnel + server running in background."
