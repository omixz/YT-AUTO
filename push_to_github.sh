#!/usr/bin/env bash
# push_to_github.sh - Run this to push to GitHub

set -e

REPO_DIR="C:/Users/Omarn/OneDrive/Documents/Default Project/YT-AUTO"
REPO_URL="https://github.com/omixz/clipai.git"

cd "$REPO_DIR"

echo "Initializing git..."
git init

echo "Adding all files..."
git add .

echo "Committing..."
git commit -m "Security hardening + local worker fallback

- Secure config with validation, spend caps, secrets management
- Security middleware: CSP, HSTS, rate limiting, CSRF, input validation
- Enhanced OAuth with JWKS verification, secure cookies
- Persistent job queue (SQLite + Redis), circuit breakers, health checks
- Local hardware worker fallback for cloud overflow
- Docker multi-stage build, Caddy auto-HTTPS"

echo "Adding remote..."
git remote add origin "$REPO_URL" 2>/dev/null || git remote set-url origin "$REPO_URL"

echo "Pushing to GitHub..."
git push -u origin main

echo "Done! Check https://github.com/omixz/clipai"