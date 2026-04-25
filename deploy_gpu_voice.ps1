#!/usr/bin/env pwsh
# Deploy voice module fixes to GPU machine (gpu.bpachter.dev)

param(
    [string]$GpuHost = "gpu.bpachter.dev",
    [string]$RemotePath = "/home/mithrandir/phase6-ui/server",
    [string]$User = "mithrandir",
    [string]$ServiceName = "mithrandir"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Mithrandir Voice Module GPU Deployment ===" -ForegroundColor Cyan
Write-Host ""

$localDir = "phase6-ui/server"
$filesToSync = @(
    "parakeet_asr.py",
    "voice_optim.py",
    "auto_ref_text.py",
    "build_kokoro_trt.py",
    "voice.py",
    "main.py"
)

Write-Host "Target: $User@$GpuHost`:$RemotePath" -ForegroundColor Yellow
Write-Host "Local source: $localDir" -ForegroundColor Yellow
Write-Host ""

# Check if files exist locally
Write-Host "Verifying local files..." -ForegroundColor Cyan
foreach ($file in $filesToSync) {
    $path = Join-Path $localDir $file
    if (Test-Path $path) {
        $size = (Get-Item $path).Length / 1KB
        Write-Host "  [OK] $file ($([math]::Round($size)) KB)"
    } else {
        Write-Host "  [FAIL] $file NOT FOUND" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Syncing files to GPU machine..." -ForegroundColor Cyan

# Try to copy each file
$failed = @()
foreach ($file in $filesToSync) {
    $localPath = Join-Path $localDir $file
    $remotePath = "$User@$GpuHost`:$RemotePath/$file"
    
    Write-Host "  Copying $file..." -ForegroundColor Gray
    $output = & scp -q $localPath $remotePath 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $file synced"
    } else {
        Write-Host "  [FAIL] $file - $output" -ForegroundColor Red
        $failed += $file
    }
}

Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "[SUCCESS] All files synced!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. SSH into GPU machine:"
    Write-Host "     ssh $User@$GpuHost"
    Write-Host "  2. Restart the service:"
    Write-Host "     systemctl restart $ServiceName"
    Write-Host "  3. Check status:"
    Write-Host "     systemctl status $ServiceName"
} else {
    Write-Host "[FAILED] Could not sync $($failed.Count) file(s):" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  - Test SSH: ssh $User@$GpuHost 'echo OK'"
    Write-Host "  - Check path: ssh $User@$GpuHost 'ls -la $RemotePath'"
    Write-Host "  - SSH key issue? Add -User parameter if needed"
    exit 1
}
