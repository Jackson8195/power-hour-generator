# Start Power Hour Studio in Docker, using the NVIDIA GPU automatically when this machine has one.
# PowerShell twin of scripts/docker-up.sh (see it for the reasoning).
#
# Usage: .\scripts\docker-up.ps1 [-DryRun] [docker compose args...]   (default: up --build -d)
#   $env:PH_FORCE_CPU = "1"   # never use the GPU
param(
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Test-NvidiaGpu {
    if ($env:PH_FORCE_CPU -eq "1") { return $false }
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { return $false }
    & nvidia-smi -L *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    $runtimes = (& docker info --format '{{json .Runtimes}}' 2>$null) -join ""
    return $runtimes -match "nvidia"
}

$files = @("-f", "docker-compose.yml")
if (Test-NvidiaGpu) {
    $files += @("-f", "docker-compose.gpu.yml")
    Write-Host "NVIDIA GPU + Docker NVIDIA runtime detected: GPU encoding enabled."
} else {
    Write-Host "No usable NVIDIA GPU for Docker: using CPU encoding."
}

if (-not $ComposeArgs -or $ComposeArgs.Count -eq 0) { $ComposeArgs = @("up", "--build", "-d") }

if ($DryRun) {
    Write-Host ("docker compose " + ($files -join " ") + " " + ($ComposeArgs -join " "))
} else {
    & docker compose @files @ComposeArgs
    exit $LASTEXITCODE
}
