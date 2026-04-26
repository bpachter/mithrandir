# Mithrandir fast-lane setup helper
# Usage examples:
#   .\scripts\setup_fast_lane.ps1
#   .\scripts\setup_fast_lane.ps1 -Family llama
#   .\scripts\setup_fast_lane.ps1 -Family qwen -FastModel "qwen2.5:14b"

param(
    [ValidateSet("qwen", "llama")]
    [string]$Family = "qwen",
    [string]$FastModel = "",
    [string]$DeepModel = "gemma4:26b",
    [switch]$SkipPull
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot ".env"
$envExamplePath = Join-Path $repoRoot ".env.example"

if (-not (Test-Path $envPath)) {
    if (-not (Test-Path $envExamplePath)) {
        throw "Could not find .env or .env.example in repo root."
    }
    Copy-Item $envExamplePath $envPath
    Write-Host "Created .env from .env.example"
}

if ([string]::IsNullOrWhiteSpace($FastModel)) {
    if ($Family -eq "qwen") {
        $FastModel = "qwen2.5:7b"
    } else {
        $FastModel = "llama3.1:8b"
    }
}

function Set-Or-AppendEnvVar {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )

    $escapedKey = [regex]::Escape($Key)
    $lines = Get-Content $Path -ErrorAction Stop
    $found = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$escapedKey\s*=") {
            $lines[$i] = "$Key=$Value"
            $found = $true
            break
        }
    }

    if (-not $found) {
        $lines += "$Key=$Value"
    }

    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

Set-Or-AppendEnvVar -Path $envPath -Key "OLLAMA_MODEL" -Value $DeepModel
Set-Or-AppendEnvVar -Path $envPath -Key "OLLAMA_FAST_MODEL" -Value $FastModel
Set-Or-AppendEnvVar -Path $envPath -Key "OLLAMA_REACT_MODEL" -Value $DeepModel
Set-Or-AppendEnvVar -Path $envPath -Key "MITHRANDIR_FAST_LANE" -Value "1"
Set-Or-AppendEnvVar -Path $envPath -Key "MITHRANDIR_AGENT_MODE" -Value "local_react"

# Conservative latency defaults for voice-first conversational feel.
Set-Or-AppendEnvVar -Path $envPath -Key "MITHRANDIR_SPOKEN_MAX_TOKENS" -Value "384"
Set-Or-AppendEnvVar -Path $envPath -Key "MITHRANDIR_SHORT_REPLY_MAX_TOKENS" -Value "160"
Set-Or-AppendEnvVar -Path $envPath -Key "MITHRANDIR_REACT_MAX_TOKENS" -Value "768"

if (-not $SkipPull) {
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -ne $ollama) {
        Write-Host "Pulling fast-lane model: $FastModel"
        & ollama pull $FastModel
        Write-Host "Ensuring deep model exists: $DeepModel"
        & ollama pull $DeepModel
    } else {
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($null -eq $docker) {
            Write-Warning "Neither ollama nor docker was found in PATH. Install Ollama or Docker, then run:"
            Write-Host "  ollama pull $FastModel"
            Write-Host "  ollama pull $DeepModel"
        } else {
            $running = (& docker ps --format "{{.Names}}") -contains "ollama"
            if (-not $running) {
                Write-Warning "Docker is available, but no running container named 'ollama' was found."
                Write-Host "If your container has a different name, pull manually:"
                Write-Host "  docker exec <container-name> ollama pull $FastModel"
                Write-Host "  docker exec <container-name> ollama pull $DeepModel"
            } else {
                Write-Host "Host ollama not found; using Docker container 'ollama'."
                Write-Host "Pulling fast-lane model in Docker: $FastModel"
                & docker exec ollama ollama pull $FastModel
                Write-Host "Ensuring deep model exists in Docker: $DeepModel"
                & docker exec ollama ollama pull $DeepModel
            }
        }
    }
}

Write-Host ""
Write-Host "Fast-lane setup complete:"
Write-Host "  OLLAMA_FAST_MODEL=$FastModel"
Write-Host "  OLLAMA_MODEL=$DeepModel"
Write-Host "  OLLAMA_REACT_MODEL=$DeepModel"
Write-Host ""
Write-Host "Restart Mithrandir after this change."
