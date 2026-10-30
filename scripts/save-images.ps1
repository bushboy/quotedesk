# Build the QuoteDesk app image and save it as a tar archive.
# PostgreSQL stays the one already running on the host.
#
#   .\scripts\save-images.ps1
#   .\scripts\save-images.ps1 -Output D:\deploy
#
# On the other machine:
#   docker load -i quotedesk-app.tar
#   docker compose up
#
# The compose file in the deployment folder uses the loaded image and
# reaches Postgres at host.docker.internal:5432. Put a .env next to it.
# This script does not copy .env.

param(
    [string]$Output = "deployment"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "Dockerfile"))) {
    throw "Dockerfile not found beside scripts/. Run this from the QuoteDesk repo."
}

$Destination = if ([System.IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $Root $Output }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

Write-Host "Building quotedesk-app:latest"
docker build -t quotedesk-app:latest $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$appArchive = Join-Path $Destination "quotedesk-app.tar"

Write-Host "Saving quotedesk-app:latest"
docker save -o $appArchive quotedesk-app:latest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

@'
# Loaded image. PostgreSQL is the one already installed on this machine.
services:
  app:
    image: quotedesk-app:latest
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+psycopg://quotedesk:quotedesk@host.docker.internal:5432/quotedesk
    extra_hosts:
      - "host.docker.internal:host-gateway"
'@ | Set-Content -Encoding utf8 (Join-Path $Destination "docker-compose.yml")

Write-Host ""
Write-Host "Saved:"
Write-Host "  $appArchive"
Write-Host "Load with: docker load -i quotedesk-app.tar"
