# ClipAI / Peakcut - Secure Deployment Guide

## Overview
This is a hardened, production-ready video clipping service with:
- **Security**: CSP, HSTS, rate limiting, CSRF protection, input validation, spend caps
- **Reliability**: Persistent job queue (SQLite/Redis), circuit breakers, health monitoring
- **Scalability**: Local hardware fallback for when cloud is overloaded
- **Observability**: Health checks, resource monitoring, detailed metrics

---

## Quick Start (Cloud - Render/Railway/Fly.io)

### 1. Fork/Clone Repository
```bash
git clone https://github.com/omixz/clipai.git
cd clipai
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your actual values
```

**Required secrets:**
- `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_PRICE_ID_PLUS`, `STRIPE_WEBHOOK_SECRET`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (OAuth)
- `SESSION_SECRET_KEY` (generate: `openssl rand -hex 32`)
- `RESEND_API_KEY` (email notifications)
- `ADSENSE_PUBLISHER_ID` (optional)

### 3. Deploy to Render
1. Connect repo to Render
2. Render auto-detects `render.yaml` and `Dockerfile`
3. Add environment variables in Render dashboard
4. Deploy!

### 4. Configure External Services
- **Stripe**: Create products/prices, add webhook URL `https://your-domain.com/stripe/webhook`
- **Google OAuth**: Add authorized redirect `https://your-domain.com/auth/google/callback`
- **Resend**: Verify domain, add API key
- **AdSense**: Add site, wait for approval

---

## Local Hardware Fallback (Hybrid Cloud-Local)

### Problem
Free-tier cloud hosts (Render 512MB) OOM on video processing.

### Solution
Run `local-worker` on your local hardware (PC, Mac, home server) to process jobs when cloud queue is full.

### Setup Local Worker
```bash
# On your local machine
git clone https://github.com/omixz/clipai.git
cd clipai

# Create .env with cloud connection
cat > .env << EOF
CLOUD_URL=https://your-domain.com
WORKER_API_KEY=your-generated-key
MAX_CONCURRENT_JOBS=2
MAX_MEMORY_PERCENT=85
EOF

# Run locally (no Docker needed)
pip install -r requirements.txt
python clipai_local_worker.py --cloud-url https://your-domain.com --api-key YOUR_KEY
```

### Enable in Cloud
Add to cloud `.env`:
```
ENABLE_LOCAL_FALLBACK=true
LOCAL_WORKER_URL=http://localhost:8001
LOCAL_WORKER_API_KEY=same-key-as-above
```

### How It Works
1. Cloud receives upload → checks local resources
2. If cloud overloaded → pushes job to local worker queue
3. Local worker picks up, processes, uploads results
4. Cloud returns clips to user

---

## Security Features

