# Registers a GitHub Actions self-hosted runner for wong80/splitsnap with the "splitsnap" label.
# Requires: gh CLI (logged in, repo admin), Docker Desktop. Run from any directory.
param(
    [string]$Repo = "wong80/splitsnap",
    [string]$Dir = "$HOME\actions-runner-splitsnap",
    [string]$Version = "2.338.0"
)
$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Set-Location $Dir

$zip = "actions-runner-win-x64-$Version.zip"
if (-not (Test-Path ".\config.cmd")) {
    $url = "https://github.com/actions/runner/releases/download/v$Version/$zip"
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath . -Force
    Remove-Item $zip
}

$token = gh api -X POST "repos/$Repo/actions/runners/registration-token" --jq .token
.\config.cmd --unattended --url "https://github.com/$Repo" --token $token `
    --name "$env:COMPUTERNAME-splitsnap" --labels "splitsnap" --work "_work" --replace

Write-Host "Runner registered. Start it with: cd $Dir; .\run.cmd"
