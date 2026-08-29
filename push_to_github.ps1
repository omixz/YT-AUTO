# push_to_github.ps1 - Run this in PowerShell to push to GitHub

Set-Location "C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO"

$repoUrl = "https://github.com/omixz/clipai.git"

Write-Host "Initializing git..." -ForegroundColor Cyan
git init

Write-Host "Adding all files..." -ForegroundColor Cyan
git add .

Write-Host "Committing..." -ForegroundColor Cyan
git commit -m "Security hardening + local worker fallback

- Secure config with validation, spend caps, secrets management
- Security middleware: CSP, HSTS, rate limiting, CSRF, input validation
- Enhanced OAuth with JWKS verification, secure cookies
- Persistent job queue (SQLite + Redis), circuit breakers, health checks
- Local hardware worker fallback for cloud overflow
- Docker multi-stage build, Caddy auto-HTTPS"

Write-Host "Adding remote..." -ForegroundColor Cyan
try {
    git remote add origin $repoUrl
} catch {
    git remote set-url origin $repoUrl
}

Write-Host "Pushing to GitHub..." -ForegroundColor Cyan
git push -u origin main

Write-Host "Done! Check https://github.com/omixz/clipai" -ForegroundColor Green