### Headers Applied
- `Content-Security-Policy`: Strict policy allowing only needed resources
- `Strict-Transport-Security`: 1 year HSTS in production
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Permissions-Policy`: No geolocation/mic/camera

### Rate Limits
| Endpoint | Limit |
|----------|-------|
| `/process` (upload) | 8/hour per IP |
| `/auth/*` | 10/5min per IP |
| API keys | 100-2000/month by tier |

### Spend Caps (Monthly)
| Service | Free | Pro | Pro+ |
|---------|------|-----|------|
| Whisper minutes | 1,000 | 5,000 | 20,000 |
| Google Translate chars | 5M | 25M | 100M |
| Piper TTS chars | 1M | 5M | 20M |

### Data Protection
- Secrets never logged (sanitized in errors)
- Secure cookies (HttpOnly, Secure, SameSite=Lax)
- API keys masked in responses
- Path traversal prevention

---

## Monitoring & Operations

### Health Endpoints
- `GET /healthz` - Basic health (for load balancer)
- `GET /api/health` - Detailed (resources, circuit breakers, queue)
- `GET /api/healthdetailed` - Background monitor state

### Admin Endpoints (require admin token)
- `GET /admin/stats` - Full system stats
- `POST /admin/jobs/cleanup` - Clean old jobs

### Circuit Breakers
Auto-disable failing external services:
- Stripe (billing)
- Whisper (transcription)
- Google Translate
- Piper TTS
- Resend (email)

### Resource Monitoring
Background thread tracks:
- CPU, memory, disk
- Recommends concurrency based on available resources
- Alerts when limits approached

---

## API Usage

### Upload Video (Web)
```bash
curl -X POST https://your-domain.com/process \
  -H "Cookie: clipai_cid=..." \
  -F "file=@video.mp4" \
  -F "clip_format=vertical" \
  -F "caption_style=bold"
```

### Upload Video (API Key)
```bash
curl -X POST https://your-domain.com/api/v1/process \
  -H "Authorization: Bearer pk_..." \
  -F "file=@video.mp4" \
  -F "clip_format=vertical"
```

### Check Status
```bash
curl https://your-domain.com/job/{job_id}
```

### Get Clips (API)
```bash
curl -H "Authorization: Bearer pk_..." \
  https://your-domain.com/api/v1/clips/{job_id}
```

---

## Docker Commands

### Build & Run Locally
```bash
docker build -t clipai .
docker run -p 8000:8000 --env-file .env clipai
```

### Full Stack (Cloud)
```bash
docker-compose up -d --build
```

### Local Worker Only
```bash
docker-compose -f docker-compose.yml up local-worker
```

---

## Troubleshooting

### OOM Killed
- Use `WHISPER_MODEL=tiny` (default)
- Reduce `MAX_CONCURRENT_JOBS=1`
- Enable local worker fallback

### Jobs Stuck
- Check `/admin/stats` for queue depth
- Run `POST /admin/jobs/cleanup`
- Check circuit breaker states in `/api/health`

### OAuth Failing
- Verify redirect URI exactly matches in Google Console
- Check `SESSION_SECRET_KEY` is 32+ chars
- Ensure `SITE_URL` uses HTTPS in production

### Webhooks Not Firing
- Verify `STRIPE_WEBHOOK_SECRET` matches Stripe Dashboard
- Check webhook endpoint accessible (not blocked by auth)
- Test with `stripe trigger checkout.session.completed`

---

## Architecture Diagram

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│   Client    │────▶│   Caddy     │────▶│    App       │
│  (Browser)  │     │  (HTTPS)    │     │  (FastAPI)   │
└─────────────┘     └─────────────┘     └──────┬───────┘
                                                │
                        ┌───────────────────────┼───────────────────────┐
                        ▼                       ▼                       ▼
                 ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
                 │   Queue     │         │  Stripe     │         │   Google    │
                 │ (SQLite/    │         │  (Billing)  │         │   (OAuth)   │
                 │  Redis)     │         └─────────────┘         └─────────────┘
                 └──────┬──────┘
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
   ┌─────────┐    ┌──────────┐   ┌──────────┐
   │ Whisper │    │ Piper    │   │  Google  │
   │ (Local) │    │ TTS      │   │ Translate│
   └────┬────┘    └────┬─────┘   └────┬─────┘
        │              │              │
        └──────────────┼──────────────┘
                       ▼
              ┌──────────────┐
              │ Local Worker │
              │ (Optional)   │
              └──────────────┘
```

---

## File Structure
```
clipai/
├── clipai_app.py          # Main FastAPI application
├── clipai_config.py       # Secure configuration
├── clipai_security.py     # Security middleware
├── clipai_auth.py         # OAuth authentication
├── clipai_queue.py        # Persistent job queue
├── clipai_monitoring.py   # Health & circuit breakers
├── clipai_local_worker.py # Local hardware worker
├── pipeline_lib.py        # Video processing
├── dub_lib.py             # Dubbing/translation
├── email_lib.py           # Email notifications
├── auth.py                # Google OAuth
├── config.py              # Legacy config (compat)
├── requirements.txt       # Python dependencies
├── Dockerfile             # Multi-stage build
├── docker-compose.yml     # Multi-service deployment
├── Caddyfile              # Reverse proxy config
├── render.yaml            # Render deployment
├── .env.example           # Environment template
└── jobs/                  # Job working directory
```

---

## Support

- **Health**: `GET /healthz` should return "ok"
- **Logs**: `docker-compose logs -f app`
- **Metrics**: `GET /api/health` for Prometheus/Grafana
- **Issues**: Check circuit breakers first, then resource stats